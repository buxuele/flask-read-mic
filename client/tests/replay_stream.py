import difflib
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
from asr import transcribe
from stream import Streamer

RATE = 16000


class File:
    def __init__(self, path):
        with wave.open(str(path)) as handle:
            self.data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="int16").reshape(-1, 1)
        self.total = len(self.data) / RATE
        self.now = 0.0

    def read_audio(self, since):
        start = int(max(since, 0) * RATE)
        end = int(self.now * RATE)
        return self.data[start:end], self.now


def main():
    path = Path(sys.argv[1])
    clip = File(path)
    out = []
    calls = []

    def asr(wav, ctx):
        import io
        import wave as w

        buffer = io.BytesIO()
        with w.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(RATE)
            handle.writeframes(wav.tobytes())
        calls.append(len(wav) / RATE)
        return transcribe(buffer.getvalue(), config.LANGUAGE, context=ctx)

    streamer = Streamer(clip.read_audio, asr, lambda text, elapsed: out.append(text))
    while clip.now < clip.total:
        clip.now = min(clip.now + 0.5, clip.total)
        streamer.tick()
    streamer.finalize()

    streamed = "".join(out)
    full = transcribe(path.read_bytes(), config.LANGUAGE)
    ratio = difflib.SequenceMatcher(None, streamed, full).ratio()
    print(f"文件 {path.name} 时长 {clip.total:.2f}s，请求 {len(calls)} 次")
    print(f"切片结果：{streamed}")
    print(f"整段结果：{full}")
    print(f"相似度 {ratio:.3f}，字数 切片 {len(streamed)} 整段 {len(full)}")


if __name__ == "__main__":
    main()
