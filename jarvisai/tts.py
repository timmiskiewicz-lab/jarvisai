from __future__ import annotations

import asyncio
import hashlib
import logging
import threading
from pathlib import Path

import numpy as np
import requests

from jarvisai.config import Settings, load_settings
from jarvisai.paths import bundle_root, user_data_dir

log = logging.getLogger("jarvisai.tts")


class Speaker:
    def __init__(self) -> None:
        self.settings = load_settings()
        self._lock = threading.Lock()

    def reload(self) -> None:
        self.settings = load_settings()

    def play(self, text: str, on_amplitude) -> None:
        text = " ".join(text.split())
        if not text:
            return
        bundled = _clip_file(text, bundle_root() / "assets" / "voice")
        if bundled is not None:
            samples, rate = _decode_mp3(bundled.read_bytes())
        else:
            samples, rate = self._synthesize(text)
        with self._lock:
            _play(samples, rate, on_amplitude)

    def _synthesize(self, text: str) -> tuple[np.ndarray, int]:
        cached = _clip_file(text, user_data_dir() / "voice")
        if cached is not None and not self.settings.uses_elevenlabs:
            return _decode_mp3(cached.read_bytes())
        settings = self.settings
        if settings.uses_elevenlabs:
            try:
                audio = _elevenlabs(text, settings)
                return _decode_mp3(audio)
            except Exception:
                log.exception("ElevenLabs failed, using the backup voice")
        audio = _edge(text, settings)
        _store_clip(text, audio)
        return _decode_mp3(audio)


def _elevenlabs(text: str, settings: Settings) -> bytes:
    voice = settings.elevenlabs_voice_id
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    response = requests.post(
        url,
        headers={
            "xi-api-key": settings.elevenlabs_api_key.strip(),
            "accept": "audio/mpeg",
            "content-type": "application/json",
        },
        json={
            "text": text,
            "model_id": settings.elevenlabs_model,
            "voice_settings": {
                "stability": 0.55,
                "similarity_boost": 0.8,
                "style": 0.15,
                "use_speaker_boost": True,
            },
        },
        timeout=25,
    )
    response.raise_for_status()
    if not response.content or response.headers.get("content-type", "").startswith("application/json"):
        raise RuntimeError("ElevenLabs did not return audio")
    return response.content


def _edge(text: str, settings: Settings) -> bytes:
    import edge_tts

    async def run() -> bytes:
        communicate = edge_tts.Communicate(text, settings.edge_voice, rate="-6%", pitch="-8Hz")
        chunks = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.extend(chunk["data"])
        return bytes(chunks)

    audio = asyncio.run(run())
    if not audio:
        raise RuntimeError("Backup voice returned no audio")
    return audio


def clip_name(text: str) -> str:
    key = " ".join(text.split()).encode("utf-8")
    return hashlib.sha1(key).hexdigest()[:16] + ".mp3"


def _clip_file(text: str, folder: Path) -> Path | None:
    path = folder / clip_name(text)
    if path.exists() and path.stat().st_size > 0:
        return path
    return None


def _store_clip(text: str, audio: bytes) -> None:
    if not audio:
        return
    folder = user_data_dir() / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / clip_name(text)).write_bytes(audio)


def _decode_mp3(data: bytes) -> tuple[np.ndarray, int]:
    import miniaudio

    decoded = miniaudio.decode(data, nchannels=1, sample_rate=44100)
    samples = np.asarray(decoded.samples, dtype=np.float32)
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    if peak > 2:
        samples = samples / 32768.0
    return samples, int(decoded.sample_rate)


def _play(samples: np.ndarray, rate: int, on_amplitude) -> None:
    import sounddevice as sd

    cursor = 0
    total = int(samples.shape[0])

    def callback(outdata, frames, _time, _status) -> None:
        nonlocal cursor
        end = min(cursor + frames, total)
        chunk = samples[cursor:end]
        count = int(chunk.shape[0])
        outdata[:] = 0
        if count:
            outdata[:count, 0] = chunk
            loud = float(np.sqrt(np.mean(chunk * chunk)))
            on_amplitude(max(0.0, min(1.0, loud * 8.0)))
        cursor = end
        if end >= total:
            on_amplitude(0.0)
            raise sd.CallbackStop

    with sd.OutputStream(samplerate=rate, channels=1, dtype="float32", callback=callback):
        while cursor < total:
            sd.sleep(30)
