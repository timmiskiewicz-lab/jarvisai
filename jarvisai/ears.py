from __future__ import annotations

import logging
import re
import shutil
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvisai.brain import Catalog, choose_transcript, command_score, is_wake_only

log = logging.getLogger("jarvisai.ears")

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms, the size openWakeWord expects


@dataclass
class Heard:
    text: str | None
    error: str | None = None


class Ears:
    """Local wake word, then one spoken command."""

    def __init__(self, state, settings_provider, on_wake, catalog_provider=None) -> None:
        self.state = state
        self.settings_provider = settings_provider
        self.on_wake = on_wake
        self.catalog_provider = catalog_provider
        self.running = True
        self._capture = False
        self._generation = 0
        self._result: Heard | None = None
        self._done = threading.Event()
        self._lock = threading.Lock()
        self._noise = 250.0
        self._hits = 0
        self._cooldown_until = 0.0
        self._was_busy = False
        self._thread = threading.Thread(target=self._run, name="jarvis-ears", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.running = False

    def capture(self, timeout: float = 8.0) -> Heard:
        with self._lock:
            self._generation += 1
            self._result = None
            self._done.clear()
            self._capture = True
        self.state.update(mode="listening", status="Listening", caption="", amplitude=0.0)
        finished = self._done.wait(timeout + 12)
        with self._lock:
            self._capture = False
            result = self._result
        if not finished or result is None:
            return Heard(None)
        return result

    def _finish(self, generation: int, heard: Heard) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._result = heard
            self._capture = False
            self._done.set()

    def _run(self) -> None:
        try:
            import sounddevice as sd
        except Exception:
            log.exception("Microphone library failed")
            self.state.update(status="Microphone unavailable")
            return

        model = _load_wake_model()
        threading.Thread(target=_load_whisper, name="jarvis-stt", daemon=True).start()
        while self.running:
            try:
                self._listen(sd, model)
            except Exception:
                log.exception("Microphone stream failed")
                self.state.update(status="Microphone unavailable")
                time.sleep(3)

    def _listen(self, sd, model) -> None:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME,
        ) as stream:
            self.state.update(status="Standing by")
            buffer: list[np.ndarray] = []
            preroll: deque[np.ndarray] = deque(maxlen=8)
            started = False
            silence_ms = 0
            started_at = 0.0
            generation = -1
            while self.running:
                frame, _overflow = stream.read(FRAME)
                samples = np.squeeze(frame).astype(np.int16)
                if samples.size != FRAME:
                    continue
                loud = _rms(samples)
                capturing = self._capture
                mode = self.state.snapshot()["mode"]

                if mode != "speaking":
                    level = max(0.0, min(1.0, loud / 3500.0))
                    if mode != "thinking":
                        self.state.update(amplitude=level)

                if capturing:
                    if generation != self._generation:
                        generation = self._generation
                        threshold = max(160.0, self._noise * 2.4)
                        buffer = list(preroll)
                        preroll.clear()
                        started = any(_rms(chunk) >= threshold for chunk in buffer)
                        silence_ms = 0
                        started_at = time.time()
                    threshold = max(160.0, self._noise * 2.4)
                    if loud >= threshold:
                        started = True
                        silence_ms = 0
                        buffer.append(samples.copy())
                    elif started:
                        buffer.append(samples.copy())
                        silence_ms += 80
                        if silence_ms >= 1280 or len(buffer) >= 100:
                            self._transcribe(buffer, generation)
                            buffer = []
                            started = False
                    elif time.time() - started_at > 8.0:
                        self._finish(generation, Heard(""))
                    continue

                generation = -1
                if mode == "speaking":
                    preroll.clear()
                else:
                    preroll.append(samples.copy())
                self._noise = self._noise * 0.98 + loud * 0.02
                if mode in {"speaking", "thinking", "listening"}:
                    self._hits = 0
                    self._was_busy = True
                    continue
                if self._was_busy and model is not None:
                    self._was_busy = False
                    self._cooldown_until = time.time() + 1.2
                    try:
                        model.reset()
                    except Exception:
                        log.debug("Wake model reset failed", exc_info=True)
                if model is None or time.time() < self._cooldown_until:
                    continue
                score = _wake_score(model, samples)
                threshold = float(self.settings_provider().wake_threshold)
                if score >= threshold:
                    self._hits += 1
                else:
                    self._hits = 0
                if self._hits >= 2:
                    self._hits = 0
                    self._cooldown_until = time.time() + 2.5
                    log.info("Wake word heard (%.2f)", score)
                    try:
                        model.reset()
                    except Exception:
                        log.debug("Wake model reset failed", exc_info=True)
                    self.on_wake()


    def _transcribe(self, frames: list[np.ndarray], generation: int) -> None:
        if not frames:
            self._finish(generation, Heard(""))
            return
        self.state.update(mode="thinking", status="Recognizing", amplitude=0.0)
        raw = np.concatenate(frames).tobytes()
        catalog = self._catalog()
        try:
            options = _google_options(raw)
            text = choose_transcript(options, catalog)
            weak = command_score(text, catalog) < 0.72 and not is_wake_only(text)
            if weak:
                names = [game.name for game in catalog.games]
                options.extend(_whisper_options(raw, names))
                text = choose_transcript(options, catalog)
            log.info("Heard: %s", text or "(silence)")
            if options:
                log.info("Alternatives: %s", " | ".join(options[:8]))
            self._finish(generation, Heard(text))
        except Exception as error:
            log.exception("Speech recognition failed")
            self._finish(generation, Heard(None, error=type(error).__name__))

    def _catalog(self) -> Catalog:
        if self.catalog_provider is None:
            return Catalog(False, [], [])
        try:
            return self.catalog_provider()
        except Exception:
            log.debug("Catalog unavailable during recognition", exc_info=True)
            return Catalog(False, [], [])


def _rms(samples: np.ndarray) -> float:
    values = samples.astype(np.float32)
    return float(np.sqrt(np.mean(values * values)))


def _wake_asset_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "assets" / "wake"
    return Path(__file__).resolve().parents[1] / "assets" / "wake"


def _stage_wake_models() -> None:
    import openwakeword.utils as utils

    destination = Path(utils.__file__).resolve().parent / "resources" / "models"
    destination.mkdir(parents=True, exist_ok=True)
    source = _wake_asset_dir()
    for name in ("melspectrogram.onnx", "embedding_model.onnx", "hey_jarvis_v0.1.onnx"):
        bundled = source / name
        target = destination / name
        if bundled.exists() and (not target.exists() or target.stat().st_size != bundled.stat().st_size):
            shutil.copyfile(bundled, target)


def _load_wake_model():
    try:
        _stage_wake_models()
        from openwakeword.model import Model

        model = Model(wakeword_models=["hey_jarvis"], inference_framework="onnx")
        log.info("Wake word ready: %s", ", ".join(model.models.keys()))
        return model
    except Exception:
        log.exception("Wake word model failed")
        return None


_whisper_model = None
_whisper_lock = threading.Lock()


def _stt_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS")) / "assets" / "stt" / "faster-whisper-base"
    return Path(__file__).resolve().parents[1] / "assets" / "stt" / "faster-whisper-base"


def _load_whisper():
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        folder = _stt_dir()
        if not (folder / "model.bin").exists():
            log.info("Local speech model is not installed")
            return None
        try:
            from faster_whisper import WhisperModel

            log.info("Loading local speech model")
            _whisper_model = WhisperModel(
                str(folder),
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
            log.info("Local speech model ready")
            return _whisper_model
        except Exception:
            log.exception("Local speech model failed")
            return None


def _google_options(raw: bytes) -> list[str]:
    import speech_recognition as sr

    audio = sr.AudioData(raw, SAMPLE_RATE, 2)
    recognizer = sr.Recognizer()
    found: list[str] = []
    for language in ("en-US", "pl-PL"):
        try:
            result = recognizer.recognize_google(audio, language=language, show_all=True)
        except Exception as error:
            if type(error).__name__ == "UnknownValueError":
                continue
            log.warning("Google %s failed: %s", language, type(error).__name__)
            continue
        found.extend(_transcripts(result))
    return found


def _transcripts(result) -> list[str]:
    if not result:
        return []
    if isinstance(result, str):
        return [result]
    alternatives = result.get("alternative") if isinstance(result, dict) else None
    if not alternatives:
        return []
    texts: list[str] = []
    for item in alternatives:
        if isinstance(item, str) and item.strip():
            texts.append(item.strip())
        elif isinstance(item, dict) and str(item.get("transcript", "")).strip():
            texts.append(str(item["transcript"]).strip())
    return texts


def _whisper_options(raw: bytes, names: list[str]) -> list[str]:
    model = _load_whisper()
    if model is None:
        return []
    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    prompt = "Hey Jarvis. Launch, start, open, play, odpal, uruchom, włącz. " + ", ".join(names[:40])
    try:
        segments, _info = model.transcribe(
            audio,
            task="transcribe",
            initial_prompt=prompt,
            beam_size=5,
            vad_filter=False,
            condition_on_previous_text=False,
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return [text] if text else []
    except Exception:
        log.exception("Local transcription failed")
        return []


def _wake_score(model, samples: np.ndarray) -> float:
    try:
        scores = model.predict(samples)
    except Exception:
        audio = samples.astype(np.float32) / 32768.0
        scores = model.predict(audio)
    if not scores:
        return 0.0
    if "hey_jarvis" in scores:
        return float(scores["hey_jarvis"])
    matched = [value for key, value in scores.items() if re.search(r"jarvis", key, re.I)]
    if matched:
        return float(max(matched))
    return float(max(scores.values()))
