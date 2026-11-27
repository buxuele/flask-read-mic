import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recorder import Segmenter

RATE = 16000
BLOCK = 1024


def blocks(amplitude, seconds):
    total = int(seconds * RATE)
    samples = (np.sin(np.linspace(0, 2 * np.pi * 440, total)) * amplitude).astype("int16")
    data = samples.reshape(-1, 1)
    return [data[i:i + BLOCK] for i in range(0, len(data), BLOCK)]


def feed(segmenter, stream):
    out = []
    for block in stream:
        out.extend(segmenter.feed(block))
    return out


def test_cut_after_silence():
    segmenter = Segmenter(rate=RATE)
    stream = blocks(0, 1.0) + blocks(3000, 2.0) + blocks(0, 1.0)
    chunks = feed(segmenter, stream)
    assert len(chunks) == 1, len(chunks)
    seconds = len(chunks[0]) / RATE
    assert 2.0 <= seconds <= 2.4, seconds
    assert segmenter.flush() is None


def test_no_split_on_short_pause():
    segmenter = Segmenter(rate=RATE)
    stream = blocks(3000, 1.0) + blocks(0, 0.4) + blocks(3000, 1.0)
    chunks = feed(segmenter, stream)
    assert chunks == []
    final = segmenter.flush()
    assert final is not None
    assert len(final) / RATE > 2.3


def test_max_chunk_splits():
    segmenter = Segmenter(rate=RATE, max_chunk=3.0, min_chunk=1.0)
    chunks = feed(segmenter, blocks(3000, 7.5))
    assert len(chunks) == 1
    first = len(chunks[0]) / RATE
    assert 5.0 <= first <= 6.1, first
    rest = segmenter.flush()
    assert rest is not None and len(rest) / RATE > 1.0


def test_cut_prefers_pause():
    segmenter = Segmenter(rate=RATE, max_chunk=6.0, min_chunk=1.0)
    stream = blocks(3000, 5.0) + blocks(0, 0.3) + blocks(3000, 5.0)
    chunks = []
    for block in stream:
        chunks.extend(segmenter.feed(block))
    assert chunks, "应该在 6 秒上限前切出一段"
    first = len(chunks[0]) / RATE
    assert 5.0 <= first <= 5.6, first


def test_silence_only():
    segmenter = Segmenter(rate=RATE)
    chunks = feed(segmenter, blocks(0, 2.0))
    assert chunks == []
    assert segmenter.flush() is None


def test_leading_silence_ignored():
    segmenter = Segmenter(rate=RATE)
    chunks = feed(segmenter, blocks(0, 3.0))
    assert chunks == []
    assert segmenter.length() == 0


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_segmenter 全部通过")
