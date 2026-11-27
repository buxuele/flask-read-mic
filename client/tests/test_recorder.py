import io
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from recorder import to_wav


def main():
    rate = 16000
    samples = (np.sin(np.linspace(0, 2 * np.pi * 440, rate)) * 3000).astype("int16").reshape(-1, 1)
    wav = to_wav(samples, rate)
    with wave.open(io.BytesIO(wav)) as handle:
        assert handle.getframerate() == rate
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2
        assert handle.getnframes() == rate
    print(f"wav 字节 {len(wav)}，帧数 {rate}，时长 1.00s")
    print("test_recorder 通过")


if __name__ == "__main__":
    main()
