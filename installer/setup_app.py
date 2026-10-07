"""Single-file installer. The build embeds payload.zip next to this script."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import winreg
import zipfile
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
CREATE_NO_WINDOW = 0x08000000


def message(text: str, flags: int = 0x40) -> int:
    return ctypes.windll.user32.MessageBoxW(0, text, "JarvisAI Setup", flags)


def bundled_zip() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "payload.zip"


def create_shortcuts(dest: Path) -> None:
    programs = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    powershell = Path(os.environ["SystemRoot"]) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    script = dest / "_shortcuts.ps1"
    script.write_text(
        "\n".join(
            [
                "$shell = New-Object -ComObject WScript.Shell",
                f"$app = $shell.CreateShortcut('{programs / 'JarvisAI.lnk'}')",
                f"$app.TargetPath = '{dest / 'JarvisAI.exe'}'",
                f"$app.WorkingDirectory = '{dest}'",
                "$app.Description = 'JarvisAI'",
                "$app.Save()",
                f"$remove = $shell.CreateShortcut('{programs / 'Uninstall JarvisAI.lnk'}')",
                f"$remove.TargetPath = '{powershell}'",
                f"$remove.Arguments = '-NoProfile -ExecutionPolicy Bypass -File \"{dest / 'uninstall.ps1'}\"'",
                f"$remove.WorkingDirectory = '{dest}'",
                "$remove.Description = 'Uninstall JarvisAI'",
                "$remove.Save()",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        check=False,
        creationflags=CREATE_NO_WINDOW,
    )
    script.unlink(missing_ok=True)


def main() -> None:
    answer = message(
        "Install JarvisAI?\n\nIt will start with Windows and listen for Hey Jarvis.",
        0x24,
    )
    if answer != 6:
        return

    archive = bundled_zip()
    if not archive.exists():
        message(f"The installer is missing its payload.\n\n{archive}", 0x10)
        return

    dest = Path(os.environ["LOCALAPPDATA"]) / "JarvisAI"
    subprocess.run(
        ["taskkill", "/F", "/IM", "JarvisAI.exe"],
        capture_output=True,
        creationflags=CREATE_NO_WINDOW,
    )
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        bundle.extractall(dest)

    exe = dest / "JarvisAI.exe"
    if not exe.exists():
        message("JarvisAI.exe was not found after unpacking.", 0x10)
        return

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "JarvisAI", 0, winreg.REG_SZ, f'"{exe}"')
    create_shortcuts(dest)
    subprocess.Popen([str(exe)], cwd=str(dest))
    message("JarvisAI is ready. Say Hey Jarvis, then ask it to launch a Steam game.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message(f"Installation failed.\n\n{error}", 0x10)
        raise
