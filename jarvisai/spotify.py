"""Play a song in the Spotify app, or in the browser when the app is missing."""

from __future__ import annotations

import logging
import os
import random
import re
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

import requests

from jarvisai.brain import SpotifyAsk

log = logging.getLogger("jarvisai.spotify")

CREATE_NO_WINDOW = 0x08000000
_SEARCH = "https://itunes.apple.com/search"


def choose_track(
    results: list[dict],
    artist: str,
    title: str | None,
    picker=random.choice,
) -> tuple[str, str] | None:
    songs = [
        (str(item.get("trackName") or "").strip(), str(item.get("artistName") or "").strip())
        for item in results
        if str(item.get("trackName") or "").strip() and str(item.get("artistName") or "").strip()
    ]
    if not songs:
        return None
    wanted = _norm(artist)
    exact = [pair for pair in songs if _same_artist(_norm(pair[1]), wanted)]
    pool = exact or songs
    if title:
        named = [pair for pair in pool if _norm(title) in _norm(pair[0]) or _norm(pair[0]) in _norm(title)]
        return (named or pool)[0]
    return picker(pool)


def find_song(ask: SpotifyAsk) -> tuple[str, str] | None:
    params = {"term": ask.artist if ask.title is None else f"{ask.title} {ask.artist}", "entity": "song", "limit": 25}
    if ask.title is None:
        params["attribute"] = "artistTerm"
    try:
        response = requests.get(_SEARCH, params=params, timeout=8)
        response.raise_for_status()
        payload = response.json()
    except (OSError, ValueError, requests.RequestException):
        log.warning("Song lookup failed")
        return None
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return None
    return choose_track(results, ask.artist, ask.title)


def spotify_id_from_relations(recordings: list[dict]) -> str | None:
    for recording in recordings:
        relations = recording.get("relations") if isinstance(recording, dict) else None
        if not isinstance(relations, list):
            continue
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            resource = str(relation.get("url", {}).get("resource") or "")
            match = re.search(r"open\.spotify\.com/track/([A-Za-z0-9]+)", resource)
            if match:
                return match.group(1)
    return None


def lookup_track_id(title: str, artist: str) -> str | None:
    """Turn a song name into a Spotify track id, using public catalog pages."""
    try:
        found = requests.get(
            "https://api.deezer.com/search",
            params={"q": f"{title} {artist}"},
            timeout=8,
        )
        found.raise_for_status()
        hits = found.json().get("data")
        if not isinstance(hits, list):
            return None
        chosen = _deezer_hit(hits, title, artist)
        if chosen is None:
            return None
        track = requests.get(f"https://api.deezer.com/track/{chosen}", timeout=8)
        track.raise_for_status()
        isrc = str(track.json().get("isrc") or "").strip()
        if not isrc:
            return None
        relations = requests.get(
            f"https://musicbrainz.org/ws/2/isrc/{isrc}",
            params={"inc": "url-rels", "fmt": "json"},
            headers={
                "User-Agent": "JarvisAI/1.0 (https://github.com/timmiskiewicz-lab/jarvisai)",
                "Accept": "application/json",
            },
            timeout=8,
        )
        relations.raise_for_status()
        recordings = relations.json().get("recordings")
    except (OSError, ValueError, requests.RequestException):
        log.warning("Spotify track lookup failed")
        return None
    if not isinstance(recordings, list):
        return None
    return spotify_id_from_relations(recordings)


def open_spotify(title: str, artist: str) -> None:
    track_id = lookup_track_id(title, artist)
    if track_id:
        _open_target(f"spotify:track:{track_id}", f"https://open.spotify.com/track/{track_id}")
        return
    query = f"{title} {artist}".strip()
    _open_target(f"spotify:search:{query}", "https://open.spotify.com/search/" + quote(query))


def _deezer_hit(hits: list, title: str, artist: str) -> int | None:
    wanted = _norm(artist)
    named = _norm(title)
    fallback = None
    for hit in hits:
        if not isinstance(hit, dict) or not hit.get("id"):
            continue
        who = _norm(str(hit.get("artist", {}).get("name") or ""))
        song = _norm(str(hit.get("title") or ""))
        if fallback is None:
            fallback = int(hit["id"])
        if _same_artist(who, wanted) and (named in song or song in named):
            return int(hit["id"])
    return fallback


def _open_target(uri: str, page: str) -> None:
    if spotify_installed():
        try:
            exe = _windows_spotify() if sys.platform == "win32" else None
            if exe is not None:
                subprocess.Popen([str(exe), f"--uri={uri}"], creationflags=CREATE_NO_WINDOW)
            elif sys.platform == "win32":
                os.startfile(uri)  # noqa: S606 - the registered Spotify handler
            else:
                subprocess.Popen(["xdg-open", uri])
            return
        except OSError:
            log.exception("Spotify app did not accept the song")
    webbrowser.open(page)


def spotify_installed() -> bool:
    if sys.platform == "win32":
        return _windows_spotify() is not None or _protocol_registered()
    if sys.platform == "darwin":
        return Path("/Applications/Spotify.app").exists()
    return any(
        path.exists()
        for path in (
            Path("/usr/bin/spotify"),
            Path.home() / ".local" / "share" / "flatpak" / "exports" / "bin" / "com.spotify.Client",
        )
    )


def _windows_spotify() -> Path | None:
    roots = [os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", "")]
    candidates = [
        Path(roots[0]) / "Spotify" / "Spotify.exe" if roots[0] else None,
        Path(roots[1]) / "Microsoft" / "WindowsApps" / "Spotify.exe" if roots[1] else None,
    ]
    for candidate in candidates:
        if candidate is not None and candidate.exists():
            return candidate
    return None


def _protocol_registered() -> bool:
    if sys.platform != "win32":
        return False
    import winreg

    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_CLASSES_ROOT):
        try:
            winreg.OpenKey(hive, r"Software\Classes\spotify" if hive == winreg.HKEY_CURRENT_USER else "spotify")
            return True
        except OSError:
            continue
    return False


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _same_artist(found: str, wanted: str) -> bool:
    return bool(wanted) and (found == wanted or found.startswith(wanted + " "))
