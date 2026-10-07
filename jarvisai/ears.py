from __future__ import annotations

import logging
import queue
import re
import shutil
import socket
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from jarvisai.brain import Catalog, addresses_jarvis, choose_transcript

log = logging.getLogger("jarvisai.ears")

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms, the size openWakeWord expects
# After the name, keep the mic open through a short pause so the rest of the sentence lands.
PHRASE_SILENCE_MS = 1400
PHRASE_MIN_HOLD_MS = 400
PHRASE_MAX_MS = 5500


def phrase_is_complete(silence_ms: int, held_ms: int) -> bool:
    if held_ms >= PHRASE_MAX_MS:
        return True
    return silence_ms >= PHRASE_SILENCE_MS and held_ms >= PHRASE_MIN_HOLD_MS


@dataclass
class Heard:
    text: str | None
    error: str | None = None
    options: list[str] | None = None


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
        self._wake_clip: list[np.ndarray] = []
        self._wake_heard: Heard | None = None
        self._bare_token = 0
        self._bare_pending: list[np.ndarray] | None = None
        self._bare_running = False
        self._mode_since = 0.0
        self._thread = threading.Thread(target=self._run, name="jarvis-ears", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.running = False

    def capture(self, timeout: float = 6.0) -> Heard:
        with self._lock:
            self._generation += 1
            self._result = None
            self._done.clear()
            self._capture = True
        self.state.update(mode="listening", status="Listening", caption="", amplitude=0.0)
        finished = self._done.wait(timeout + 8)
        with self._lock:
            self._capture = False
            result = self._result
        if not finished or result is None:
            self.state.update(mode="idle", status="Standing by", amplitude=0.0)
            return Heard("")
        return result

    def take_prepared(self) -> Heard | None:
        """Transcript already checked for a bare 'Jarvis', so it is not sent to speech again."""
        with self._lock:
            heard = self._wake_heard
            self._wake_heard = None
            if heard is not None:
                self._wake_clip = []
            return heard

    def take_wake_clip(self) -> bytes | None:
        with self._lock:
            frames = self._wake_clip
            self._wake_clip = []
        if len(frames) < 8:
            return None
        return np.concatenate(frames).tobytes()

    def _bump_bare(self) -> int:
        with self._lock:
            self._bare_token += 1
            return self._bare_token

    def _bare_current(self, token: int) -> bool:
        with self._lock:
            return token == self._bare_token and not self._capture

    def recognize(self, raw: bytes, catalog: Catalog) -> Heard:
        return _recognize(raw, catalog)

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
        frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=80)

        def callback(indata, _frames, _time_info, _status) -> None:
            chunk = np.squeeze(indata).astype(np.int16).copy()
            if chunk.size != FRAME:
                return
            try:
                frames.put_nowait(chunk)
            except queue.Full:
                try:
                    frames.get_nowait()
                except queue.Empty:
                    pass

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME,
            callback=callback,
        ):
            self.state.update(status="Standing by")
            buffer: list[np.ndarray] = []
            preroll: deque[np.ndarray] = deque(maxlen=25)
            started = False
            handed = False
            silence_ms = 0
            started_at = 0.0
            generation = -1
            empty_reads = 0
            following = False
            follow_frames: list[np.ndarray] = []
            follow_silence = 0
            follow_started = 0.0
            utterance: list[np.ndarray] = []
            utter_started = False
            utter_silence = 0
            while self.running:
                try:
                    samples = frames.get(timeout=0.5)
                except queue.Empty:
                    empty_reads += 1
                    self._unstick()
                    if empty_reads >= 6:
                        log.warning("Microphone stalled, reopening")
                        return
                    continue
                empty_reads = 0
                loud = _rms(samples)
                capturing = self._capture
                mode = self.state.snapshot()["mode"]
                self._unstick(mode)

                if mode != "speaking":
                    level = max(0.0, min(1.0, loud / 3500.0))
                    if mode != "thinking":
                        self.state.update(amplitude=level)

                if capturing:
                    following = False
                    utterance = []
                    utter_started = False
                    if generation != self._generation:
                        generation = self._generation
                        handed = False
                        threshold = max(160.0, self._noise * 2.4)
                        buffer = list(preroll)
                        preroll.clear()
                        started = any(_rms(chunk) >= threshold for chunk in buffer)
                        silence_ms = 0
                        started_at = time.time()
                    if handed:
                        continue
                    threshold = max(160.0, self._noise * 2.4)
                    if loud >= threshold:
                        started = True
                        silence_ms = 0
                        buffer.append(samples.copy())
                    elif started:
                        buffer.append(samples.copy())
                        silence_ms += 80
                        if silence_ms >= 850 or len(buffer) >= 90:
                            self._transcribe_later(buffer, generation)
                            buffer = []
                            started = False
                            handed = True
                    elif time.time() - started_at > 6.0:
                        self._finish(generation, Heard(""))
                        handed = True
                    continue

                generation = -1
                handed = False
                if following:
                    follow_frames.append(samples.copy())
                    floor = max(180.0, self._noise * 2.2)
                    if loud >= floor:
                        follow_silence = 0
                    else:
                        follow_silence += 80
                    held_ms = int((time.time() - follow_started) * 1000)
                    if phrase_is_complete(follow_silence, held_ms):
                        following = False
                        with self._lock:
                            self._wake_clip = follow_frames
                            self._wake_heard = None
                        follow_frames = []
                        self._cooldown_until = time.time() + 1.2
                        log.info("Wake phrase finished, checking the rest")
                        self._notify_wake()
                    continue

                if mode == "speaking":
                    preroll.clear()
                    utterance = []
                    utter_started = False
                    self._hits = 0
                    self._was_busy = True
                    continue
                preroll.append(samples.copy())
                self._noise = self._noise * 0.98 + loud * 0.02
                if mode in {"thinking", "listening"}:
                    self._hits = 0
                    self._was_busy = True
                    utterance = []
                    utter_started = False
                    continue
                if self._was_busy and model is not None:
                    self._was_busy = False
                    self._cooldown_until = time.time() + 0.6
                    try:
                        model.reset()
                    except Exception:
                        log.debug("Wake model reset failed", exc_info=True)
                triggered = False
                if model is not None and time.time() >= self._cooldown_until:
                    score = _wake_score(model, samples)
                    threshold = float(self.settings_provider().wake_threshold)
                    if score >= threshold:
                        self._hits += 1
                    else:
                        self._hits = 0
                    if self._hits >= 2:
                        self._hits = 0
                        triggered = True
                        log.info("Wake word heard (%.2f)", score)
                        try:
                            model.reset()
                        except Exception:
                            log.debug("Wake model reset failed", exc_info=True)
                if triggered:
                    following = True
                    follow_started = time.time()
                    follow_silence = 0
                    follow_frames = list(preroll)
                    utterance = []
                    utter_started = False
                    self._bump_bare()
                    self.state.update(mode="listening", status="Listening", caption="", amplitude=0.0)
                    continue

                floor = max(180.0, self._noise * 2.2)
                if loud >= floor:
                    if not utter_started:
                        utterance = list(preroll)
                        utter_started = True
                    else:
                        utterance.append(samples.copy())
                    utter_silence = 0
                    if len(utterance) > 100:
                        utterance = []
                        utter_started = False
                elif utter_started:
                    utterance.append(samples.copy())
                    utter_silence += 80
                    if utter_silence >= PHRASE_SILENCE_MS:
                        clip = utterance
                        utterance = []
                        utter_started = False
                        self._consider_bare(clip)
                    elif len(utterance) > 100:
                        utterance = []
                        utter_started = False

    def _unstick(self, mode: str | None = None) -> None:
        mode = mode if mode is not None else self.state.snapshot()["mode"]
        if mode in {"listening", "thinking", "speaking"}:
            if self._mode_since == 0.0:
                self._mode_since = time.time()
            else:
                limit = 20.0 if mode == "speaking" else 15.0
                if time.time() - self._mode_since > limit:
                    log.warning("Listener stalled, resetting")
                    self._capture = False
                    self._done.set()
                    self._mode_since = 0.0
                    self._bump_bare()
                    self.state.update(mode="idle", status="Standing by", amplitude=0.0)
        else:
            self._mode_since = 0.0

    def _transcribe_later(self, frames: list[np.ndarray], generation: int) -> None:
        threading.Thread(
            target=self._transcribe,
            args=(frames, generation),
            name="jarvis-stt-once",
            daemon=True,
        ).start()

    def _transcribe(self, frames: list[np.ndarray], generation: int) -> None:
        if not frames:
            self._finish(generation, Heard(""))
            return
        self.state.update(mode="thinking", status="Recognizing", amplitude=0.0)
        raw = np.concatenate(frames).tobytes()
        try:
            heard = _recognize(raw, self._catalog())
            self._finish(generation, heard)
        except Exception as error:
            log.exception("Speech recognition failed")
            self._finish(generation, Heard(None, error=type(error).__name__))

    def _notify_wake(self) -> None:
        started = self.on_wake()
        if started is False:
            log.info("Wake ignored because a conversation is still running")
            self.state.update(mode="idle", status="Standing by", caption="", amplitude=0.0)

    def _consider_bare(self, frames: list[np.ndarray]) -> None:
        loud = sum(1 for frame in frames if _rms(frame) >= 180)
        if loud < 6 or len(frames) > 100:
            return
        with self._lock:
            self._bare_pending = frames
            self._bare_token += 1
            if self._bare_running:
                return
            self._bare_running = True
        threading.Thread(target=self._bare_loop, name="jarvis-name", daemon=True).start()

    def _bare_loop(self) -> None:
        while True:
            with self._lock:
                frames = self._bare_pending
                self._bare_pending = None
                if frames is None:
                    self._bare_running = False
                    return
                self._bare_token += 1
                token = self._bare_token
            self._bare_jarvis(frames, token)

    def _bare_jarvis(self, frames: list[np.ndarray], token: int) -> None:
        if not self._bare_current(token):
            return
        try:
            heard = _recognize(
                np.concatenate(frames).tobytes(),
                self._catalog(),
                quiet=True,
                local=False,
            )
        except Exception:
            log.debug("Name check failed", exc_info=True)
            return
        text = heard.text or ""
        if not self._bare_current(token) or not addresses_jarvis(text):
            log.debug("Speech was not addressed to Jarvis: %s", text or "(silence)")
            return
        with self._lock:
            if token != self._bare_token:
                return
            self._wake_clip = frames
            self._wake_heard = heard
        log.info("Jarvis heard on its own: %s", text)
        self._notify_wake()

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


def _recognize(raw: bytes, catalog: Catalog, quiet: bool = False, local: bool = True) -> Heard:
    options = _google_options(raw)
    text = choose_transcript(options, catalog)
    if not options and local:
        names = [game.name for game in catalog.games]
        names.extend(game.name for game in (catalog.library or [])[:40])
        options.extend(_whisper_options(raw, names))
        text = choose_transcript(options, catalog)
    if not quiet:
        log.info("Heard: %s", text or "(silence)")
        if options:
            log.info("Alternatives: %s", " | ".join(options[:8]))
    return Heard(text, options=options[:8])


def _google_options(raw: bytes) -> list[str]:
    import speech_recognition as sr

    audio = sr.AudioData(raw, SAMPLE_RATE, 2)
    found: list[str] = []
    lock = threading.Lock()
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(4)

    def one(language: str) -> None:
        try:
            result = sr.Recognizer().recognize_google(audio, language=language, show_all=True)
        except Exception as error:
            if type(error).__name__ != "UnknownValueError":
                log.warning("Google %s failed: %s", language, type(error).__name__)
            return
        texts = _transcripts(result)
        with lock:
            found.extend(texts)

    workers = [threading.Thread(target=one, args=(language,), daemon=True) for language in ("pl-PL", "en-US")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(4.5)
    socket.setdefaulttimeout(previous)
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
    prompt = "Hej Jarvis. Odpal, uruchom, włącz, zainstaluj, pobierz. " + ", ".join(names[:30])
    try:
        with _whisper_lock:
            segments, _info = model.transcribe(
                audio,
                task="transcribe",
                initial_prompt=prompt,
                beam_size=1,
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
