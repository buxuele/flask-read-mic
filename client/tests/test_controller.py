import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from controller import Controller


class FakeRecorder:
    def __init__(self, stop_chunks=None, seconds=1.2, rms=500, fail=False):
        self.stop_chunks = stop_chunks if stop_chunks is not None else [(b"chunk", 1.2, 500)]
        self.seconds = seconds
        self.rms = rms
        self.fail = fail
        self.dropped = False
        self.pending_chunks = []

    def start(self):
        if self.fail:
            raise RuntimeError("设备忙")

    def take_chunks(self):
        chunks, self.pending_chunks = self.pending_chunks, []
        return chunks

    def stop(self):
        return self.stop_chunks, self.seconds, self.rms

    def drop(self):
        self.dropped = True


def build(recorder, asr=None):
    events = []
    controller = Controller(
        recorder=recorder,
        run_asr=asr or (lambda wav, ctx: "测试文本"),
        on_state=lambda state: events.append(("state", state)),
        on_text=lambda text, elapsed: events.append(("text", text)),
        on_error=lambda message: events.append(("error", message)),
        min_seconds=0.3,
        max_seconds=280,
        audio_limit=295,
        min_rms=40,
    )
    return controller, events


def wait(controller):
    deadline = time.time() + 2
    while time.time() < deadline:
        with controller.lock:
            if controller.pending == 0:
                break
        time.sleep(0.01)


def texts(events):
    return [payload for kind, payload in events if kind == "text"]


def test_normal_hold():
    controller, events = build(FakeRecorder())
    controller.press()
    assert controller.state == "recording"
    controller.release()
    wait(controller)
    assert texts(events) == ["测试文本"]
    assert controller.state == "idle"


def test_two_chunks_in_order():
    recorder = FakeRecorder(stop_chunks=[(b"a", 1.5, 500), (b"b", 2.0, 500)], seconds=3.5)
    calls = []

    def asr(wav, ctx):
        calls.append(wav)
        return "第一句" if wav == b"a" else "第二句"

    controller, events = build(recorder, asr=asr)
    controller.press()
    controller.release()
    wait(controller)
    assert texts(events) == ["第一句", "第二句"]
    assert calls == [b"a", b"b"]


def test_push_from_recorder_callback():
    recorder = FakeRecorder(stop_chunks=[], seconds=2.0, rms=500)
    controller, events = build(recorder)
    controller.press()
    recorder.on_chunk((b"pushed", 1.5, 500))
    wait(controller)
    assert texts(events) == ["测试文本"]
    controller.release()
    wait(controller)


def test_out_of_order_results_keep_order():
    recorder = FakeRecorder(stop_chunks=[(b"a", 1.5, 500), (b"b", 1.5, 500)], seconds=3.0)

    def asr(wav, ctx):
        if wav == b"a":
            time.sleep(0.25)
            return "第一句"
        time.sleep(0.01)
        return "第二句"

    controller, events = build(recorder, asr=asr)
    controller.press()
    controller.release()
    wait(controller)
    assert texts(events) == ["第一句", "第二句"]


def test_poll_delivers_mid_recording():
    recorder = FakeRecorder(stop_chunks=[], seconds=3.0, rms=500)
    controller, events = build(recorder)
    controller.press()
    recorder.pending_chunks = [(b"early", 1.5, 500)]
    controller.poll()
    wait(controller)
    assert texts(events) == ["测试文本"]
    controller.release()
    wait(controller)


def test_context_grows():
    recorder = FakeRecorder(stop_chunks=[(b"a", 1.5, 500), (b"b", 1.5, 500)], seconds=3.0)
    seen = []

    def asr(wav, ctx):
        seen.append(ctx)
        return "第一句" if wav == b"a" else "第二句"

    controller, events = build(recorder, asr=asr)
    controller.press()
    controller.release()
    wait(controller)
    assert seen[0] == ""
    assert "第一句" in seen[1]


def test_combo_ignored():
    controller, events = build(FakeRecorder())
    controller.press(combo=True)
    assert controller.state == "idle"
    controller.release()
    assert texts(events) == []


def test_short_press_discarded():
    controller, events = build(FakeRecorder(seconds=0.1))
    controller.press()
    controller.release()
    wait(controller)
    assert texts(events) == []
    assert not any(kind == "error" for kind, _ in events)


def test_silence_discarded():
    controller, events = build(FakeRecorder(stop_chunks=[], seconds=1.2, rms=5))
    controller.press()
    controller.release()
    wait(controller)
    assert ("error", "没有检测到声音") in events


def test_too_long_rejected():
    controller, events = build(FakeRecorder(seconds=400))
    controller.press()
    controller.release()
    wait(controller)
    assert any(kind == "error" and "295" in message for kind, message in events)
    assert texts(events) == []


def test_asr_failure_reports():
    def broken(wav, ctx):
        raise RuntimeError("识别失败 500")

    controller, events = build(FakeRecorder(), asr=broken)
    controller.press()
    controller.release()
    wait(controller)
    assert ("error", "识别失败 500") in events
    assert controller.state == "idle"


def test_mic_failure_blocks():
    controller, events = build(FakeRecorder(fail=True))
    controller.press()
    assert controller.state == "idle"
    assert any("麦克风不可用" in message for kind, message in events)
    controller.release()
    assert texts(events) == []


def test_cancel_skips_queued():
    recorder = FakeRecorder(stop_chunks=[(b"a", 1.5, 500)], seconds=1.5)
    started = []

    def slow_asr(wav, ctx):
        started.append(wav)
        time.sleep(0.2)
        return "不应出现"

    controller, events = build(recorder, asr=slow_asr)
    controller.press()
    recorder.pending_chunks = [(b"early", 1.5, 500)]
    controller.poll()
    time.sleep(0.05)
    controller.cancel()
    wait(controller)
    time.sleep(0.3)
    assert texts(events) == []


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_controller 全部通过")
