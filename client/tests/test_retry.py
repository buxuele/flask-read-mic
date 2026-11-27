import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import asr


class _FakeSession:
    def __init__(self, post):
        self.post = post


class FakeResponse:
    status_code = 200

    def json(self):
        return {"text": "重试成功"}


def test_retry_once_on_connection_error():
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise asr.requests.ConnectionError("断线")
        return FakeResponse()

    asr.session = lambda: _FakeSession(fake_post)
    text = asr.transcribe(b"wav", "zh")
    assert text == "重试成功"
    assert len(calls) == 2


def test_give_up_after_second_failure():
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        raise asr.requests.Timeout("超时")

    asr.session = lambda: _FakeSession(fake_post)
    try:
        asr.transcribe(b"wav", "zh")
    except asr.requests.Timeout:
        pass
    else:
        raise AssertionError("应该抛出超时")
    assert len(calls) == 2


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_retry 通过")
