import json
import time
from pathlib import Path


class Store:
    def __init__(self, root):
        self.root = Path(root)

    def start(self, wav_bytes, seconds, rms, chunks):
        folder = self.root / time.strftime("%Y%m%d")
        folder.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%H%M%S")
        base = folder / stamp
        index = 2
        while base.with_suffix(".wav").exists():
            base = folder / f"{stamp}_{index}"
            index += 1

        base.with_suffix(".wav").write_bytes(wav_bytes)
        meta = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "seconds": round(seconds, 2),
            "rms": round(rms, 1),
            "chunks": [
                {"seconds": round(item["seconds"], 2), "rms": round(item["rms"], 1), "text": ""}
                for item in chunks
            ],
        }
        base.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return base

    def set_verify(self, base, text, elapsed, matched):
        path = base.with_suffix(".json")
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        meta["verify"] = {
            "text": text,
            "elapsed": round(elapsed, 2),
            "matched": matched,
        }
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def set_text(self, base, index, text, elapsed):
        path = base.with_suffix(".json")
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if index < len(meta["chunks"]):
            meta["chunks"][index]["text"] = text
            meta["chunks"][index]["elapsed"] = round(elapsed, 2)
            path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
