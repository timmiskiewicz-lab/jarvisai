"""Record the built-in Jarvis lines so the app can speak without an API key."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jarvisai.brain import GREETINGS, profile_prompt  # noqa: E402
from jarvisai.steam import installed_games, steam_profiles, steam_root  # noqa: E402
from jarvisai.tts import clip_name  # noqa: E402

VOICE = "en-GB-RyanNeural"
OUT = ROOT / "assets" / "voice"

FIXED = list(GREETINGS) + [
    "Standing by, sir.",
    "Very well, sir.",
    "I can launch Steam games for now, sir. Try launch Gothic 1.",
    "I can't find Steam on this computer, sir.",
    "I couldn't find that game, sir. Say the name again.",
    "I couldn't find that game in your Steam library, sir.",
    "I lost track of that game, sir.",
    "Say first, second, or the profile name, sir.",
    "I can't reach speech recognition right now, sir.",
    "Steam didn't close, so I couldn't switch profiles, sir.",
    "I found Wallpaper Engine, sir. Shall I install the desktop interface?",
    "Installing the desktop interface, sir.",
    "The desktop interface is online, sir.",
    "Say yes or no, sir.",
    "I can't find Wallpaper Engine on this computer, sir.",
    "I couldn't install the wallpaper, sir.",
    "Gemini is offline, sir. I'll follow the direct commands.",
]


def collect() -> list[str]:
    lines = list(FIXED)
    root = steam_root()
    if root is None:
        return _unique(lines)
    games = installed_games(root)
    profiles = steam_profiles(root)
    if len(profiles) > 1:
        lines.append(profile_prompt(profiles))
    for game in games:
        lines.append(f"Launching {game.name}, sir.")
        for profile in profiles:
            persona = profile.persona_name or profile.account_name or "that profile"
            lines.append(f"Launching {game.name} on {persona}, sir.")
            lines.append(f"Switching to {persona} and launching {game.name}, sir.")
            if not profile.remember_password:
                lines.append(
                    f"Switching to {persona} and launching {game.name}, sir. Steam may ask you to sign in."
                )
    return _unique(lines)


def _unique(lines: list[str]) -> list[str]:
    seen: list[str] = []
    for line in lines:
        text = " ".join(line.split())
        if text and text not in seen:
            seen.append(text)
    return seen


async def render(lines: list[str]) -> None:
    import edge_tts

    OUT.mkdir(parents=True, exist_ok=True)
    pending = [line for line in lines if not (OUT / clip_name(line)).exists()]
    print(f"Voice clips: {len(lines) - len(pending)} ready, {len(pending)} to record")
    sem = asyncio.Semaphore(4)

    async def one(line: str) -> None:
        async with sem:
            communicate = edge_tts.Communicate(line, VOICE, rate="-6%", pitch="-8Hz")
            chunks = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    chunks.extend(chunk["data"])
            if not chunks:
                raise RuntimeError(f"No audio for: {line}")
            (OUT / clip_name(line)).write_bytes(chunks)

    await asyncio.gather(*(one(line) for line in pending))


def main() -> None:
    lines = collect()
    asyncio.run(render(lines))
    print(f"Voice bank: {OUT} ({len(list(OUT.glob('*.mp3')))} files)")


if __name__ == "__main__":
    main()
