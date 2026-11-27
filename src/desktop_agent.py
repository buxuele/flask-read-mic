"""
全局语音输入代理（对标 macOS 听写）。

触发方式：
    双击 Ctrl  ->  开始录音（等价于 macOS 连按两次 Fn）
    再双击一次 / Esc / 静音超时  ->  停止
    按住 Ctrl  ->  也可触发（TRIGGER_HOLD 为真时启用）

停止后自动转录，并按焦点窗口类型选择注入方式：
    普通窗口  ->  Ctrl+V 粘贴
    终端窗口  ->  Ctrl+Shift+V 粘贴（Windows Terminal / conhost 更稳）
    纯 ASCII  ->  直接逐字敲击，完全不碰剪贴板

录音期间若按下其它功能键（Ctrl+C / Ctrl+V 等），一律视为真实快捷键，
立即让路，绝不劫持正常使用。
"""

import ctypes
import io
import os
import queue
import threading
import time
import wave
import webbrowser

import keyboard
import numpy as np

from config import SERVER_HOST, SERVER_PORT
from logger import app_logger

# sounddevice 在 import 时就会初始化 PortAudio，动辄几百毫秒。
# 只有真的要开麦时才导入，让托盘能秒起。
_sd = None


def _audio():
    global _sd
    if _sd is None:
        import sounddevice as sd

        _sd = sd
    return _sd

# ---------- 触发方式 ----------
TRIGGER_DOUBLE_TAP = True
TRIGGER_HOLD = True
DOUBLE_TAP_INTERVAL = 0.42      # 两次 Ctrl 按下的最大间隔（秒）
HOLD_TRIGGER_SECONDS = 0.5      # 单次 Ctrl 按住超过此时长视为「按住」触发
COMBO_KEY_GRACE = 0.12          # 按下 Ctrl 后此窗口内按其它键即判为组合键
PRESS_SETTLE_SECONDS = 0.12

# ---------- 录音参数 ----------
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_SIZE = 1600
SILENCE_RMS = 0.008
MIN_SPEAKING_RMS = 0.006
MIN_RECORD_SECONDS = 0.4
MAX_RECORD_SECONDS = 30.0
TRAILING_SILENCE_SECONDS = 0.35
SILENCE_AUTO_STOP = 0.5         # 说完静音这么久自动收尾，越短越跟手，过长会让人觉得卡

# ---------- 文本注入 ----------
PASTE_SETTLE_SECONDS = 0.12
AUTO_ENTER_AFTER_TYPE = False
# 纯 ASCII 文本直接敲字，绕开剪贴板，终端与各类 TUI 通吃
TYPEWRITE_ASCII = True
TYPEWRITE_MAX_CHARS = 240
TYPEWRITE_INTERVAL = 0.004
# 终端内注入后自动回车（opencode CLI 这类命令行场景需要）
AUTO_ENTER_IN_TERMINAL = True
# 终端粘贴热键：Windows Terminal 两者都吃，Ctrl+Shift+V 在 conhost 更稳
TERMINAL_PASTE_HOTKEY = ("ctrl", "shift", "v")
NORMAL_PASTE_HOTKEY = ("ctrl", "v")

# ---------- 窗口类型识别 ----------
TERMINAL_CLASS_HINTS = (
    "cascadia_hosting_window_class",   # Windows Terminal
    "consolewindowclass",              # conhost
    "putty",                           # PuTTY
    "mintty",                          # Git Bash
    "xterm",                           # VcXsrv / X11
    "konsole", "gnome-terminal", "alacritty", "wezterm", "kitty",
)
TERMINAL_TITLE_HINTS = (
    "opencode", "windows terminal", "powershell", "cmd.exe",
    "ubuntu", "wsl", "git bash", "hyper",
)
# 这些窗口即使识别成终端，也按普通窗口处理（它们不吃终端粘贴键）
TERMINAL_EXCLUDE_TITLES = ("visual studio code", "code -", "notepad")

# ---------- Flask 服务（端口与 host 统一由 config 提供，避免两处漂移） ----------
FLASK_BASE = f"http://127.0.0.1:{SERVER_PORT}"
FLASK_TIMEOUT = 180


# ---------- 前台窗口识别 ----------
def _foreground_info():
    """返回 (窗口类名, 标题)，失败时返回空串"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return '', ''
        cls_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls_buf, 256)
        length = user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buf, length + 1)
        return cls_buf.value, title_buf.value
    except Exception as e:
        app_logger.warning(f"前台窗口识别失败: {e}")
        return '', ''


def is_terminal_foreground():
    """判断焦点窗口是否为终端。VS Code 等虽然跑在终端里，但要用普通粘贴键。"""
    cls, title = _foreground_info()
    low_cls = cls.lower()
    low_title = title.lower()

    if any(bad in low_title for bad in TERMINAL_EXCLUDE_TITLES):
        return False
    if any(hint in low_cls for hint in TERMINAL_CLASS_HINTS):
        return True
    return any(hint in low_title for hint in TERMINAL_TITLE_HINTS)


def describe_foreground():
    cls, title = _foreground_info()
    kind = '终端' if is_terminal_foreground() else '窗口'
    return f"{kind} · {title or cls or '未知'}"[:60]


class AudioRecorder:
    """按 16kHz 单声道采集麦克风数据，松手后吐出 WAV 字节流。"""

    def __init__(self):
        self._frames = queue.Queue()
        self._stream = None
        self._recording = False
        self._last_rms = 0.0
        self._peak_rms = 0.0

    def _callback(self, indata, frames, time_info, status):
        rms = float(np.sqrt(np.mean(indata.astype(np.float64) ** 2)))
        self._last_rms = rms
        if rms > self._peak_rms:
            self._peak_rms = rms
        self._frames.put(indata.copy())

    def start(self):
        self._frames = queue.Queue()
        self._recording = True
        self._last_rms = 0.0
        self._peak_rms = 0.0
        self._stream = _audio().InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=BLOCK_SIZE,
            callback=self._callback,
        )
        self._stream.start()

    def stop(self):
        if not self._recording:
            return None
        self._recording = False
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

        chunks = []
        while not self._frames.empty():
            chunks.append(self._frames.get_nowait())
        if not chunks:
            app_logger.warning("录音结束但未捕获到任何音频帧")
            return None

        samples = np.concatenate(chunks, axis=0).reshape(-1)
        if samples.size == 0:
            return None

        trailing = int(TRAILING_SILENCE_SECONDS * SAMPLE_RATE)
        if samples.size > trailing:
            samples = samples[:-trailing]
        if samples.size == 0:
            return None

        return self._to_wav(samples)

    @staticmethod
    def _to_wav(samples):
        clipped = np.clip(samples, -1.0, 1.0)
        pcm = (clipped * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav:
            wav.setnchannels(CHANNELS)
            wav.setsampwidth(2)
            wav.setframerate(SAMPLE_RATE)
            wav.writeframes(pcm.tobytes())
        return buffer.getvalue()

    def is_speaking(self):
        """最近一帧响度，用于托盘实时反馈"""
        return self._last_rms > SILENCE_RMS

    def had_speech(self):
        """整段录音的峰值响度，用于识别误触（没说话就别浪费 GPU）"""
        return self._peak_rms > MIN_SPEAKING_RMS


# 桌面代理默认直接转录并注入文字；指令模式（搜索/记事）留给网页端。
# 若这里走 command，每句话都会同步调用 LLM 解析意图，网络一慢就直接拖垮输入延迟。
DESKTOP_MODE = "dictate"


def transcribe_via_flask(wav_bytes, language="zh", mode=DESKTOP_MODE):
    """把录音送回本地 Flask 转录，立即返回文本。

    归档收尾放到后台线程，绝不让合并音频或校对阻塞用户拿到文字。
    """
    import requests

    session_id = requests.post(
        f"{FLASK_BASE}/session/start", timeout=30
    ).json()["session_id"]

    response = requests.post(
        f"{FLASK_BASE}/transcribe",
        files={"audio": ("clip.wav", wav_bytes, "audio/wav")},
        data={"session_id": session_id, "language": language, "mode": mode},
        timeout=FLASK_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload["error"])

    text = payload.get("text", "").strip()

    def archive():
        try:
            requests.post(
                f"{FLASK_BASE}/session/{session_id}/finalize",
                timeout=60,
            )
        except Exception as e:
            app_logger.warning(f"会话归档失败（不影响已输出文字）: {e}")

    threading.Thread(target=archive, daemon=True).start()
    return session_id, text


def _is_plain_ascii(text):
    return text.isascii() and text.isprintable()


def inject_text(text, terminal=None):
    """把文本打进当前焦点窗口。

    terminal=None 表示现场判断焦点窗口类型。纯 ASCII 优先逐字敲击：
    不碰剪贴板，终端、编辑器、TUI 输入框全部通吃。
    """
    import pyautogui

    pyautogui.FAILSAFE = False
    if not text:
        return

    if terminal is None:
        terminal = is_terminal_foreground()

    if TYPEWRITE_ASCII and _is_plain_ascii(text) and len(text) <= TYPEWRITE_MAX_CHARS:
        pyautogui.typewrite(text, interval=TYPEWRITE_INTERVAL)
    else:
        import pyperclip

        pyperclip.copy(text)
        time.sleep(PASTE_SETTLE_SECONDS)
        pyautogui.hotkey(*(TERMINAL_PASTE_HOTKEY if terminal else NORMAL_PASTE_HOTKEY))

    should_enter = AUTO_ENTER_IN_TERMINAL if terminal else AUTO_ENTER_AFTER_TYPE
    if should_enter:
        time.sleep(PASTE_SETTLE_SECONDS)
        pyautogui.press("enter")

    kind = '终端' if terminal else '窗口'
    app_logger.info(f"注入文本[{kind}]: {text}")


def flask_is_alive():
    import requests

    try:
        requests.get(f"{FLASK_BASE}/model", timeout=3)
        return True
    except requests.RequestException:
        return False


def wait_for_flask(timeout=60):
    """等待识别服务与模型都就绪。只等 HTTP 200 会在模型未加载时注册热键，
    用户双击后请求会阻塞在模型锁上，表现为无响应。"""
    import json
    import requests

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            requests.get(f"{FLASK_BASE}/model", timeout=2)
            info = requests.get(f"{FLASK_BASE}/model/status", timeout=2).json()
            if info.get("status") == "ready":
                return True
            if info.get("status") == "error":
                app_logger.error(f"模型加载失败: {info.get('error')}")
                return False
        except requests.RequestException:
            pass
        time.sleep(0.4)
    return False


IDLE, RECORDING, WORKING = "idle", "recording", "working"


def _ctrl_keys():
    """keyboard.Key 需要管理员权限才能解析，延迟到真正跑起来时再取"""
    return (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r)


def _is_ctrl(key):
    name = getattr(key, "name", None)
    return name in ("ctrl", "ctrl_l", "ctrl_r")



LABELS = {
    IDLE: "待机 - 双击 Ctrl 开始说话",
    RECORDING: "录音中 - 再双击或静音自动结束",
    WORKING: "处理中 - 识别并输入",
}

TRIGGER_HINT = "双击 Ctrl" if TRIGGER_DOUBLE_TAP else "长按 Ctrl"
if TRIGGER_DOUBLE_TAP and TRIGGER_HOLD:
    TRIGGER_HINT = "双击或长按 Ctrl"


class VoiceAgent:
    def __init__(self):
        self.recorder = AudioRecorder()
        self.state = IDLE
        self._busy = False
        self._on_state_change = lambda _: None

        # 双击检测：记录上一次「完整按下-松开」Ctrl 的时间戳
        self._last_tap_time = 0.0

        # 按住检测
        self._hold_token = 0

        # 组合键让路
        self._combo_used = False
        self._hold_down = False
        self._trigger = None

    # ---------- 状态 ----------
    def set_state(self, state):
        self.state = state
        self._on_state_change(state)

    # ---------- 热键回调（keyboard 库线程，绝不能在此做阻塞 IO）----------
    def on_press(self, key):
        if _is_ctrl(key):
            self._on_ctrl_down()
        else:
            self._on_other_down()

    def on_release(self, key):
        if _is_ctrl(key):
            self._on_ctrl_up()

    def _on_ctrl_down(self):
        if self._busy or self.state == WORKING:
            return

        # 已在录音中：再双击一次即停止（对标 macOS 再次按 Fn）
        if self.state == RECORDING and TRIGGER_DOUBLE_TAP:
            now = time.time()
            if now - self._last_tap_time <= DOUBLE_TAP_INTERVAL:
                self._last_tap_time = 0.0
                threading.Thread(target=self._finish_recording, daemon=True).start()
            else:
                self._last_tap_time = now
            return

        self._combo_used = False
        self._hold_down = True
        self._hold_token += 1
        threading.Thread(
            target=self._watch_hold, args=(self._hold_token,), daemon=True
        ).start()

    def _on_ctrl_up(self):
        if not self._hold_down:
            return
        self._hold_down = False

        # 按住模式：松手即收尾
        if self.state == RECORDING and self._trigger == 'hold':
            threading.Thread(target=self._finish_recording, daemon=True).start()
            return

        now = time.time()
        if TRIGGER_DOUBLE_TAP and now - self._last_tap_time <= DOUBLE_TAP_INTERVAL:
            # 间隔内的第二次松手 = 一次完整双击
            self._last_tap_time = 0.0
            if self.state == IDLE:
                threading.Thread(
                    target=self._begin_recording, kwargs={'trigger': 'double'}, daemon=True
                ).start()
        else:
            self._last_tap_time = now

    def _watch_hold(self, token):
        time.sleep(HOLD_TRIGGER_SECONDS)
        if not TRIGGER_HOLD or self._hold_token != token:
            return
        if not self._hold_down or self._combo_used:
            return
        if self.state != IDLE:
            return
        # 按住期间双击计时器已失效，这里独占触发
        self._last_tap_time = 0.0
        threading.Thread(
            target=self._begin_recording, kwargs={'trigger': 'hold'}, daemon=True
        ).start()

    def _on_other_down(self):
        # 按住待判定期出现其它键 = 用户真实快捷键，立即让路
        if self._hold_down and self.state == IDLE:
            self._combo_used = True
            return
        if self.state == RECORDING and self._trigger == 'hold':
            threading.Thread(target=self._abort_recording, daemon=True).start()

    # ---------- 录音生命周期（均在独立线程执行）----------
    def _begin_recording(self, trigger='double'):
        if self.state != IDLE:
            return
        self._trigger = trigger
        self._last_tap_time = 0.0
        try:
            self.recorder.start()
            self.set_state(RECORDING)
            started = time.time()
            last_voice = time.time()
            while self.state == RECORDING:
                if time.time() - started > MAX_RECORD_SECONDS:
                    self._finish_recording()
                    return
                if self.recorder.is_speaking():
                    last_voice = time.time()
                elif time.time() - last_voice > SILENCE_AUTO_STOP:
                    self._finish_recording()
                    return
                time.sleep(0.05)
        except Exception as e:
            app_logger.error(f"录音启动失败: {e}")
            self._reset()

    def _reset(self):
        self._hold_down = False
        self._combo_used = False
        self._last_tap_time = 0.0
        self.set_state(IDLE)

    def _abort_recording(self):
        self.recorder.stop()
        self._reset()

    def _finish_recording(self):
        if self.state != RECORDING:
            return
        had_speech = self.recorder.had_speech()
        wav_bytes = self.recorder.stop()
        self._reset()
        if not wav_bytes or not had_speech:
            app_logger.info("静音或空录音，丢弃")
            return

        self._busy = True
        self.set_state(WORKING)
        try:
            self._handle(wav_bytes)
        except Exception as e:
            app_logger.error(f"语音处理失败: {e}")
        finally:
            self._busy = False
            self.set_state(IDLE)

    def _handle(self, wav_bytes):
        session_id, text = transcribe_via_flask(wav_bytes)
        app_logger.info(f"桌面转录完成: {session_id} -> {text}")
        if not text:
            return

        from commander import execute_command

        consumed, result = execute_command(text)
        if result:
            app_logger.info(f"指令执行: {result}")
        if not consumed:
            # 既不是指令也不是可识别意图，直接当作要说的话注入焦点窗口
            inject_text(text)


def make_icon_image(color, size=64):
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((6, 6, size - 6, size - 6), fill=color)
    return image


def main():
    import pystray

    agent = VoiceAgent()
    icons = {
        IDLE: make_icon_image("#555555"),
        RECORDING: make_icon_image("#d9234a"),
        WORKING: make_icon_image("#c8a44a"),
    }
    menu = pystray.Menu(
        pystray.MenuItem(lambda _item: LABELS[agent.state], None, enabled=False),
        pystray.MenuItem(
            lambda _item: f"目标：{describe_foreground()}", None, enabled=False
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            f"终端内自动回车：{'开' if AUTO_ENTER_IN_TERMINAL else '关'}",
            toggle_enter,
        ),
        pystray.MenuItem("打开控制面板", lambda _item: webbrowser.open(FLASK_BASE)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda _item: icon.stop()),
    )

    icon = pystray.Icon("flask-read-mic", icons[IDLE], "语音输入", menu)
    agent._on_state_change = lambda state: setattr(icon, "icon", icons[state])
    agent._on_state_change(IDLE)

    def register_hotkeys():
        if not wait_for_flask():
            app_logger.error(f"模型未在超时内就绪（{FLASK_BASE}），热键未注册")
            return
        keyboard.on_press(agent.on_press)
        keyboard.on_release(agent.on_release)
        app_logger.info(f"热键已就绪，{TRIGGER_HINT} 说话")

    threading.Thread(target=register_hotkeys, name="hotkey-register", daemon=True).start()

    app_logger.info("托盘已启动，等待模型预热")
    icon.run()


def toggle_enter(item):
    global AUTO_ENTER_IN_TERMINAL
    AUTO_ENTER_IN_TERMINAL = not AUTO_ENTER_IN_TERMINAL
    app_logger.info(f"终端自动回车已{'开启' if AUTO_ENTER_IN_TERMINAL else '关闭'}")
    item.text = f"终端内自动回车：{'开' if AUTO_ENTER_IN_TERMINAL else '关'}"


if __name__ == "__main__":
    main()
