import io
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from asr import transcribe
from recorder import Segmenter, to_wav

RATE = 16000
BLOCK = 1024


def speech(text):
    aiff = Path("/tmp") / "seg.aiff"
    wav = Path("/tmp") / "seg.wav"
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(wav)], check=True)
    with wave.open(str(wav)) as handle:
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype="int16")
    return data


def main():
    first = speech("第一句，明天上午十点开产品评审会。")
    second = speech("第二句，记得带上设计稿。")
    silence = np.zeros(RATE, dtype="int16")
    audio = np.concatenate([first, silence, second])

    segmenter = Segmenter(rate=RATE)
    chunks = []
    for start in range(0, len(audio), BLOCK):
        for chunk in segmenter.feed(audio[start:start + BLOCK].reshape(-1, 1)):
            chunks.append(chunk)
    tail = segmenter.flush()
    if tail is not None:
        chunks.append(tail)
    print("切出片段:", len(chunks), [round(len(c) / RATE, 2) for c in chunks])
    assert len(chunks) == 2, len(chunks)

    context = ""
    texts = []
    for chunk in chunks:
        text = transcribe(to_wav(chunk, RATE), "zh", context=context)
        print("识别:", text)
        assert text
        texts.append(text)
        context = (context + text)[-400:]
    assert "评审" in texts[0] or "十点" in texts[0]
    assert "设计" in texts[1] or "记得" in texts[1]
    print("test_stream 通过")


if __name__ == "__main__":
    main()
