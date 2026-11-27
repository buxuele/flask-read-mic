import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config
from recorder import to_wav, trim_wav


def test_save_setting_updates_existing(tmp_path=None):
    path = Path("/tmp/mic_server_env_test")
    path.write_text("# 注释\nASR_KEY=old\nLANGUAGE=zh\n", encoding="utf-8")
    config.save_setting("LANGUAGE", "en", path=path)
    text = path.read_text(encoding="utf-8")
    assert "# 注释" in text
    assert "ASR_KEY=old" in text
    assert "LANGUAGE=en" in text
    assert text.count("LANGUAGE=") == 1
    path.unlink()


def test_save_setting_appends():
    path = Path("/tmp/mic_server_env_test2")
    path.write_text("ASR_KEY=old\n", encoding="utf-8")
    config.save_setting("MIC_DEVICE", "UGREEN", path=path)
    text = path.read_text(encoding="utf-8")
    assert "MIC_DEVICE=UGREEN" in text
    assert text.count("MIC_DEVICE=") == 1
    path.unlink()


def make_wav(segments, rate=16000):
    chunks = []
    for amplitude, seconds in segments:
        count = int(rate * seconds)
        wave = (np.sin(np.linspace(0, 2 * np.pi * 440, count)) * amplitude).astype("int16")
        chunks.append(wave.reshape(-1, 1))
    return to_wav(np.concatenate(chunks), rate)


def test_trim_removes_edges():
    wav = make_wav([(20, 1.0), (3000, 1.0), (20, 1.0)])
    trimmed = trim_wav(wav)
    assert len(trimmed) < len(wav)
    assert len(trimmed) > len(wav) * 0.3


def test_trim_keeps_all_loud():
    wav = make_wav([(3000, 1.5), (3000, 1.5)])
    assert trim_wav(wav) == wav


def test_trim_all_quiet():
    wav = make_wav([(20, 1.0)])
    assert trim_wav(wav) == wav


if __name__ == "__main__":
    for name, function in sorted(globals().items()):
        if name.startswith("test_") and callable(function):
            function()
            print(f"{name} 通过")
    print("test_config 全部通过")
