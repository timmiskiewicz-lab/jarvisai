from __future__ import annotations

import logging
import re
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

log = logging.getLogger("jarvisai.ears")

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms, the size openWakeWord expects


@dataclass
class Heard:
    text: str | None
    error: str | None = None


class Ears:
    """Local wake word, then one spoken command."""

    def __init__(self, state, settings_provider, on_wake) -> None:
        self.state = state
        self.settings_provider = settings_provider
        self.on_wake = on_wake
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
                        buffer = []
                        started = False
                        silence_ms = 0
                        started_at = time.time()
                    threshold = max(320.0, self._noise * 3.8)
                    if loud >= threshold:
                        started = True
                        silence_ms = 0
                        buffer.append(samples.copy())
                    elif started:
                        buffer.append(samples.copy())
                        silence_ms += 80
                        if silence_ms >= 900 or len(buffer) >= 90:
                            self._transcribe(buffer, generation)
                            buffer = []
                            started = False
                    elif time.time() - started_at > 7.5:
                        self._finish(generation, Heard(""))
                    continue

                generation = -1
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
        try:
            import speech_recognition as sr

            audio = sr.AudioData(raw, SAMPLE_RATE, 2)
            text = sr.Recognizer().recognize_google(audio, language="en-US")
            log.info("Heard: %s", text)
            self._finish(generation, Heard(text.strip()))
        except Exception as error:
            name = type(error).__name__
            if name == "UnknownValueError":
                self._finish(generation, Heard(""))
                return
            log.exception("Speech recognition failed")
            self._finish(generation, Heard(None, error=name))


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
