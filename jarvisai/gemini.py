"""Turn a messy transcript into a Jarvis command. The key stays in the environment."""

from __future__ import annotations

import json
import logging
import os
import re
import winreg

import requests

from jarvisai.brain import Catalog

log = logging.getLogger("jarvisai.gemini")

_ENV_NAME = "GEMINI_API_KEY"
_MODELS = ("gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.8-flash")
_INTENTS = {"wake", "launch", "choose", "cancel", "wallpaper_yes", "wallpaper_no", "unknown"}


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
    return {
        "intent": kind,
        "game": str(data.get("game") or "").strip(),
        "choice": str(data.get("choice") or "").strip(),
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
    profiles = []
    for index, profile in enumerate(catalog.profiles[:8]):
        label = profile.persona_name or "profile"
        profiles.append(f"{index + 1}. {label}")
    profile_text = "\n".join(profiles) or "- (none)"
    alternatives = "\n".join(f"- {line}" for line in heard[:8])
    return (
        "You understand short spoken commands for a desktop assistant called Jarvis. "
        "The speaker uses Polish and English, and speech recognition is often wrong. "
        "Choose the meaning that best matches an installed game.\n"
        f"Conversation phase: {phase}\n"
        f"Installed Steam games:\n{games}\n"
        f"Steam profiles, in order:\n{profile_text}\n"
        f"What the microphone heard:\n{alternatives}\n"
        "Reply with one JSON object and nothing else. Fields:\n"
        'intent: "wake", "launch", "choose", "cancel", "wallpaper_yes", "wallpaper_no", or "unknown".\n'
        "game: exact game name copied from the installed list, or empty.\n"
        "choice: first, second, third, or a profile name from the list, or empty.\n"
        "Use wake when they only said the wake phrase. "
        "Use launch when they want a game opened. Never invent a game that is not in the list. "
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
            timeout=20,
        )
        if response.status_code in {401, 403}:
            raise RuntimeError(f"Gemini rejected the API key ({response.status_code})")
        if response.status_code == 400:
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                headers={"x-goog-api-key": key, "content-type": "application/json"},
                json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0}},
                timeout=20,
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
