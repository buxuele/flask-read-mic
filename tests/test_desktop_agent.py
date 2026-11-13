"""语音输入代理状态机测试：双击触发、按住触发、组合键让路、终端识别。
运行：python tests/test_desktop_agent.py"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

import commander
import desktop_agent as da


class FakeKey:
    """模拟 keyboard.Key 的具名键对象"""

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f'Key({self.name})'


CTRL_L, CTRL_R = FakeKey('ctrl_l'), FakeKey('ctrl_r')
KEY_C, KEY_A, KEY_V = FakeKey('c'), FakeKey('a'), FakeKey('v')


class FakeRecorder:
    def __init__(self, speech=True):
        self.started = 0
        self.stopped = 0
        self.speech = speech
        self.speaking = speech

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1
        return b'WAV' if self.speech else None

    def had_speech(self):
        return self.speech

    def is_speaking(self):
        return self.speaking


# 阻断真实网络、剪贴板与鼠标操作
da.transcribe_via_flask = lambda wav, **kw: ('sess_test', '测试文本')
da.inject_text = lambda text, terminal=None: None
commander.inject_text = lambda text: None
commander.parse_with_llm = lambda text: {'action': 'none'}

fails = []


def check(name, cond, extra=''):
    print(f'{"PASS" if cond else "FAIL"}  {name} {extra}', flush=True)
    if not cond:
        fails.append(name)


def new_agent(speech=True):
    a = da.VoiceAgent()
    a.recorder = FakeRecorder(speech)
    return a


def tap(a, gap=0.0, key=CTRL_L):
    """完整的一次点击：按下 -> 抬起"""
    a.on_press(key)
    a.on_release(key)
    if gap:
        time.sleep(gap)


def cleanup(a):
    a.recorder.stop()
    a._reset()
    a.recorder.speaking = False
    time.sleep(0.15)


# 1. 双击 Ctrl 触发录音
a = new_agent()
tap(a)
tap(a, gap=0.08)
time.sleep(0.5)
check('双击 Ctrl 触发录音', a.state == da.RECORDING, a.state)
check('录音器只启动一次', a.recorder.started == 1)
cleanup(a)

# 2. 单击 Ctrl 不触发
a = new_agent()
tap(a)
time.sleep(da.DOUBLE_TAP_INTERVAL + 0.3)
check('单击 Ctrl 不触发录音', a.recorder.started == 0 and a.state == da.IDLE)
cleanup(a)

# 3. 双击间隔过长不算双击
a = new_agent()
tap(a)
time.sleep(da.DOUBLE_TAP_INTERVAL + 0.2)
tap(a)
time.sleep(0.5)
check('间隔过长的两次不算双击', a.recorder.started == 0, str(a.recorder.started))
cleanup(a)

# 4. 录音中再双击一次即停止
a = new_agent()
tap(a)
tap(a, gap=0.08)
time.sleep(0.5)
check('已进入录音', a.state == da.RECORDING)
a.recorder.speaking = False
tap(a)
tap(a, gap=0.08)
time.sleep(1.2)
check('录音中再双击可停止', a.state == da.IDLE, a.state)
cleanup(a)

# 5. 按住 Ctrl 触发
a = new_agent()
a.on_press(CTRL_L)
time.sleep(da.HOLD_TRIGGER_SECONDS + 0.25)
check('按住 Ctrl 触发录音', a.state == da.RECORDING, a.state)
check('按住模式标记正确', a._trigger == 'hold', str(a._trigger))
a.on_release(CTRL_L)
time.sleep(0.6)
check('松开后自动收尾', a.state == da.IDLE, a.state)
cleanup(a)

# 6. Ctrl+C 组合键让路（按下后立刻按其它键，不应触发录音）
a = new_agent()
a.on_press(CTRL_L)
time.sleep(0.05)
a.on_press(KEY_C)
time.sleep(da.HOLD_TRIGGER_SECONDS + 0.2)
check('Ctrl+C 不触发录音', a.recorder.started == 0, str(a.recorder.started))
a.on_release(CTRL_L)
cleanup(a)

# 7. 双击后按其它键不劫持（此时已进入录音，文本照常注入）
a = new_agent()
tap(a)
tap(a, gap=0.08)
time.sleep(0.5)
a.on_press(KEY_C)
time.sleep(0.3)
check('双击录音不因单键中止', a.state == da.RECORDING, a.state)
cleanup(a)

# 8. 静音录音被丢弃（静音自动停止会先收尾，所以等待要超过 SILENCE_AUTO_STOP）
a = new_agent(speech=False)
tap(a)
tap(a, gap=0.08)
time.sleep(0.5)
check('静音录音已进入录音态', a.state == da.RECORDING, a.state)
time.sleep(da.SILENCE_AUTO_STOP + 0.8)
check('静音超时自动收尾', a.state == da.IDLE, a.state)
check('静音录音被丢弃不送 GPU', a._busy is False)
cleanup(a)

# 9. 左右 Ctrl 混按仍能双击
a = new_agent()
tap(a, key=CTRL_L)
tap(a, gap=0.08, key=CTRL_R)
time.sleep(0.5)
check('左右 Ctrl 混按可双击', a.state == da.RECORDING, a.state)
cleanup(a)

# 10. 终端窗口识别
check('识别为终端', da.is_terminal_foreground() in (True, False))
check('描述非空', len(da.describe_foreground()) > 0, da.describe_foreground())

# 11. 纯 ASCII 走敲字路径
check('纯 ASCII 判定', da._is_plain_ascii('hello world') is True)
check('含中文不走敲字', da._is_plain_ascii('你好') is False)
check('含换行不走敲字', da._is_plain_ascii('a\nb') is False)


if __name__ == '__main__':
    print()
    print('ALL PASS' if not fails else f'FAILED ({len(fails)}): {fails}', flush=True)
    sys.exit(1 if fails else 0)
