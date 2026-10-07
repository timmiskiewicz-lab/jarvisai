from __future__ import annotations

import logging
import subprocess
import time
import winreg
from dataclasses import dataclass
from pathlib import Path

from jarvisai.vdf import parse_vdf

log = logging.getLogger("jarvisai.steam")

CREATE_NO_WINDOW = 0x08000000
STEAM_KEY = r"Software\Valve\Steam"


@dataclass(frozen=True)
class Game:
    appid: str
    name: str


@dataclass(frozen=True)
class Profile:
    account_name: str
    persona_name: str
    active: bool
    remember_password: bool


def steam_root() -> Path | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STEAM_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "SteamPath")
    except OSError:
        return None
    path = Path(str(value))
    if (path / "steam.exe").exists():
        return path
    return None


def steam_exe() -> Path | None:
    root = steam_root()
    if root is None:
        return None
    exe = root / "steam.exe"
    return exe if exe.exists() else None


def autologin_user() -> str:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STEAM_KEY) as key:
            value, _ = winreg.QueryValueEx(key, "AutoLoginUser")
    except OSError:
        return ""
    return str(value or "")


def set_autologin_user(account_name: str) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STEAM_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "AutoLoginUser", 0, winreg.REG_SZ, account_name)


def needs_account_switch(profile: Profile, current_user: str) -> bool:
    if not profile.account_name:
        return False
    return profile.account_name.lower() != (current_user or "").lower()


def _read_vdf(path: Path) -> dict:
    if not path.exists():
        return {}
    return parse_vdf(path.read_text(encoding="utf-8", errors="replace"))


def library_roots(root: Path) -> list[Path]:
    found: list[Path] = [root]
    data = _read_vdf(root / "steamapps" / "libraryfolders.vdf")
    folders = data.get("libraryfolders", {})
    if isinstance(folders, dict):
        for node in folders.values():
            if isinstance(node, dict) and node.get("path"):
                found.append(Path(str(node["path"])))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in found:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def installed_games(root: Path | None = None) -> list[Game]:
    root = root or steam_root()
    if root is None:
        return []
    games: dict[str, Game] = {}
    for library in library_roots(root):
        steamapps = library / "steamapps"
        if not steamapps.exists():
            continue
        for manifest in steamapps.glob("appmanifest_*.acf"):
            data = _read_vdf(manifest)
            state = data.get("AppState", data)
            if not isinstance(state, dict):
                continue
            appid = str(state.get("appid", "")).strip()
            name = str(state.get("name", "")).strip()
            if not appid or not name:
                continue
            games[appid] = Game(appid=appid, name=name)
    return sorted(games.values(), key=lambda game: game.name.lower())


def steam_profiles(root: Path | None = None) -> list[Profile]:
    root = root or steam_root()
    if root is None:
        return []
    data = _read_vdf(root / "config" / "loginusers.vdf")
    users = data.get("users", {})
    if not isinstance(users, dict):
        return []
    current = autologin_user().lower()
    profiles: list[Profile] = []
    for node in users.values():
        if not isinstance(node, dict):
            continue
        account = str(node.get("AccountName", "")).strip()
        persona = str(node.get("PersonaName", "")).strip() or account
        if not account and not persona:
            continue
        flagged = str(node.get("AutoLogin", node.get("MostRecent", "0"))) == "1"
        active = flagged or (current and account.lower() == current)
        remember = str(node.get("RememberPassword", "0")) == "1"
        profiles.append(
            Profile(
                account_name=account,
                persona_name=persona,
                active=active,
                remember_password=remember,
            )
        )
    profiles.sort(key=lambda profile: (not profile.active, profile.persona_name.lower()))
    return profiles


def steam_running() -> bool:
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
            creationflags=CREATE_NO_WINDOW,
            text=True,
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return "steam.exe" in output.lower()


def _wait_until_stopped(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not steam_running():
            return True
        time.sleep(0.4)
    return not steam_running()


def _wait_until_started(timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if steam_running():
            return True
        time.sleep(0.4)
    return steam_running()


def launch_game(game: Game, profile: Profile) -> str | None:
    """Launch a game. Returns an error sentence, or None when Steam accepted it."""
    exe = steam_exe()
    if exe is None:
        return "I can't find Steam on this computer, sir."

    current = autologin_user()
    switch = needs_account_switch(profile, current) and bool(profile.account_name)
    command = [str(exe), "-applaunch", str(game.appid)]

    if not switch:
        subprocess.Popen(command, creationflags=CREATE_NO_WINDOW)
        return None

    previous = current
    log.info("Switching Steam autologin for this launch")
    set_autologin_user(profile.account_name)
    try:
        if steam_running():
            subprocess.run(command[:1] + ["-shutdown"], creationflags=CREATE_NO_WINDOW, timeout=20)
            if not _wait_until_stopped(25):
                return "Steam didn't close, so I couldn't switch profiles, sir."
        subprocess.Popen(command, creationflags=CREATE_NO_WINDOW)
        # Steam reads AutoLoginUser while it is starting. Give it time before
        # putting the previous account back, so the next boot is unchanged.
        if _wait_until_started(20):
            time.sleep(8)
    finally:
        if previous:
            try:
                set_autologin_user(previous)
            except OSError:
                log.exception("Could not restore the previous Steam account")
    return None
