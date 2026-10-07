"""Install the bundled J.A.R.V.I.S. wallpaper into Wallpaper Engine."""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from jarvisai.paths import bundle_root, user_data_dir
from jarvisai.steam import library_roots, steam_root

log = logging.getLogger("jarvisai.wallpaper")

CREATE_NO_WINDOW = 0x08000000
PROJECT_NAME = "jarvisai"
ASK_LINE = "I found Wallpaper Engine, sir. Shall I install the desktop interface?"


def remember_path() -> Path:
    return user_data_dir() / "wallpaper.json"


def load_choice() -> dict:
    path = remember_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def remember(**fields) -> None:
    data = load_choice()
    data.update(fields)
    remember_path().write_text(json.dumps(data, indent=2), encoding="utf-8")


def source_dir() -> Path:
    return bundle_root() / "wallpapers" / "jarvis"


def find_engine() -> Path | None:
    root = steam_root()
    if root is None:
        return None
    for library in library_roots(root):
        candidate = library / "steamapps" / "common" / "wallpaper_engine"
        if _engine_exe(candidate) is not None:
            return candidate
    return None


def installed_project(engine: Path | None = None) -> Path | None:
    engine = engine if engine is not None else find_engine()
    if engine is None:
        return None
    project = engine / "projects" / "myprojects" / PROJECT_NAME / "project.json"
    if project.exists():
        return project
    return None


def should_ask() -> bool:
    if find_engine() is None:
        return False
    choice = load_choice()
    if choice.get("declined"):
        return False
    if installed_project() is not None and choice.get("installed"):
        return False
    return True


def install_and_apply() -> str:
    engine = find_engine()
    if engine is None:
        return "I can't find Wallpaper Engine on this computer, sir."
    destination = engine / "projects" / "myprojects" / PROJECT_NAME
    try:
        copy_project(source_dir(), destination)
    except Exception:
        log.exception("Wallpaper copy failed")
        return "I couldn't install the wallpaper, sir."
    project = destination / "project.json"
    exe = _engine_exe(engine)
    if exe is None:
        return "I couldn't install the wallpaper, sir."
    try:
        _ensure_running(exe)
        _apply(exe, project)
    except Exception:
        log.exception("Wallpaper Engine did not accept the wallpaper")
        remember(installed=True)
        return "I copied the wallpaper, sir. Open Wallpaper Engine and choose J.A.R.V.I.S."
    remember(installed=True, declined=False)
    return "The desktop interface is online, sir."


def copy_project(source: Path, destination: Path) -> None:
    if not (source / "project.json").exists():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, dirs_exist_ok=True)


def _engine_exe(engine: Path) -> Path | None:
    for name in ("wallpaper64.exe", "wallpaper32.exe"):
        candidate = engine / name
        if candidate.exists():
            return candidate
    return None


def _running(exe: Path) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"IMAGENAME eq {exe.name}", "/NH"],
        capture_output=True,
        text=True,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    return exe.name.lower() in (result.stdout or "").lower()


def _ensure_running(exe: Path) -> None:
    if _running(exe):
        return
    subprocess.Popen([str(exe)])
    for _ in range(40):
        if _running(exe):
            return
        import time

        time.sleep(0.25)


def _apply(exe: Path, project: Path) -> None:
    import ctypes

    monitors = max(1, int(ctypes.windll.user32.GetSystemMetrics(80)))
    for index in range(monitors):
        subprocess.run(
            [
                str(exe),
                "-control",
                "openWallpaper",
                "-file",
                str(project),
                "-monitor",
                str(index),
            ],
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
