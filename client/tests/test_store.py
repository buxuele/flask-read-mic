import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from store import Store

ROOT = Path(tempfile.mkdtemp())


def test_save_and_update():
    store = Store(ROOT)
    chunks = [{"seconds": 1.5, "rms": 320.0}, {"seconds": 2.0, "rms": 410.0}]
    base = store.start(b"RIFF-fake", 3.5, 380.0, chunks)
    assert base.with_suffix(".wav").read_bytes() == b"RIFF-fake"
    meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["seconds"] == 3.5
    assert len(meta["chunks"]) == 2

    store.set_text(base, 1, "第二句", 1.2)
    meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["chunks"][1]["text"] == "第二句"
    assert meta["chunks"][1]["elapsed"] == 1.2
    assert meta["chunks"][0]["text"] == ""

    store.set_verify(base, "整段复核", 1.1, False)
    meta = json.loads(base.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["verify"]["text"] == "整段复核"
    assert meta["verify"]["matched"] is False


if __name__ == "__main__":
    try:
        test_save_and_update()
        print("test_store 通过")
    finally:
        shutil.rmtree(ROOT, ignore_errors=True)
