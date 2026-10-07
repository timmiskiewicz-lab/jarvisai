from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "JarvisAI"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    root = Path(__file__).resolve().parents[1]
    python = Path(sys.executable).resolve()
    return f'cmd /c cd /d "{root}" && "{python}" -m jarvisai'


def ensure_autostart() -> None:
    """Register JarvisAI in the current user's startup list.

    The installed app does this itself. Running from source does not, so a
    development session cannot replace the installed startup entry.
    """
    if not getattr(sys, "frozen", False):
        return
    command = launch_command()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, command)
