import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stream import Streamer, common_prefix

RATE = 16000
TRUTH = "今天下午三点开会讨论新能源汽车销量数据"


class Clock:
    def __init__(self, total):
        self.now = 0.0
        self.total = total

    def read_audio(self, since):
        samples = max(0, int((self.now - since) * RATE))
        return np.zeros((samples, 1), dtype="int16"), self.now

    def asr(self, audio, context):
        progress = min(1.0, self.now / self.total)
        count = int(len(TRUTH) * progress)
        return TRUTH[:count]


def test_common_prefix():
    assert common_prefix("今天下午", "今天上午") == "今天"
    assert common_prefix("abc", "abc") == "abc"
    assert common_prefix("", "abc") == ""


def run_stream(total=4.0, step=0.5):
    clock = Clock(total)
    out = []
    streamer = Streamer(
        read_audio=clock.read_audio,
        asr=clock.asr,
        deliver=lambda text, elapsed: out.append(text),
        step=step,
        window=6.0,
        min_audio=1.0,
        holdback=4,
    )
    while clock.now < total:
        clock.now += step
        streamer.tick()
    streamer.finalize()
    return "".join(out)


def test_no_duplicate_no_gap():
    result = run_stream()
    assert result == TRUTH, result
    assert len(result) == len(TRUTH)


def test_holdback_delays_commit():
    clock = Clock(4.0)
    out = []
    streamer = Streamer(clock.read_audio, clock.asr, lambda t, e: out.append(t), min_audio=1.0, holdback=6)
    clock.now = 1.5
    streamer.tick()
    assert out == [], out
    clock.now = 2.0
    streamer.tick()
    assert out and len("".join(out)) < len(TRUTH) * 0.5


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_stream_mode 全部通过")
