import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import asr


class FakeResponse:
    status_code = 200

    def json(self):
        return {"text": "重试成功"}


class RetryResponse:
    def __init__(self, code, text=""):
        self.status_code = code
        self.headers = {}
        self._text = text

    def json(self):
        return {"text": self._text}


class _FakeSession:
    def __init__(self, post):
        self.post = post


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


def test_give_up_after_three_failures():
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
    assert len(calls) == 3


def test_retry_on_rate_limit():
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return RetryResponse(429)
        return RetryResponse(200, "限流后成功")

    asr.session = lambda: _FakeSession(fake_post)
    text = asr.transcribe(b"wav", "zh")
    assert text == "限流后成功"
    assert len(calls) == 2


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_retry 全部通过")
