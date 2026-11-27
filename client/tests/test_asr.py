import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from asr import transcribe


def make_speech(text, folder):
    aiff = folder / "speech.aiff"
    wav = folder / "speech.wav"
    subprocess.run(["say", "-o", str(aiff), text], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", str(aiff), str(wav)], check=True)
    return wav.read_bytes()


def main():
    with tempfile.TemporaryDirectory() as folder:
        wav = make_speech("测试语音识别接口是否正常", Path(folder))
        text = transcribe(wav, "zh")
        print("识别结果:", text)
        assert "语音识别" in text or "接口" in text, text
    print("test_asr 通过")


if __name__ == "__main__":
    main()
