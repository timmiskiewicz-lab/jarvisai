from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading

from jarvisai.autostart import ensure_autostart
from jarvisai.brain import (
    Brain,
    Catalog,
    Step,
    command_score,
    extract_install_target,
    extract_launch_target,
    extract_spotify,
    extract_volume,
    is_wake_only,
    rank_games,
    strip_wake,
)
from jarvisai.config import load_settings, save_settings
from jarvisai.ears import Ears, Heard
from jarvisai.gemini import api_key, interpret, store_api_key
from jarvisai.link import StateLink
from jarvisai.paths import hud_dir, log_path
from jarvisai.wallpaper import ASK_LINE, find_engine, install_and_apply, remember, should_ask
from jarvisai.spotify import find_song, open_spotify
from jarvisai.volume import raise_volume
from jarvisai.steam import (
    autologin_user,
    begin_install,
    installed_games,
    launch_game,
    needs_account_switch,
    steam_profiles,
    steam_root,
    uninstalled_games,
)
from jarvisai.tts import Speaker

log = logging.getLogger("jarvisai")

_MUTEX = None
WIDTH = 860
HEIGHT = 940


class SharedState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.mode = "idle"
        self.amplitude = 0.0
        self.caption = ""
        self.status = "Starting systems"

    def update(self, **kwargs) -> None:
        with self._lock:
            for key, value in kwargs.items():
                setattr(self, key, value)

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "amplitude": float(self.amplitude),
                "caption": self.caption,
                "status": self.status,
            }


class Api:
    def __init__(self, app: "JarvisApp") -> None:
        self._app = app

    def get_state(self) -> dict:
        snap = self._app.state.snapshot()
        snap["voice"] = self._app.voice_label()
        snap["wallpaper"] = find_engine() is not None
        return snap

    def hide_window(self) -> bool:
        self._app.hide()
        return True

    def get_settings(self) -> dict:
        settings = self._app.settings
        return {
            "api_key": settings.elevenlabs_api_key,
            "voice_id": settings.elevenlabs_voice_id,
            "elevenlabs": settings.uses_elevenlabs,
            "gemini_key": api_key(),
            "gemini": bool(api_key()),
        }

    def save_settings(self, api_key: str, gemini_key: str | None = None) -> dict:
        self._app.settings.elevenlabs_api_key = (api_key or "").strip()
        save_settings(self._app.settings)
        self._app.speaker.reload()
        if gemini_key is not None:
            store_api_key(gemini_key)
        log.info("Settings saved")
        return {
            "ok": True,
            "elevenlabs": self._app.settings.uses_elevenlabs,
            "gemini": bool(api_key()),
        }

    def test_voice(self) -> dict:
        return {"ok": self._app.test_voice()}

    def listen_now(self) -> bool:
        self._app.request_conversation()
        return True

    def install_wallpaper(self) -> dict:
        if find_engine() is None:
            return {"ok": False, "message": "Wallpaper Engine is not installed."}
        message = install_and_apply()
        return {"ok": "online" in message.lower() or "copied" in message.lower(), "message": message}


class JarvisApp:
    def __init__(self) -> None:
        self.state = SharedState()
        self.settings = load_settings()
        self.speaker = Speaker()
        self.brain = Brain()
        self._busy = threading.Lock()
        self._quitting = False
        self.window = None
        self.icon = None
        self.ears = Ears(self.state, lambda: self.settings, self.request_conversation, self.catalog)
        self.link = StateLink(self.state.snapshot)
        self._offer_attempts = 0

    def voice_label(self) -> str:
        if self.settings.uses_elevenlabs:
            return "Daniel · ElevenLabs"
        return "Jarvis"

    def speak(self, text: str) -> None:
        self.state.update(mode="speaking", caption=text, status="Speaking", amplitude=0.0)
        try:
            self.speaker.play(text, lambda amplitude: self.state.update(amplitude=amplitude))
        except Exception:
            log.exception("Speech failed")
            self.state.update(status="Voice failed")
            threading.Event().wait(1.2)
        finally:
            if self.state.snapshot()["mode"] == "speaking":
                self.state.update(mode="idle", status="Standing by", amplitude=0.0)
            else:
                self.state.update(amplitude=0.0)

    def request_conversation(self) -> bool:
        if not self._busy.acquire(blocking=False):
            return False
        threading.Thread(target=self._conversation, name="jarvis-talk", daemon=True).start()
        return True

    def test_voice(self) -> bool:
        if not self._busy.acquire(blocking=False):
            return False

        def run() -> None:
            try:
                self.speak("At your service, sir.")
            finally:
                self.state.update(mode="idle", status="Standing by", caption="", amplitude=0.0)
                self._busy.release()

        threading.Thread(target=run, name="jarvis-test-voice", daemon=True).start()
        return True

    def catalog(self) -> Catalog:
        root = steam_root()
        if root is None:
            return Catalog(False, [], [])
        try:
            return Catalog(True, installed_games(root), steam_profiles(root), uninstalled_games(root))
        except Exception:
            log.exception("Could not read Steam")
            return Catalog(True, [], [])

    def _conversation(self) -> None:
        try:
            heard = self.ears.take_prepared()
            if heard is None:
                clip = self.ears.take_wake_clip()
                heard = self.ears.recognize(clip, self.catalog()) if clip else None
            if heard and heard.error:
                step = self._understand(heard, self.catalog())
            elif heard and heard.text and not is_wake_only(heard.text):
                self.brain.begin()
                step = self._understand(heard, self.catalog())
            else:
                step = self.brain.begin()
            while True:
                step = self._act(step)
                if not step.listen:
                    break
                self.state.update(mode="listening", status="Listening", caption="", amplitude=0.0)
                heard = self.ears.capture(6)
                if heard.error:
                    step = Step(
                        say="I can't reach speech recognition right now, sir.",
                        listen=False,
                        phase="idle",
                    )
                    continue
                if heard.text:
                    self.state.update(status=f"Heard: {heard.text}", caption=heard.text)
                step = self._understand(heard, self.catalog())
        except Exception:
            log.exception("Conversation failed")
        finally:
            self.state.update(mode="idle", status="Standing by", caption="", amplitude=0.0)
            self._busy.release()

    def _act(self, step: Step) -> Step:
        if step.volume:
            self._turn_up(step.volume)
            return step
        if step.spotify:
            self._play_spotify(step.spotify)
            return step
        if step.install:
            if step.say:
                self.speak(step.say)
            self.state.update(mode="thinking", status="Installing", caption=step.install.name)
            when = begin_install(step.install)
            if when:
                self.speak(f"It should be finished at {when}, sir.")
            else:
                self.speak("Steam is installing it, sir. It hasn't reported a finish time yet.")
            return step
        if step.launch:
            game, profile = step.launch
            current = autologin_user()
            if needs_account_switch(profile, current):
                persona = profile.persona_name or profile.account_name or "that profile"
                line = f"Switching to {persona} and launching {game.name}, sir."
                if not profile.remember_password:
                    line += " Steam may ask you to sign in."
                self.speak(line)
            elif step.say:
                self.speak(step.say)
            self.state.update(mode="thinking", status="Opening Steam", caption="")
            error = launch_game(game, profile)
            if error:
                self.speak(error)
            return step
        if step.wallpaper == "decline":
            remember(declined=True)
        if step.wallpaper == "install":
            if step.say:
                self.speak(step.say)
            self.state.update(mode="thinking", status="Installing wallpaper", caption="")
            self.speak(install_and_apply())
            return step
        if step.say:
            self.speak(step.say)
        return step

    def _understand(self, heard: Heard, catalog: Catalog) -> Step:
        if heard.error:
            return Step(say="I can't reach speech recognition right now, sir.", listen=False, phase="idle")
        options = list(heard.options or [])
        if heard.text and heard.text not in options:
            options.insert(0, heard.text)
        text = heard.text or ""
        if extract_volume(text) or extract_spotify(strip_wake(text)):
            return self.brain.handle(text, catalog)
        target = extract_launch_target(strip_wake(text)) or extract_install_target(text)
        clear = (
            self.brain.phase in {"profile", "game", "install", "wallpaper"}
            or is_wake_only(text)
            or bool(extract_install_target(text))
            or command_score(text, catalog) >= 0.8
            or bool(target and rank_games(target, catalog.library or []))
        )
        if clear:
            return self.brain.handle(text, catalog)
        self.state.update(mode="thinking", status="Understanding", caption=text)
        intent = interpret(options, catalog, self.brain.phase)
        if intent is None:
            return self.brain.handle(text, catalog)
        return self.brain.apply(intent, catalog, heard.text)

    def _turn_up(self, step: int) -> None:
        try:
            level = raise_volume(step)
        except Exception:
            log.exception("Volume did not change")
            self.speak("I couldn't change the volume, sir.")
            return
        if level is None:
            self.speak("It's already as loud as it goes, sir.")
            return
        if step == 10:
            self.speak("Turning it up, sir.")
        else:
            self.speak(f"Turning it up by {step} percent, sir.")

    def _play_spotify(self, ask) -> None:
        found = find_song(ask)
        if found:
            title, artist = found
        elif ask.title:
            title, artist = ask.title, ask.artist
        else:
            self.speak("I couldn't find that on Spotify, sir.")
            return
        self.speak(f"Playing {title} by {artist}, sir.")
        self.state.update(mode="thinking", status="Opening Spotify", caption=title)
        try:
            open_spotify(title, artist)
        except Exception:
            log.exception("Spotify did not open")
            self.speak("I couldn't open Spotify, sir.")

    def offer_wallpaper(self) -> None:
        if self._quitting or not should_ask():
            return
        if not self._busy.acquire(blocking=False):
            self._offer_attempts += 1
            if self._offer_attempts < 4:
                threading.Timer(8.0, self.offer_wallpaper).start()
            return
        threading.Thread(target=self._offer_wallpaper, name="jarvis-wallpaper", daemon=True).start()

    def _offer_wallpaper(self) -> None:
        try:
            self.brain.phase = "wallpaper"
            self.brain._greeted = True
            step = Step(say=ASK_LINE, listen=True, phase="wallpaper")
            while True:
                step = self._act(step)
                if not step.listen:
                    break
                self.state.update(mode="listening", status="Listening", caption="", amplitude=0.0)
                heard = self.ears.capture(6)
                if heard.text:
                    self.state.update(status=f"Heard: {heard.text}", caption=heard.text)
                step = self._understand(heard, self.catalog())
        except Exception:
            log.exception("Wallpaper question failed")
        finally:
            self.state.update(mode="idle", status="Standing by", caption="", amplitude=0.0)
            self._busy.release()

    def hide(self) -> None:
        if self.window is not None:
            self.window.hide()

    def show(self) -> None:
        if self.window is not None:
            self.window.show()
            try:
                self.window.restore()
            except Exception:
                pass

    def quit(self) -> None:
        self._quitting = True
        self.ears.stop()
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                log.debug("Tray icon was already stopped", exc_info=True)
        os._exit(0)

    def run(self) -> None:
        import webview

        self.link.start()
        self.ears.start()
        self._start_tray()
        threading.Timer(3.0, self.offer_wallpaper).start()
        api = Api(self)
        x, y = _center(WIDTH, HEIGHT)
        self.window = webview.create_window(
            "JarvisAI",
            (hud_dir() / "index.html").as_uri(),
            js_api=api,
            width=WIDTH,
            height=HEIGHT,
            x=x,
            y=y,
            frameless=True,
            easy_drag=False,
            resizable=False,
            shadow=True,
            on_top=False,
            background_color="#061018",
            text_select=True,
        )
        self.window.events.closing += self._on_closing
        webview.start(gui="edgechromium")
        self.quit()

    def _on_closing(self) -> bool:
        if self._quitting:
            return True
        self.hide()
        return False

    def _start_tray(self) -> None:
        import pystray
        from PIL import Image, ImageDraw

        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.ellipse((4, 4, 60, 60), outline=(90, 220, 255, 255), width=4)
        draw.ellipse((16, 16, 48, 48), outline=(226, 177, 90, 255), width=3)
        menu = pystray.Menu(
            pystray.MenuItem("Show Jarvis", lambda _icon, _item: self.show(), default=True),
            pystray.MenuItem("Quit", lambda _icon, _item: self.quit()),
        )
        self.icon = pystray.Icon("JarvisAI", image, "JarvisAI", menu)
        threading.Thread(target=self.icon.run, name="jarvis-tray", daemon=True).start()


def _center(width: int, height: int) -> tuple[int, int]:
    user32 = ctypes.windll.user32
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    return max(0, (screen_w - width) // 2), max(0, (screen_h - height) // 2)


def _already_running() -> bool:
    global _MUTEX
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, "Local\\JarvisAI.SingleInstance")
    if not handle:
        return False
    if kernel32.GetLastError() == 183:
        return True
    _MUTEX = handle
    return False


def _setup_logging() -> None:
    handlers: list[logging.Handler] = [logging.FileHandler(log_path(), encoding="utf-8")]
    if not getattr(sys, "frozen", False):
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )


def _prepare_windows() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JarvisAI.Desktop")
    except Exception:
        pass
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        log.debug("Windows certificate store was not injected", exc_info=True)


def main() -> None:
    _setup_logging()
    _prepare_windows()
    if _already_running():
        log.info("JarvisAI is already running")
        return
    try:
        ensure_autostart()
        JarvisApp().run()
    except Exception as error:
        log.exception("JarvisAI stopped")
        ctypes.windll.user32.MessageBoxW(
            0,
            f"JarvisAI could not start.\n\n{error}\n\nDetails are in {log_path()}",
            "JarvisAI",
            0x10,
        )


if __name__ == "__main__":
    main()
