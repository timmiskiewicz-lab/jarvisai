"""Download the local speech model used to understand game names."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "assets" / "stt" / "faster-whisper-base"
BASE = "https://huggingface.co/Systran/faster-whisper-base/resolve/main"
FILES = (
    "config.json",
    "tokenizer.json",
    "vocabulary.txt",
    "model.bin",
)


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = DEST / name
        if target.exists() and target.stat().st_size > 0:
            print(f"already have {name}")
            continue
        print(f"downloading {name}")
        subprocess.run(
            ["curl.exe", "-L", "--fail", "--retry", "3", "-o", str(target), f"{BASE}/{name}"],
            check=True,
        )
        if target.stat().st_size == 0:
            raise SystemExit(f"{name} is empty")
    print(f"Speech model: {DEST}")


if __name__ == "__main__":
    main()
