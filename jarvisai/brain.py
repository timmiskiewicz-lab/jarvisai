from __future__ import annotations

import random
import re
from dataclasses import dataclass

from jarvisai.steam import Game, Profile, search_uninstalled

GREETINGS = (
    "What's up, sir? What are you doing today?",
    "What's up, sir? What can I do for you?",
    "At your service, sir. What are you doing today?",
    "Yes, sir? What would you like me to do?",
    "Good to hear you, sir. What are we working on?",
    "Online and ready, sir. Shall I launch something, or install a game?",
    "Right here, sir. Tell me what you need.",
    "For you, sir, always. What's the plan today?",
    "Standing by, sir. Name a game and I'll take care of it.",
    "Ready when you are, sir. What are you doing today?",
    "How can I help you, sir? I can launch a game or install one from your library.",
    "Yes, sir?",
)

_ORDINALS = (
    ("first", "1st", "one", "pierwszy"),
    ("second", "2nd", "two", "drugi"),
    ("third", "3rd", "three", "trzeci"),
    ("fourth", "4th", "four", "czwarty"),
    ("fifth", "5th", "five", "piaty", "piąty"),
    ("sixth", "6th", "six", "szosty", "szósty"),
    ("seventh", "7th", "seven"),
    ("eighth", "8th", "eight"),
)
_ORDINAL_LABELS = ("First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth")

_ROMAN = {
    "i": "1",
    "ii": "2",
    "iii": "3",
    "iv": "4",
    "v": "5",
    "vi": "6",
    "vii": "7",
    "viii": "8",
    "ix": "9",
    "x": "10",
}
_NUMBER_WORDS = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
    "jeden": "1",
    "dwa": "2",
    "trzy": "3",
    "cztery": "4",
    "piec": "5",
    "pięć": "5",
    "szesc": "6",
    "sześć": "6",
    "siedem": "7",
    "osiem": "8",
    "dziewiec": "9",
    "dziewięć": "9",
    "dziesiec": "10",
    "dziesięć": "10",
}

_LAUNCH = re.compile(
    r"\b(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
    r"(?:launch|start|open|run|play|boot|fire up|uruchom|odpal|odpalaj|wlacz|włącz|zagraj|otworz|otwórz)"
    r"\b\s+(?:the\s+)?(?:game\s+)?(.+)",
    re.IGNORECASE,
)
_PROFILE_HINT = re.compile(
    r"\b(?:on|using|with|profile)\s+(?:the\s+)?"
    r"(first|second|third|fourth|fifth|sixth|seventh|eighth|"
    r"one|two|three|four|five|six|seven|eight|[1-8])"
    r"\b(?:\s+profile)?",
    re.IGNORECASE,
)
_INSTALL = re.compile(
    r"\b(?:please\s+)?(?:can you\s+|could you\s+|prosz[eę]\s+)?"
    r"(?:install|download|zainstaluj|instaluj|pobierz|sciagnij|ściągnij|wgraj)"
    r"\b\s+(?:mi\s+)?(?:the\s+)?(?:game\s+)?(?:gre\s+)?(.+)",
    re.IGNORECASE,
)
_CANCEL = re.compile(r"\b(cancel|never mind|nevermind|stop|abort|forget it|anuluj|nieważne|niewazne)\b", re.IGNORECASE)
_YES = re.compile(
    r"\b(yes|yeah|yep|sure|ok|okay|do it|install|please|tak|dawaj|jasne|pewnie|zainstaluj|instaluj|chce|chcę)\b",
    re.IGNORECASE,
)
_NO = re.compile(r"\b(no|nope|don't|dont|nie|zostaw|pomin|pomiń|later|pozniej|później)\b", re.IGNORECASE)
_WAKE = re.compile(r"\b(?:hey|hi|ok|okay|yo)\s+jarv\w*\b", re.IGNORECASE)
_JARVIS_WORD = re.compile(r"\bjarv\w*\b", re.IGNORECASE)


@dataclass
class Catalog:
    steam_found: bool
    games: list[Game]
    profiles: list[Profile]
    library: list[Game] | None = None

    def __post_init__(self) -> None:
        if self.library is None:
            self.library = []


@dataclass
class Step:
    say: str | None = None
    listen: bool = False
    launch: tuple[Game, Profile] | None = None
    phase: str = "idle"
    wallpaper: str | None = None
    install: Game | None = None


def normalize(text: str) -> str:
    cleaned = text.lower().replace("®", " ").replace("™", " ")
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    tokens = cleaned.split()
    output: list[str] = []
    for index, token in enumerate(tokens):
        if token in _NUMBER_WORDS:
            output.append(_NUMBER_WORDS[token])
        elif index > 0 and token in _ROMAN:
            output.append(_ROMAN[token])
        else:
            output.append(token)
    return " ".join(output)


def score_name(query: str, name: str) -> float:
    from difflib import SequenceMatcher

    left = normalize(query)
    right = normalize(name)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_numbers = set(re.findall(r"\d+", left))
    right_numbers = set(re.findall(r"\d+", right))
    score = SequenceMatcher(None, left, right).ratio()
    if left in right or right in left:
        score = max(score, 0.9)
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if left_tokens and left_tokens <= right_tokens:
        score = max(score, 0.86)
    if left_numbers and left_numbers != right_numbers:
        score *= 0.4
    return score


def rank_games(query: str, games: list[Game]) -> list[Game]:
    scored = [(score_name(query, game.name), game) for game in games]
    scored = [(score, game) for score, game in scored if score >= 0.64]
    scored.sort(key=lambda item: item[0], reverse=True)
    if not scored:
        return []
    best = scored[0][0]
    window = 0.03 if best >= 0.98 else 0.08
    return [game for score, game in scored if best - score <= window][:4]


def parse_ordinal(text: str) -> int | None:
    lowered = text.lower()
    for index, words in enumerate(_ORDINALS):
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return index
    match = re.search(r"\b([1-8])\b", lowered)
    if match:
        return int(match.group(1)) - 1
    return None


def strip_wake(text: str) -> str:
    return _WAKE.sub(" ", text).strip(" ,.")


def is_wake_only(text: str) -> bool:
    """True when the phrase is only the wake word, including the mishearing 'play jarvis'."""
    raw = _JARVIS_WORD.sub(" ", strip_wake(text))
    target = extract_launch_target(raw)
    if target and not _JARVIS_WORD.fullmatch(normalize(target).strip()):
        return False
    leftover = re.sub(
        r"\b(play|start|launch|open|run|boot|please|hey|hi|ok|okay|yo|the|a|an|game|sir)\b",
        " ",
        raw,
        flags=re.IGNORECASE,
    )
    leftover = re.sub(r"[^a-z0-9]+", " ", leftover.lower()).strip()
    return leftover == ""


def command_score(text: str, catalog: Catalog) -> float:
    if is_wake_only(text):
        return -1.0
    target = extract_launch_target(strip_wake(text))
    query = target or text
    matches = rank_games(query, catalog.games)
    if not matches:
        return 0.0
    score = score_name(query, matches[0].name)
    if target:
        score += 0.15
    if len(matches) == 1 and score >= 0.8:
        score += 0.1
    return score


def choose_transcript(options: list[str], catalog: Catalog) -> str:
    cleaned: list[str] = []
    for option in options:
        text = " ".join((option or "").split())
        if text and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return ""
    ranked = sorted(cleaned, key=lambda text: command_score(text, catalog), reverse=True)
    if command_score(ranked[0], catalog) > 0:
        return ranked[0]
    for text in cleaned:
        if not is_wake_only(text):
            return text
    return cleaned[0]


def extract_install_target(text: str) -> str | None:
    match = _INSTALL.search(text.strip())
    if not match:
        return None
    target = re.sub(r"\b(please|for me|sir|thanks|thank you|prosze|proszę|mi)\b", " ", match.group(1), flags=re.IGNORECASE)
    target = re.sub(r"\s+", " ", target).strip(" .,_-")
    return target or None


def extract_launch_target(text: str) -> str | None:
    match = _LAUNCH.search(text.strip())
    if not match:
        return None
    target = match.group(1)
    target = re.sub(r"\b(please|for me|sir|thanks|thank you)\b", " ", target, flags=re.IGNORECASE)
    target = re.sub(r"\s+", " ", target).strip(" .,_-")
    return target or None


def split_profile_hint(text: str) -> tuple[str, str | None]:
    match = _PROFILE_HINT.search(text)
    if not match:
        return text, None
    hint = match.group(1)
    cleaned = f"{text[: match.start()]} {text[match.end() :]}"
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, hint


def _labels(items: list, name_of) -> str:
    parts = [f"{_ORDINAL_LABELS[index]}, {name_of(item)}" for index, item in enumerate(items[:8])]
    return ". ".join(parts)


def game_prompt(games: list[Game]) -> str:
    return f"I found more than one match, sir. {_labels(games, lambda game: game.name)}. Which one?"


def profile_prompt(profiles: list[Profile]) -> str:
    return (
        "Which profile do you want me to launch, sir? "
        f"{_labels(profiles, lambda profile: profile.persona_name)}."
    )


def _named_profile(text: str, profiles: list[Profile]) -> int | None:
    lowered = text.lower()
    for index, profile in enumerate(profiles):
        persona = profile.persona_name.lower().strip()
        account = profile.account_name.lower().strip()
        if len(persona) >= 3 and re.search(rf"\b{re.escape(persona)}\b", lowered):
            return index
        if len(account) >= 3 and re.search(rf"\b{re.escape(account)}\b", lowered):
            return index
    return None


class Brain:
    def __init__(self) -> None:
        self.phase = "idle"
        self._games: list[Game] = []
        self._profiles: list[Profile] = []
        self._game: Game | None = None
        self._retries = 0
        self._pending_hint: str | None = None
        self._pending_named: int | None = None
        self._greeted = False

    def begin(self) -> Step:
        self.phase = "command"
        self._retries = 0
        self._games = []
        self._profiles = []
        self._game = None
        self._pending_hint = None
        self._pending_named = None
        self._greeted = True
        return Step(say=random.choice(GREETINGS), listen=True, phase="command")

    def _acknowledge(self) -> Step:
        if not self._greeted:
            self._greeted = True
            self.phase = "command"
            return Step(say=random.choice(GREETINGS), listen=True, phase="command")
        self._retries += 1
        if self._retries <= 2:
            return Step(say="Yes, sir?", listen=True, phase=self.phase)
        self.phase = "idle"
        return Step(say="Standing by, sir.", listen=False, phase="idle")

    def handle(self, text: str | None, catalog: Catalog) -> Step:
        if self.phase == "wallpaper":
            if text is None or not text.strip():
                return self._retry("Say yes or no, sir.")
            return self._wallpaper_answer(text)
        if text is None or not text.strip() or (self.phase == "command" and is_wake_only(text)):
            return self._acknowledge()

        if _CANCEL.search(text):
            self.phase = "idle"
            return Step(say="Very well, sir.", listen=False, phase="idle")

        if self.phase == "install":
            return self._pick_install(text)
        if self.phase == "game":
            return self._pick_game(text, catalog)
        if self.phase == "profile":
            return self._pick_profile(text)
        return self._command(text, catalog)

    def _command(self, text: str, catalog: Catalog) -> Step:
        raw = strip_wake(text)
        named = _named_profile(raw, catalog.profiles) if len(catalog.profiles) > 1 else None
        if named is not None:
            profile = catalog.profiles[named]
            for label in (profile.persona_name, profile.account_name):
                if label:
                    raw = re.sub(rf"\b{re.escape(label)}\b", " ", raw, flags=re.IGNORECASE)
        cleaned, hint = split_profile_hint(raw)
        install_target = extract_install_target(cleaned)
        if install_target:
            return self._install_named(install_target, catalog, explicit=True)
        target = extract_launch_target(cleaned)
        if not target:
            self.phase = "idle"
            return Step(
                say="I can launch Steam games for now, sir. Try launch Gothic 1.",
                listen=False,
                phase="idle",
            )
        if not catalog.steam_found:
            self.phase = "idle"
            return Step(say="I can't find Steam on this computer, sir.", listen=False, phase="idle")

        matches = rank_games(target, catalog.games)
        if not matches:
            library_matches = self._library_matches(target, catalog)
            if len(library_matches) == 1:
                return self._queue_install(library_matches[0], missing=True)
            if len(library_matches) > 1:
                return self._offer_install(library_matches)
        if not matches:
            self._retries += 1
            if self._retries <= 1:
                self.phase = "command"
                return Step(
                    say="I couldn't find that game, sir. Say the name again.",
                    listen=True,
                    phase="command",
                )
            self.phase = "idle"
            return Step(
                say="I couldn't find that game in your Steam library, sir.",
                listen=False,
                phase="idle",
            )
        if len(matches) > 1:
            self._games = matches
            self._profiles = catalog.profiles
            self.phase = "game"
            self._retries = 0
            self._pending_hint = hint
            self._pending_named = named
            return Step(say=game_prompt(matches), listen=True, phase="game")

        self._game = matches[0]
        return self._after_game(catalog, hint=hint, named=named)

    def _pick_game(self, text: str, catalog: Catalog) -> Step:
        index = parse_ordinal(text)
        if index is None:
            narrowed = rank_games(text, self._games)
            if len(narrowed) == 1:
                self._game = narrowed[0]
            else:
                return self._retry("Say first, second, or the game name, sir.")
        elif index >= len(self._games):
            return self._retry("That number isn't on the list, sir.")
        else:
            self._game = self._games[index]
        hint = getattr(self, "_pending_hint", None)
        named = getattr(self, "_pending_named", None)
        return self._after_game(catalog, hint=hint, named=named)

    def _after_game(self, catalog: Catalog, hint: str | None, named: int | None) -> Step:
        profiles = catalog.profiles
        if not profiles:
            profile = Profile("", "your account", True, True)
            return self._launch(profile, chosen=False)
        if len(profiles) == 1:
            return self._launch(profiles[0], chosen=False)
        if named is not None and named < len(profiles):
            return self._launch(profiles[named], chosen=True)
        if hint:
            index = parse_ordinal(hint)
            if index is not None and index < len(profiles):
                return self._launch(profiles[index], chosen=True)
        self._profiles = profiles
        self.phase = "profile"
        self._retries = 0
        return Step(say=profile_prompt(profiles), listen=True, phase="profile")

    def _pick_profile(self, text: str) -> Step:
        index = parse_ordinal(text)
        if index is None:
            index = _named_profile(text, self._profiles)
        if index is None or index >= len(self._profiles):
            return self._retry("Say first, second, or the profile name, sir.")
        return self._launch(self._profiles[index], chosen=True)

    def _launch(self, profile: Profile, chosen: bool) -> Step:
        game = self._game
        self.phase = "idle"
        if game is None:
            return Step(say="I lost track of that game, sir.", listen=False, phase="idle")
        if chosen and profile.persona_name:
            line = f"Launching {game.name} on {profile.persona_name}, sir."
        else:
            line = f"Launching {game.name}, sir."
        return Step(say=line, listen=False, launch=(game, profile), phase="idle")

    def apply(self, intent: dict, catalog: Catalog, heard: str | None) -> Step:
        kind = str(intent.get("intent") or "unknown")
        if kind in {"wallpaper_yes", "wallpaper_no"} or self.phase == "wallpaper":
            if kind == "wallpaper_no":
                return self._decline_wallpaper()
            if kind == "wallpaper_yes":
                return self._accept_wallpaper()
            if self.phase == "wallpaper":
                return self._wallpaper_answer(heard or "")
        if kind == "cancel":
            self.phase = "idle"
            return Step(say="Very well, sir.", listen=False, phase="idle")
        if kind == "wake":
            return self._acknowledge()
        if kind == "install" and intent.get("game"):
            return self._install_named(str(intent["game"]), catalog, explicit=True)
        if kind == "launch" and intent.get("game"):
            phrase = f"launch {intent['game']}"
            choice = str(intent.get("choice") or "").strip()
            if choice:
                if re.fullmatch(r"first|second|third|fourth|fifth|sixth|seventh|eighth|[1-8]", choice, re.I):
                    phrase += f" on the {choice} profile"
                else:
                    phrase += f" {choice}"
            return self._command(phrase, catalog)
        if kind == "choose":
            return self.handle(str(intent.get("choice") or intent.get("game") or heard or ""), catalog)
        return self.handle(heard, catalog)

    def _install_named(self, target: str, catalog: Catalog, explicit: bool) -> Step:
        if not catalog.steam_found:
            self.phase = "idle"
            return Step(say="I can't find Steam on this computer, sir.", listen=False, phase="idle")
        installed = rank_games(target, catalog.games)
        if len(installed) == 1 and explicit:
            self._game = installed[0]
            step = self._after_game(catalog, hint=None, named=None)
            if step.say:
                step.say = f"That's already installed, sir. {step.say}"
            return step
        library_matches = self._library_matches(target, catalog)
        if len(library_matches) == 1:
            return self._queue_install(library_matches[0], missing=not explicit)
        if len(library_matches) > 1:
            return self._offer_install(library_matches)
        self._retries += 1
        if self._retries <= 1:
            self.phase = "command"
            return Step(say="I couldn't find that game, sir. Say the name again.", listen=True, phase="command")
        self.phase = "idle"
        return Step(say="I couldn't find that game in your Steam library, sir.", listen=False, phase="idle")

    def _library_matches(self, target: str, catalog: Catalog) -> list[Game]:
        matches = rank_games(target, catalog.library or [])
        if matches:
            return matches
        return rank_games(target, search_uninstalled(target))

    def _offer_install(self, games: list[Game]) -> Step:
        self._games = games
        self.phase = "install"
        self._retries = 0
        return Step(say=game_prompt(games), listen=True, phase="install")

    def _pick_install(self, text: str) -> Step:
        index = parse_ordinal(text)
        if index is None:
            narrowed = rank_games(text, self._games)
            if len(narrowed) == 1:
                return self._queue_install(narrowed[0], missing=False)
            return self._retry("Say first, second, or the game name, sir.")
        if index >= len(self._games):
            return self._retry("That number isn't on the list, sir.")
        return self._queue_install(self._games[index], missing=False)

    def _queue_install(self, game: Game, missing: bool) -> Step:
        self.phase = "idle"
        if missing:
            line = f"{game.name} isn't installed, sir. I'm downloading it."
        else:
            line = f"Installing {game.name}, sir."
        return Step(say=line, listen=False, phase="idle", install=game)

    def _wallpaper_answer(self, text: str) -> Step:
        if _NO.search(text) and not _YES.search(text):
            return self._decline_wallpaper()
        if _YES.search(text):
            return self._accept_wallpaper()
        return self._retry("Say yes or no, sir.")

    def _accept_wallpaper(self) -> Step:
        self.phase = "idle"
        return Step(
            say="Installing the desktop interface, sir.",
            listen=False,
            phase="idle",
            wallpaper="install",
        )

    def _decline_wallpaper(self) -> Step:
        self.phase = "idle"
        return Step(say="Very well, sir.", listen=False, phase="idle", wallpaper="decline")

    def _retry(self, line: str) -> Step:
        self._retries += 1
        if self._retries <= 1:
            return Step(say=line, listen=True, phase=self.phase)
        self.phase = "idle"
        return Step(say="Standing by, sir.", listen=False, phase="idle")
