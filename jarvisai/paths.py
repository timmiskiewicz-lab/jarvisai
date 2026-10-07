from __future__ import annotations

import os
import sys
from pathlib import Path


APP_DIR_NAME = "JarvisAI"


def user_data_dir() -> Path:
    root = os.environ.get("APPDATA") or str(Path.home())
    path = Path(root) / APP_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return user_data_dir() / "config.json"


def log_path() -> Path:
    return user_data_dir() / "jarvis.log"


def bundle_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent.parent


def hud_dir() -> Path:
    if getattr(sys, "frozen", False):
        return bundle_root() / "jarvisai" / "hud"
    return Path(__file__).resolve().parent / "hud"


def install_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return bundle_root()
