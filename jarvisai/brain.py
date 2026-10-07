from __future__ import annotations

import random
import re
from dataclasses import dataclass

from jarvisai.steam import Game, Profile

GREETINGS = (
    "What's up, sir?",
    "At your service.",
    "Yes, sir?",
    "How can I help you?",
    "Online and ready.",
    "For you, sir, always.",
    "Standing by.",
    "Right here, sir.",
    "Ready when you are.",
    "Good to hear you, sir.",
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
}

_LAUNCH = re.compile(
    r"\b(?:please\s+)?(?:can you\s+|could you\s+|would you\s+)?"
    r"(?:launch|start|open|run|play|boot|fire up|uruchom|odpal|wlacz|włącz)"
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
_CANCEL = re.compile(r"\b(cancel|never mind|nevermind|stop|abort|forget it|anuluj)\b", re.IGNORECASE)
_WAKE = re.compile(r"\b(?:hey|hi|ok|okay)\s+jarv\w*\b", re.IGNORECASE)


@dataclass
class Catalog:
    steam_found: bool
    games: list[Game]
    profiles: list[Profile]


@dataclass
class Step:
    say: str | None = None
    listen: bool = False
    launch: tuple[Game, Profile] | None = None
    phase: str = "idle"


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

    def begin(self) -> Step:
        self.phase = "command"
        self._retries = 0
        self._games = []
        self._profiles = []
        self._game = None
        self._pending_hint = None
        self._pending_named = None
        return Step(say=random.choice(GREETINGS), listen=True, phase="command")

    def handle(self, text: str | None, catalog: Catalog) -> Step:
        if text is None or not text.strip():
            self._retries += 1
            if self._retries <= 1 and self.phase in {"command", "game", "profile"}:
                return Step(say="I didn't catch that, sir.", listen=True, phase=self.phase)
            self.phase = "idle"
            return Step(say="Standing by, sir.", listen=False, phase="idle")

        if _CANCEL.search(text):
            self.phase = "idle"
            return Step(say="Very well, sir.", listen=False, phase="idle")

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
            self.phase = "idle"
            return Step(
                say=f"I couldn't find {target} in your Steam library, sir.",
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

    def _retry(self, line: str) -> Step:
        self._retries += 1
        if self._retries <= 1:
            return Step(say=line, listen=True, phase=self.phase)
        self.phase = "idle"
        return Step(say="Standing by, sir.", listen=False, phase="idle")
