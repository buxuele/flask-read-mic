import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import (
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRunInMode,
    CFMachPortCreateRunLoopSource,
    kCFRunLoopDefaultMode,
    kCGEventFlagMaskCommand,
    kCGEventKeyDown,
    kCGEventTapDisabledByTimeout,
    kCGEventTapOptionDefault,
    kCGHIDEventTap,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
)
from paste import paste_text

seen = []
stop_key = None


def callback(proxy, event_type, event, refcon):
    if event_type == kCGEventTapDisabledByTimeout:
        return event
    if event_type == kCGEventKeyDown:
        code = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        flags = CGEventGetFlags(event)
        if code == 9 and flags & kCGEventFlagMaskCommand:
            seen.append((code, bool(flags & kCGEventFlagMaskCommand)))
            return None
    return event


def main():
    global stop_key
    tap = CGEventTapCreate(
        kCGHIDEventTap,
        kCGHeadInsertEventTap,
        kCGEventTapOptionDefault,
        CGEventMaskBit(kCGEventKeyDown),
        callback,
        None,
    )
    if tap is None:
        raise RuntimeError("事件监听创建失败，检查辅助功能权限")
    source = CFMachPortCreateRunLoopSource(None, tap, 0)
    CFRunLoopAddSource(CFRunLoopGetCurrent(), source, kCFRunLoopDefaultMode)

    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setString_forType_("原有内容", NSPasteboardTypeString)

    paste_text("粘贴测试 ABC")
    CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.5, False)

    assert seen, "没有捕获到 Cmd+V 事件"
    assert board.stringForType_(NSPasteboardTypeString) == "粘贴测试 ABC"

    time.sleep(1.0)
    assert board.stringForType_(NSPasteboardTypeString) == "原有内容", "剪贴板未恢复"
    print(f"捕获 Cmd+V {len(seen)} 次，剪贴板已恢复")
    print("test_paste 通过")


if __name__ == "__main__":
    main()
