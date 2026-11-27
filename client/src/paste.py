import threading
import time

from AppKit import NSPasteboard, NSPasteboardTypeString
from Quartz import (
    CGEventCreateKeyboardEvent,
    CGEventPost,
    CGEventSetFlags,
    kCGEventFlagMaskCommand,
    kCGHIDEventTap,
)

PASTE_KEYCODE = 9


def copy_to_clipboard(text):
    board = NSPasteboard.generalPasteboard()
    previous = board.stringForType_(NSPasteboardTypeString)
    board.clearContents()
    board.setString_forType_(text, NSPasteboardTypeString)
    return previous, board.changeCount()


def restore_clipboard(previous, expected_count):
    board = NSPasteboard.generalPasteboard()
    if board.changeCount() != expected_count:
        return False
    board.clearContents()
    if previous is not None:
        board.setString_forType_(previous, NSPasteboardTypeString)
    return True


def post_paste_shortcut():
    down = CGEventCreateKeyboardEvent(None, PASTE_KEYCODE, True)
    CGEventSetFlags(down, kCGEventFlagMaskCommand)
    up = CGEventCreateKeyboardEvent(None, PASTE_KEYCODE, False)
    CGEventSetFlags(up, kCGEventFlagMaskCommand)
    CGEventPost(kCGHIDEventTap, down)
    time.sleep(0.02)
    CGEventPost(kCGHIDEventTap, up)


def paste_text(text, restore_delay=0.8):
    previous, change_count = copy_to_clipboard(text)
    post_paste_shortcut()
    threading.Timer(restore_delay, restore_clipboard, args=(previous, change_count)).start()
