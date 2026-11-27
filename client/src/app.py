#!/usr/bin/env python3
import fcntl
import logging
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import objc
from objc import python_method
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSColor,
    NSImage,
    NSMenu,
    NSMenuItem,
    NSPasteboard,
    NSPasteboardTypeString,
    NSStatusBar,
    NSTimer,
    NSVariableStatusItemLength,
    NSWorkspace,
    NSEvent,
    NSEventMaskFlagsChanged,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSEventTypeFlagsChanged,
    NSEventTypeKeyDown,
)
from Foundation import NSObject, NSURL
from PyObjCTools import AppHelper

import config
import permissions
from asr import health, transcribe
from controller import Controller
from paste import paste_text
from recorder import Recorder, list_input_devices
from store import Store

ICONS = {
    "idle": ("mic", None),
    "recording": ("mic.fill", "red"),
    "busy": ("ellipsis", None),
    "error": ("exclamationmark.triangle.fill", "orange"),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_DIR / "app.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("mic")


def beep(name):
    from AppKit import NSSound

    sound = NSSound.soundNamed_(name)
    if sound is not None:
        sound.play()


class MicApp(NSObject):
    def init(self):
        self = objc.super(MicApp, self).init()
        if self is None:
            return None
        self.last_error = ""
        self.last_paste_at = 0.0
        self.monitor = None
        self.ctrl_down = False
        self.health = ""
        self.health_at = 0.0
        self.error_timer = None
        store = Store(config.RECORD_DIR) if config.SAVE_AUDIO else None
        self.controller = Controller(
            recorder=Recorder(
                rate=config.SAMPLE_RATE,
                device=config.MIC_DEVICE,
                threshold=config.CHUNK_THRESHOLD,
                silence_gap=config.CHUNK_SILENCE,
            ),
            run_asr=lambda wav, ctx: transcribe(wav, config.LANGUAGE, context=ctx),
            on_state=self._on_state,
            on_text=self._on_text,
            on_error=self._on_error,
            min_seconds=config.MIN_SECONDS,
            max_seconds=config.MAX_SECONDS,
            audio_limit=config.AUDIO_LIMIT,
            min_rms=config.MIN_RMS,
            store=store,
            on_verify=self._on_verify,
        )
        return self

    def applicationDidFinishLaunching_(self, notification):
        self._build_menu()
        self._install_monitor()
        self._check_permissions()
        self._refresh_health()
        NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.2, self, "tick:", None, True
        )
        log.info("听写已就绪，按住 Ctrl 说话")

    @python_method
    def _build_menu(self):
        NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
        self.status_item.button().setToolTip_("按住 Ctrl 说话，松开转录")
        self._apply_icon("idle")

        menu = NSMenu.alloc().init()
        menu.setDelegate_(self)

        hint = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("按住 Ctrl 说话，松开转录", None, "")
        hint.setEnabled_(False)
        menu.addItem_(hint)
        menu.addItem_(NSMenuItem.separatorItem())

        self.state_item = self._disabled_item("状态：就绪")
        self.health_item = self._disabled_item("接口：检查中")
        self.perm_item = self._disabled_item("权限：检查中")
        menu.addItem_(self.state_item)
        menu.addItem_(self.health_item)
        menu.addItem_(self.perm_item)
        menu.addItem_(NSMenuItem.separatorItem())

        self.last_item = self._disabled_item("最近识别：无")
        self.copy_item = self._menu_item("复制最近识别", "copyLast:")
        self.copy_item.setEnabled_(False)
        menu.addItem_(self.last_item)
        menu.addItem_(self.copy_item)
        self.verify_item = self._disabled_item("复核：未运行")
        self.verify_copy_item = self._menu_item("复制复核结果", "copyVerify:")
        self.verify_copy_item.setEnabled_(False)
        menu.addItem_(self.verify_item)
        menu.addItem_(self.verify_copy_item)
        menu.addItem_(self._menu_item("测试粘贴", "testPaste:"))
        menu.addItem_(NSMenuItem.separatorItem())

        self.device_menu = NSMenu.alloc().init()
        device_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("麦克风", None, "")
        device_item.setSubmenu_(self.device_menu)
        menu.addItem_(device_item)

        self.language_menu = NSMenu.alloc().init()
        language_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("语言", None, "")
        language_item.setSubmenu_(self.language_menu)
        menu.addItem_(language_item)
        menu.addItem_(NSMenuItem.separatorItem())

        menu.addItem_(self._menu_item("打开录音目录", "openRecords:"))
        menu.addItem_(self._menu_item("打开日志", "openLog:"))
        menu.addItem_(self._menu_item("打开隐私设置", "openPrivacy:"))
        menu.addItem_(NSMenuItem.separatorItem())
        menu.addItem_(self._menu_item("退出", "quit:"))

        self.status_item.setMenu_(menu)
        self._rebuild_device_menu()
        self._rebuild_language_menu()

    @python_method
    def _disabled_item(self, title):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, None, "")
        item.setEnabled_(False)
        return item

    @python_method
    def _menu_item(self, title, action):
        item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, "")
        item.setTarget_(self)
        return item

    def menuWillOpen_(self, menu):
        self._refresh_menu()
        self._refresh_health()

    @python_method
    def _rebuild_device_menu(self):
        self.device_menu.removeAllItems()
        default = self._menu_item("默认输入", "setDevice:")
        default.setRepresentedObject_("")
        default.setState_(0 if config.MIC_DEVICE else 1)
        self.device_menu.addItem_(default)
        for index, name in list_input_devices():
            item = self._menu_item(name, "setDevice:")
            item.setRepresentedObject_(name)
            selected = config.MIC_DEVICE == name or config.MIC_DEVICE == index
            item.setState_(1 if selected else 0)
            self.device_menu.addItem_(item)

    @python_method
    def _rebuild_language_menu(self):
        self.language_menu.removeAllItems()
        for code, label in config.LANGUAGES:
            item = self._menu_item(label, "setLanguage:")
            item.setRepresentedObject_(code)
            item.setState_(1 if config.LANGUAGE == code else 0)
            self.language_menu.addItem_(item)

    @python_method
    def _on_verify(self, text, matched):
        prefix = "复核：一致" if matched else "复核：有差异，可复制"
        AppHelper.callAfter(self.verify_item.setTitle_, prefix)
        AppHelper.callAfter(self.verify_copy_item.setEnabled_, not matched)

    @python_method
    def _refresh_menu(self):
        labels = {"idle": "就绪", "recording": "录音中", "busy": "识别中"}
        text = labels.get(self.controller.state, self.controller.state)
        if self.last_error:
            error = self.last_error
            if len(error) > 24:
                error = error[:24] + "…"
            text = f"{text}，上次错误：{error}"
        self.state_item.setTitle_(f"状态：{text}")

        self.health_item.setTitle_(f"接口：{self.health or '检查中'}")
        ax = "已授权" if permissions.ax_trusted() else "未授权"
        self.perm_item.setTitle_(f"权限：麦克风 {permissions.mic_text()}，辅助功能 {ax}")

        if self.controller.last_text:
            preview = self.controller.last_text
            if len(preview) > 24:
                preview = preview[:24] + "…"
            elapsed = self.controller.last_elapsed
            prefix = f"最近识别 {elapsed:.1f}s" if elapsed else "最近识别"
            self.last_item.setTitle_(f"{prefix}：{preview}")
            self.copy_item.setEnabled_(True)

    @python_method
    def _apply_icon(self, state):
        name, tint = ICONS[state]
        image = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if image is not None:
            image.setTemplate_(True)
            self.status_item.button().setImage_(image)
        colors = {"red": NSColor.systemRedColor, "orange": NSColor.systemOrangeColor}
        color = colors[tint]() if tint in colors else None
        self.status_item.button().setContentTintColor_(color)

    @python_method
    def _check_permissions(self):
        if permissions.mic_status() == 0:
            permissions.request_mic()
        if not permissions.ax_trusted(prompt=True):
            log.warning("缺少辅助功能权限，键盘监听和自动粘贴不会生效")
            self.last_error = "缺少辅助功能权限"
            beep("Basso")
        if not config.ASR_URL or not config.ASR_KEY:
            log.error("未配置 ASR_URL 或 ASR_KEY")
            self.last_error = "未配置接口"
            beep("Basso")

    @python_method
    def _install_monitor(self):
        mask = NSEventMaskFlagsChanged | NSEventMaskKeyDown
        self.monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self._handle_event)
        if self.monitor is None:
            log.error("键盘监听注册失败，检查辅助功能权限")
            self.last_error = "键盘监听失败"

    @python_method
    def _handle_event(self, event):
        try:
            event_type = event.type()
            if event_type == NSEventTypeFlagsChanged:
                flags = event.modifierFlags()
                down = bool(flags & NSEventModifierFlagControl)
                if down and not self.ctrl_down:
                    self.ctrl_down = True
                    combo = bool(flags & (NSEventModifierFlagCommand | NSEventModifierFlagOption))
                    self.controller.press(combo=combo)
                elif not down and self.ctrl_down:
                    self.ctrl_down = False
                    self.controller.release()
            elif event_type == NSEventTypeKeyDown:
                if self.ctrl_down:
                    if self.controller.state == "recording" and event.keyCode() == 53:
                        self.controller.cancel()
                    else:
                        self.controller.combo = True
                        if self.controller.state == "recording":
                            self.controller.cancel()
        except Exception as error:
            log.exception("热键处理异常")
            self.last_error = str(error)

    def tick_(self, timer):
        self.controller.poll()
        if self.controller.state == "recording":
            seconds = int(self.controller.elapsed())
            self.status_item.setTitle_(f"{seconds}s")
            if seconds >= config.MAX_SECONDS:
                log.info("达到时长上限，自动结束")
                self.controller.release()

    @python_method
    def _on_state(self, state):
        if state == "recording":
            log.info("开始录音")
        elif state == "busy":
            log.info("上传识别")
        AppHelper.callAfter(self._render_state, state)

    @python_method
    def _render_state(self, state):
        self._apply_icon(state)
        self.status_item.setTitle_("" if state != "recording" else "0s")

    @python_method
    def _on_text(self, text, elapsed):
        AppHelper.callAfter(self._deliver, text, elapsed)

    @python_method
    def _deliver(self, text, elapsed):
        if not permissions.ax_trusted():
            self.last_error = "缺少辅助功能权限，文本已放进剪贴板"
            log.error("没有辅助功能权限，无法模拟 Cmd+V")
            self._flash_error()
            return
        wait = 0.15 - (time.monotonic() - self.last_paste_at)
        if wait > 0:
            time.sleep(wait)
        self.last_error = ""
        target = NSWorkspace.sharedWorkspace().frontmostApplication()
        target_name = target.localizedName() if target else "当前窗口"
        paste_text(text)
        self.last_paste_at = time.monotonic()
        log.info("已粘贴到 %s（%.1fs）：%s", target_name, elapsed, text)

    @python_method
    def _on_error(self, message):
        self.last_error = message
        log.error("%s", message)
        AppHelper.callAfter(self._flash_error)

    @python_method
    def _flash_error(self):
        beep("Basso")
        self._apply_icon("error")
        if self.error_timer is not None:
            self.error_timer.invalidate()
        self.error_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            2.5, self, "clearError:", None, False
        )

    def clearError_(self, timer):
        self.error_timer = None
        self._apply_icon("idle")
        self.status_item.setTitle_("")

    @python_method
    def _refresh_health(self):
        if time.monotonic() - self.health_at < 20:
            return
        self.health_at = time.monotonic()
        threading.Thread(target=self._check_health, daemon=True).start()

    @python_method
    def _check_health(self):
        try:
            ok = health()
        except Exception:
            ok = False
        AppHelper.callAfter(self._set_health, ok)

    @python_method
    def _set_health(self, ok):
        self.health = "正常" if ok else "不可达"
        self.health_item.setTitle_(f"接口：{self.health}")

    def setDevice_(self, sender):
        name = sender.representedObject() or ""
        config.MIC_DEVICE = name or None
        config.save_setting("MIC_DEVICE", name)
        self.controller.recorder.device = config.MIC_DEVICE
        log.info("麦克风切换为 %s", name or "默认输入")
        self._rebuild_device_menu()

    def setLanguage_(self, sender):
        code = sender.representedObject()
        config.LANGUAGE = code
        config.save_setting("LANGUAGE", code)
        log.info("语言切换为 %s", code)
        self._rebuild_language_menu()

    def testPaste_(self, sender):
        if not permissions.ax_trusted():
            self.last_error = "缺少辅助功能权限，无法测试粘贴"
            self._flash_error()
            return
        paste_text("粘贴测试：能看到这行字说明自动输入可用。", restore_delay=1.2)
        log.info("已发送测试粘贴")

    def copyVerify_(self, sender):
        text = self.controller.last_verify
        if not text:
            return
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(text, NSPasteboardTypeString)

    def copyLast_(self, sender):
        text = self.controller.last_text
        if not text:
            return
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        board.setString_forType_(text, NSPasteboardTypeString)

    def openRecords_(self, sender):
        config.RECORD_DIR.mkdir(parents=True, exist_ok=True)
        NSWorkspace.sharedWorkspace().openFile_(str(config.RECORD_DIR))

    def openLog_(self, sender):
        NSWorkspace.sharedWorkspace().openFile_(str(config.LOG_DIR / "app.log"))

    def openPrivacy_(self, sender):
        url = NSURL.URLWithString_("x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")
        NSWorkspace.sharedWorkspace().openURL_(url)

    def quit_(self, sender):
        log.info("退出")
        NSApplication.sharedApplication().terminate_(None)


def main():
    config.LOG_DIR.mkdir(exist_ok=True)
    lock_handle = open(config.LOG_DIR / "app.lock", "w")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("听写已在运行")
        return

    app = NSApplication.sharedApplication()
    delegate = MicApp.alloc().init()
    app.setDelegate_(delegate)
    AppHelper.runEventLoop()


if __name__ == "__main__":
    main()
