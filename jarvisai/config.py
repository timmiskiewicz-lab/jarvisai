from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from jarvisai.paths import config_path

# Daniel is ElevenLabs' premade British male voice. Among the voices that
# work with any API key, it is the closest match to J.A.R.V.I.S.
DANIEL_VOICE_ID = "onwK4e9ZLuTAKqWW03F9"


@dataclass
class Settings:
    elevenlabs_api_key: str = ""
    elevenlabs_voice_id: str = DANIEL_VOICE_ID
    elevenlabs_model: str = "eleven_turbo_v2_5"
    edge_voice: str = "en-GB-RyanNeural"
    wake_threshold: float = 0.5

    @property
    def uses_elevenlabs(self) -> bool:
        return bool(self.elevenlabs_api_key.strip())


def load_settings() -> Settings:
    path = config_path()
    if not path.exists():
        settings = Settings()
        save_settings(settings)
        return settings
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    settings = Settings()
    for field in asdict(settings):
        if field in raw and raw[field] is not None:
            setattr(settings, field, raw[field])
    settings.wake_threshold = float(settings.wake_threshold)
    return settings


def save_settings(settings: Settings) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
