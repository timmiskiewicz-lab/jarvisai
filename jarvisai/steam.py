from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
import winreg
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from jarvisai.paths import user_data_dir
from jarvisai.vdf import parse_vdf

log = logging.getLogger("jarvisai.steam")

CREATE_NO_WINDOW = 0x08000000
STEAM_KEY = r"Software\Valve\Steam"


@dataclass(frozen=True)
class Game:
    appid: str
    name: str
    installed: bool = True


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


_names_lock = threading.Lock()
_names: dict[str, str] | None = None
_owned_cache: tuple[float, set[str]] | None = None


def finish_clock(samples: list[tuple[float, int, int]], now: datetime) -> str | None:
    """Estimate a local clock time from (timestamp, downloaded, total) samples."""
    if len(samples) < 2:
        return None
    started, downloaded_then, _total_then = samples[0]
    ended, downloaded, total = samples[-1]
    elapsed = ended - started
    gained = downloaded - downloaded_then
    if elapsed <= 0 or gained < 50_000 or total <= downloaded:
        return None
    remaining = total - downloaded
    finish = now + timedelta(seconds=remaining / (gained / elapsed))
    return finish.strftime("%H:%M")


def uninstalled_games(root: Path | None = None) -> list[Game]:
    root = root or steam_root()
    if root is None:
        return []
    installed = {game.appid for game in installed_games(root)}
    names = _library_names()
    games = [
        Game(appid, names[appid], False)
        for appid in sorted(_owned_appids(root))
        if appid not in installed and names.get(appid)
    ]
    games.sort(key=lambda game: game.name.lower())
    return games


def warm_library_names() -> None:
    root = steam_root()
    if root is None:
        return
    owned = _owned_appids(root)
    names = dict(_library_names())
    if owned and owned <= set(names):
        return
    try:
        import requests

        response = requests.get("https://api.steampowered.com/ISteamApps/GetAppList/v2/", timeout=40)
        response.raise_for_status()
        apps = response.json().get("applist", {}).get("apps", [])
    except Exception:
        log.warning("Could not refresh the Steam library names")
        return
    for app in apps:
        if not isinstance(app, dict):
            continue
        appid = str(app.get("appid", "")).strip()
        name = str(app.get("name", "")).strip()
        if appid in owned and name:
            names[appid] = name
    _store_names(names)
    log.info("Steam library names ready (%s)", len(names))


def search_uninstalled(query: str, root: Path | None = None) -> list[Game]:
    root = root or steam_root()
    if root is None or not query.strip():
        return []
    installed = {game.appid for game in installed_games(root)}
    owned = _owned_appids(root)
    try:
        import requests

        response = requests.get(
            "https://steamcommunity.com/actions/SearchApps/" + quote(query.strip()),
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        log.warning("Steam name search failed")
        return []
    found: list[Game] = []
    if not isinstance(payload, list):
        return []
    for item in payload:
        if not isinstance(item, dict):
            continue
        appid = str(item.get("appid", "")).strip()
        name = str(item.get("name", "")).strip()
        if appid in owned and appid not in installed and name:
            found.append(Game(appid, name, False))
    if found:
        names = dict(_library_names())
        for game in found:
            names[game.appid] = game.name
        _store_names(names)
    return found


def begin_install(game: Game) -> str | None:
    """Start a Steam install. Returns the local time it should finish, when known."""
    exe = steam_exe()
    if exe is None:
        return None
    subprocess.Popen([str(exe), f"steam://install/{game.appid}"], creationflags=CREATE_NO_WINDOW)
    samples: list[tuple[float, int, int]] = []
    deadline = time.time() + 8
    while time.time() < deadline and len(samples) < 3:
        progress = _download_progress(game.appid)
        if progress is not None:
            samples.append((time.time(), progress[0], progress[1]))
        time.sleep(1.4)
    return finish_clock(samples, datetime.now())


def _names_path() -> Path:
    return user_data_dir() / "library_names.json"


def _library_names() -> dict[str, str]:
    global _names
    with _names_lock:
        if _names is not None:
            return _names
        path = _names_path()
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                _names = {str(key): str(value) for key, value in loaded.items()} if isinstance(loaded, dict) else {}
            except (OSError, json.JSONDecodeError):
                _names = {}
        else:
            _names = {}
        return _names


def _store_names(names: dict[str, str]) -> None:
    global _names
    with _names_lock:
        _names = names
    try:
        _names_path().write_text(json.dumps(names), encoding="utf-8")
    except OSError:
        log.warning("Could not save Steam library names")


def _owned_appids(root: Path) -> set[str]:
    global _owned_cache
    now = time.time()
    if _owned_cache and now - _owned_cache[0] < 20:
        return _owned_cache[1]
    found: set[str] = set()
    cache = root / "appcache" / "librarycache"
    if cache.exists():
        for path in cache.iterdir():
            if path.name.isdigit():
                found.add(path.name)
    users = root / "userdata"
    if users.exists():
        for folder in users.iterdir():
            local = folder / "config" / "localconfig.vdf"
            if not local.exists():
                continue
            data = _read_vdf(local)
            apps = (
                data.get("UserLocalConfigStore", {})
                .get("Software", {})
                .get("Valve", {})
                .get("Steam", {})
                .get("apps", {})
            )
            if isinstance(apps, dict):
                found.update(key for key in apps if str(key).isdigit())
    _owned_cache = (now, found)
    return found


def _download_progress(appid: str) -> tuple[int, int] | None:
    root = steam_root()
    if root is None:
        return None
    for library in library_roots(root):
        manifest = library / "steamapps" / f"appmanifest_{appid}.acf"
        if not manifest.exists():
            continue
        data = _read_vdf(manifest)
        state = data.get("AppState", data)
        if not isinstance(state, dict):
            continue
        try:
            downloaded = int(state.get("BytesDownloaded") or 0)
            total = int(state.get("BytesToDownload") or 0)
        except (TypeError, ValueError):
            continue
        if total > 0:
            return downloaded, total
    return None
