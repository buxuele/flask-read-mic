import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_env(path=ENV_PATH):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key.strip(), value)


def save_setting(key, value, path=ENV_PATH):
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    output = []
    found = False
    for line in lines:
        if line.strip().startswith(f"{key}="):
            output.append(f"{key}={value}")
            found = True
        else:
            output.append(line)
    if not found:
        output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.environ[key] = value


load_env()

ASR_URL = os.environ.get("ASR_URL", "").rstrip("/")
ASR_KEY = os.environ.get("ASR_KEY", "")
LANGUAGE = os.environ.get("LANGUAGE", "zh")
SAMPLE_RATE = 16000
MIN_SECONDS = 0.3
MAX_SECONDS = 280
AUDIO_LIMIT = 295
MIN_RMS = float(os.environ.get("MIN_RMS", "40") or 40)
CHUNK_THRESHOLD = int(os.environ.get("CHUNK_THRESHOLD", "500") or 500)
CHUNK_SILENCE = float(os.environ.get("CHUNK_SILENCE", "0.6") or 0.6)
LANGUAGES = [("zh", "中文"), ("en", "英文"), ("auto", "自动")]

_raw_device = os.environ.get("MIC_DEVICE", "").strip()
if not _raw_device:
    MIC_DEVICE = None
elif _raw_device.isdigit():
    MIC_DEVICE = int(_raw_device)
else:
    MIC_DEVICE = _raw_device

LOG_DIR = ROOT / "logs"
