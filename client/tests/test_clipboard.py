import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from AppKit import NSPasteboard, NSPasteboardTypeString
from paste import copy_to_clipboard, restore_clipboard


def current():
    return NSPasteboard.generalPasteboard().stringForType_(NSPasteboardTypeString)


def put(text):
    board = NSPasteboard.generalPasteboard()
    board.clearContents()
    board.setString_forType_(text, NSPasteboardTypeString)


def test_restore_when_untouched():
    original = current()
    copy_to_clipboard("识别结果")
    previous, count = copy_to_clipboard("第二次写入")
    assert current() == "第二次写入"
    assert restore_clipboard(previous, count) is True
    assert current() == "识别结果"
    if original is not None:
        put(original)


def test_keep_user_copy():
    original = current()
    copy_to_clipboard("识别结果")
    put("用户后复制的内容")
    board = NSPasteboard.generalPasteboard()
    previous, count = "识别结果", board.changeCount() - 1
    assert restore_clipboard(previous, count) is False
    assert current() == "用户后复制的内容"
    if original is not None:
        put(original)


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_clipboard 通过")
