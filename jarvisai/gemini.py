"""Turn a messy transcript into a Jarvis command. The key stays in the environment."""

from __future__ import annotations

import json
import logging
import os
import re
import winreg

import requests

from jarvisai.brain import Catalog, _percent_token

log = logging.getLogger("jarvisai.gemini")

_ENV_NAME = "GEMINI_API_KEY"
_MODELS = ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash")
_INTENTS = {
    "wake",
    "launch",
    "install",
    "choose",
    "cancel",
    "wallpaper_yes",
    "wallpaper_no",
    "spotify",
    "volume_up",
    "unknown",
}


def api_key() -> str:
    value = os.environ.get(_ENV_NAME, "").strip()
    if value:
        return value
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            stored, _kind = winreg.QueryValueEx(key, _ENV_NAME)
    except OSError:
        return ""
    value = str(stored or "").strip()
    if value:
        os.environ[_ENV_NAME] = value
    return value


def store_api_key(value: str) -> None:
    """Save the Gemini key in the current user's environment. It never goes into the app folder."""
    key = (value or "").strip()
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as reg:
        if key:
            winreg.SetValueEx(reg, _ENV_NAME, 0, winreg.REG_SZ, key)
        else:
            try:
                winreg.DeleteValue(reg, _ENV_NAME)
            except OSError:
                pass
    if key:
        os.environ[_ENV_NAME] = key
    else:
        os.environ.pop(_ENV_NAME, None)
    _broadcast_environment()


def _broadcast_environment() -> None:
    import ctypes

    result = ctypes.c_ulong()
    ctypes.windll.user32.SendMessageTimeoutW(
        0xFFFF,
        0x001A,
        0,
        "Environment",
        0x0002,
        500,
        ctypes.byref(result),
    )


def parse_intent(raw: str) -> dict:
    text = raw.strip()
    fenced = re.search(r"\{.*\}", text, re.DOTALL)
    if fenced:
        text = fenced.group(0)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Gemini reply was not an object")
    kind = str(data.get("intent") or "unknown").strip().lower()
    if kind not in _INTENTS:
        kind = "unknown"
    flag = data.get("random")
    if isinstance(flag, str):
        random_song = flag.strip().lower() in {"1", "true", "yes"}
    else:
        random_song = bool(flag)
    return {
        "intent": kind,
        "game": str(data.get("game") or "").strip(),
        "choice": str(data.get("choice") or "").strip(),
        "song": str(data.get("song") or "").strip(),
        "artist": str(data.get("artist") or "").strip(),
        "random": random_song,
        "amount": _percent_token(str(data.get("amount") or "")),
    }


def interpret(options: list[str], catalog: Catalog, phase: str) -> dict | None:
    heard = [line.strip() for line in options if line and line.strip()]
    if not heard:
        return None
    key = api_key()
    if not key:
        return None
    prompt = _prompt(heard, catalog, phase)
    try:
        raw = _generate(prompt, key)
        intent = parse_intent(raw)
    except Exception as error:
        log.warning("Gemini could not interpret the phrase: %s", _redact(error, key))
        return None
    log.info("Gemini intent: %s", intent["intent"])
    return intent


def _prompt(heard: list[str], catalog: Catalog, phase: str) -> str:
    games = "\n".join(f"- {game.name}" for game in catalog.games[:80]) or "- (none)"
    library = "\n".join(f"- {game.name}" for game in (catalog.library or [])[:80]) or "- (none)"
    profiles = []
    for index, profile in enumerate(catalog.profiles[:8]):
        label = profile.persona_name or "profile"
        profiles.append(f"{index + 1}. {label}")
    profile_text = "\n".join(profiles) or "- (none)"
    alternatives = "\n".join(f"- {line}" for line in heard[:8])
    return (
        "You understand short spoken commands for a desktop assistant called Jarvis. "
        "The speaker usually talks in Polish, sometimes English, and speech recognition is often wrong. "
        "odpal, uruchom, włącz and otwórz mean launch a Steam game. "
        "play or zagraj followed by a song and by/od/zespołu means Spotify, not a game. "
        "play random song by an artist means Spotify with random true. "
        "zainstaluj, instaluj, pobierz and ściągnij mean install. "
        "jeden dwa trzy mean 1 2 3.\n"
        f"Conversation phase: {phase}\n"
        f"Installed Steam games:\n{games}\n"
        f"Owned but not installed:\n{library}\n"
        f"Steam profiles, in order:\n{profile_text}\n"
        f"What the microphone heard:\n{alternatives}\n"
        "Reply with one JSON object and nothing else. Fields:\n"
        'intent: "wake", "launch", "install", "choose", "cancel", "wallpaper_yes", "wallpaper_no", "spotify", "volume_up", or "unknown".\n'
        "game: exact game name copied from one of the lists, or empty.\n"
        "choice: first, second, third, or a profile name from the list, or empty.\n"
        "song: the song title for Spotify, or empty when random is true.\n"
        "artist: the artist or band for Spotify, or empty.\n"
        "random: true when they want any song by that artist, otherwise false.\n"
        "amount: percent to raise the volume, such as 20 for turn this up by 20 percent, or empty.\n"
        "Use wake when they only said the wake phrase. "
        "Use launch when they want an installed game opened. "
        "Use spotify when they want a song, including play something by someone, or a random song by an artist. "
        "Use volume_up when they want the computer louder, such as turn this up, turn this up by 20 percent, louder, or głośniej. "
        "Use install when they want a game downloaded, or when the game is only in the owned list. "
        "Never invent a game that is not in the lists. "
        "Use choose when they are picking from a list already offered. "
        "Use wallpaper_yes or wallpaper_no only for the desktop wallpaper question. "
        "Use cancel when they want to stop. Otherwise unknown."
    )


def _generate(prompt: str, key: str) -> str:
    last_error = "Gemini did not answer"
    for model in _MODELS:
        response = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            headers={"x-goog-api-key": key, "content-type": "application/json"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            },
            timeout=8,
        )
        if response.status_code in {401, 403}:
            raise RuntimeError(f"Gemini rejected the API key ({response.status_code})")
        if response.status_code == 400:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "content-type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0}},
                timeout=8,
            )
        if response.status_code in {401, 403}:
            raise RuntimeError(f"Gemini rejected the API key ({response.status_code})")
        if response.status_code in {404, 429, 503}:
            last_error = f"{model} returned {response.status_code}"
            continue
        if response.status_code >= 400:
            raise RuntimeError(f"Gemini {model} returned {response.status_code}")
        payload = response.json()
        parts = payload["candidates"][0]["content"]["parts"]
        text = "".join(str(part.get("text", "")) for part in parts).strip()
        if text:
            return text
        last_error = f"{model} returned an empty reply"
    raise RuntimeError(last_error)


def _redact(error: Exception, key: str) -> str:
    text = str(error)
    if key:
        text = text.replace(key, _ENV_NAME)
    return text
