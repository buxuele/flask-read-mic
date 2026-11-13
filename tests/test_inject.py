"""验证注入策略选择（不真的敲键盘，只验证分支）"""
import sys
import types

sys.path.insert(0, 'src')
import desktop_agent as da

calls = []


def fake_typewrite(text, interval=0.0):
    calls.append(('typewrite', text))


def fake_hotkey(*keys):
    calls.append(('hotkey', keys))


def fake_press(key):
    calls.append(('press', key))


def fake_copy(text):
    calls.append(('clipboard', text))


def install_fakes():
    pyautogui = types.SimpleNamespace(
        typewrite=fake_typewrite,
        hotkey=fake_hotkey,
        press=fake_press,
        FAILSAFE=True,
    )
    pyperclip = types.SimpleNamespace(copy=fake_copy)
    sys.modules['pyautogui'] = pyautogui
    sys.modules['pyperclip'] = pyperclip


install_fakes()

cases = [
    ('普通窗口 + 英文', 'hello world', False),
    ('终端 + 英文', 'hello world', True),
    ('普通窗口 + 中文', '你好世界', False),
    ('终端 + 中文', '你好世界', True),
    ('终端 + 长英文(超阈值)', 'a' * 300, True),
    ('普通窗口 + 带换行', 'line1\nline2', False),
]

fails = []
for label, text, terminal in cases:
    calls.clear()
    da.inject_text(text, terminal=terminal)
    actions = [c[0] for c in calls]
    expected = 'typewrite' if (da._is_plain_ascii(text) and len(text) <= da.TYPEWRITE_MAX_CHARS) else 'clipboard+hotkey'
    ok = (actions[0] == 'typewrite') if expected == 'typewrite' else (actions[0] == 'clipboard')
    hotkey = next((c[1] for c in calls if c[0] == 'hotkey'), None)
    press = next((c[1] for c in calls if c[0] == 'press'), None)
    want_enter = (da.AUTO_ENTER_IN_TERMINAL if terminal else da.AUTO_ENTER_AFTER_TYPE)
    ok = ok and (press == 'enter') == want_enter
    if hotkey:
        want = da.TERMINAL_PASTE_HOTKEY if terminal else da.NORMAL_PASTE_HOTKEY
        ok = ok and hotkey == want
    print(('PASS  ' if ok else 'FAIL  ') + f'{label:24s} {actions} hotkey={hotkey} enter={press}', flush=True)
    if not ok:
        fails.append(label)

# 空文本不应有任何动作
calls.clear()
da.inject_text('', terminal=False)
ok = len(calls) == 0
print(('PASS  ' if ok else 'FAIL  ') + f'空文本无动作 {calls}', flush=True)
if not ok:
    fails.append('空文本')

print()
print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}')
sys.exit(1 if fails else 0)
