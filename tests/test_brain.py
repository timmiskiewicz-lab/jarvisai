import unittest

from jarvisai.brain import (
    Brain,
    Catalog,
    GREETINGS,
    addresses_jarvis,
    choose_transcript,
    extract_launch_target,
    extract_spotify,
    extract_volume,
    is_wake_only,
    rank_games,
    score_name,
)
from jarvisai.ears import phrase_is_complete
from jarvisai.steam import Game, Profile, needs_account_switch

GAMES = [
    Game("65540", "Gothic 1"),
    Game("39510", "Gothic II: Gold Edition"),
    Game("39500", "Gothic 3"),
    Game("620", "Portal 2"),
]
PROFILES = [
    Profile("alpha", "Alpha", True, True),
    Profile("beta", "Beta", False, True),
]


def catalog(profiles=None, steam_found=True, library=None) -> Catalog:
    return Catalog(steam_found, GAMES, PROFILES if profiles is None else profiles, library or [])


class MatchingTests(unittest.TestCase):
    def test_gothic_one_is_exact(self):
        names = [game.name for game in rank_games("gothic 1", GAMES)]
        self.assertEqual(names, ["Gothic 1"])

    def test_spoken_number_and_roman_numeral(self):
        self.assertEqual(rank_games("gothic one", GAMES)[0].name, "Gothic 1")
        self.assertEqual(rank_games("gothic ii", GAMES)[0].name, "Gothic II: Gold Edition")

    def test_number_conflict_is_rejected(self):
        self.assertLess(score_name("gothic 1", "Gothic II: Gold Edition"), 0.5)
        self.assertLess(score_name("gothic 1", "Gothic 3"), 0.5)

    def test_plain_gothic_is_ambiguous(self):
        names = [game.name for game in rank_games("gothic", GAMES)]
        self.assertGreaterEqual(len(names), 3)


class ConversationTests(unittest.TestCase):
    def test_greeting_is_one_of_the_jarvis_lines(self):
        brain = Brain()
        brain.begin()
        step = brain.handle("Play Jarvis", catalog())
        self.assertIn(step.say, GREETINGS)
        self.assertTrue(step.listen)
        self.assertIsNone(step.launch)

    def test_hey_jarvis_is_not_a_steam_search(self):
        brain = Brain()
        brain.begin()
        for phrase in ("Hey Jarvis", "play jarvis", "ok jarvis", "Jarvis"):
            step = brain.handle(phrase, catalog())
            self.assertIsNone(step.launch)
            self.assertNotIn("couldn't find", (step.say or "").lower())

    def test_bare_jarvis_still_counts_as_the_wake_word(self):
        self.assertTrue(is_wake_only("Jarvis"))
        self.assertTrue(addresses_jarvis("Jarvis"))
        self.assertTrue(addresses_jarvis("Hey Jarvis, turn this up"))
        self.assertFalse(addresses_jarvis("turn this up"))
        self.assertFalse(addresses_jarvis("I saw jarvis yesterday"))
        self.assertEqual(extract_launch_target("Jarvis launch gothic 1"), "gothic 1")

    def test_he_waits_through_a_short_pause(self):
        self.assertFalse(phrase_is_complete(800, 2000))
        self.assertFalse(phrase_is_complete(1400, 200))
        self.assertTrue(phrase_is_complete(1400, 500))
        self.assertTrue(phrase_is_complete(0, 5500))

    def test_wallpaper_yes_and_no(self):
        brain = Brain()
        brain.begin()
        brain.phase = "wallpaper"
        yes = brain.handle("tak, zainstaluj", catalog())
        self.assertEqual(yes.wallpaper, "install")
        brain.phase = "wallpaper"
        no = brain.handle("nie", catalog())
        self.assertEqual(no.wallpaper, "decline")

    def test_gemini_launch_uses_the_named_game(self):
        brain = Brain()
        brain.begin()
        one = catalog(profiles=[PROFILES[0]])
        step = brain.apply({"intent": "launch", "game": "Portal 2", "choice": ""}, one, "odpal to")
        self.assertIsNotNone(step.launch)
        self.assertEqual(step.launch[0].name, "Portal 2")

    def test_installs_a_library_game_and_reports_the_clock(self):
        from datetime import datetime

        from jarvisai.steam import finish_clock

        library = [Game("1", "Hollow Knight", False)]
        brain = Brain()
        brain.begin()
        step = brain.handle("zainstaluj hollow knight", catalog(library=library))
        self.assertIsNotNone(step.install)
        self.assertEqual(step.install.name, "Hollow Knight")
        when = finish_clock(
            [(0.0, 0, 8_000_000), (2.0, 200_000, 8_000_000)],
            datetime(2026, 10, 7, 18, 0, 0),
        )
        self.assertEqual(when, "18:01")

    def test_launch_of_an_uninstalled_game_starts_a_download(self):
        library = [Game("1", "Hollow Knight", False)]
        brain = Brain()
        brain.begin()
        step = brain.handle("odpal hollow knight", catalog(library=library))
        self.assertIsNotNone(step.install)
        self.assertEqual(step.install.name, "Hollow Knight")
        self.assertIn("downloading", (step.say or "").lower())

    def test_can_you_launch_survives_a_misheard_verb(self):
        games = GAMES + [Game("361420", "ASTRONEER")]
        library = Catalog(True, games, [PROFILES[0]])
        brain = Brain()
        brain.begin()
        step = brain.handle("Can you want astroneer please", library)
        self.assertIsNotNone(step.launch)
        self.assertEqual(step.launch[0].name, "ASTRONEER")
        chosen = choose_transcript(
            [
                "Can you want astroneer please",
                "can you launch Australia please",
                "can you launch astronauts please",
            ],
            library,
        )
        self.assertIn("astroneer", chosen.lower())

    def test_transcript_prefers_the_installed_game(self):
        self.assertTrue(is_wake_only("Play Jarvis"))
        self.assertFalse(is_wake_only("odpal gothic 1"))
        chosen = choose_transcript(
            ["John Gotti classic", "odpal Gothic 1", "Play Jarvis"],
            catalog(),
        )
        self.assertIn("Gothic 1", chosen)

    def test_two_profiles_are_offered_in_order(self):
        brain = Brain()
        brain.begin()
        step = brain.handle("launch gothic 1", catalog())
        self.assertEqual(step.phase, "profile")
        self.assertIn("Which profile do you want me to launch", step.say)
        self.assertIn("First, Alpha", step.say)
        self.assertIn("Second, Beta", step.say)
        step = brain.handle("second", catalog())
        self.assertEqual(step.launch[0].appid, "65540")
        self.assertEqual(step.launch[1].persona_name, "Beta")
        self.assertIn("Beta", step.say)

    def test_first_and_profile_name(self):
        brain = Brain()
        brain.begin()
        brain.handle("play gothic one", catalog())
        step = brain.handle("the first one", catalog())
        self.assertEqual(step.launch[1].account_name, "alpha")

        brain = Brain()
        brain.begin()
        step = brain.handle("launch portal 2", catalog())
        step = brain.handle("beta", catalog())
        self.assertEqual(step.launch[0].name, "Portal 2")
        self.assertEqual(step.launch[1].persona_name, "Beta")

    def test_single_profile_skips_the_question(self):
        brain = Brain()
        brain.begin()
        step = brain.handle("please launch gothic 1", catalog(profiles=[PROFILES[0]]))
        self.assertEqual(step.phase, "idle")
        self.assertEqual(step.launch[0].name, "Gothic 1")
        self.assertNotIn("Which profile", step.say)

    def test_inline_profile(self):
        brain = Brain()
        brain.begin()
        step = brain.handle("launch portal 2 on the second profile", catalog())
        self.assertEqual(step.launch[0].appid, "620")
        self.assertEqual(step.launch[1].persona_name, "Beta")

    def test_ambiguous_game_then_profile(self):
        brain = Brain()
        brain.begin()
        step = brain.handle("launch gothic", catalog())
        self.assertEqual(step.phase, "game")
        self.assertIn("First, Gothic 1", step.say)
        step = brain.handle("second", catalog())
        self.assertEqual(step.phase, "profile")
        self.assertEqual(brain._game.name, "Gothic II: Gold Edition")
        step = brain.handle("first", catalog())
        self.assertEqual(step.launch[0].name, "Gothic II: Gold Edition")
        self.assertEqual(step.launch[1].persona_name, "Alpha")

    def test_missing_game_and_cancel(self):
        brain = Brain()
        brain.begin()
        step = brain.handle("launch minecraft", catalog())
        self.assertIn("couldn't find", step.say.lower())
        brain.begin()
        brain.handle("launch gothic", catalog())
        step = brain.handle("cancel", catalog())
        self.assertEqual(step.phase, "idle")
        self.assertIn("Very well", step.say)

    def test_switch_only_when_the_account_differs(self):
        self.assertFalse(needs_account_switch(PROFILES[0], "alpha"))
        self.assertTrue(needs_account_switch(PROFILES[1], "alpha"))


class VdfTests(unittest.TestCase):
    def test_library_and_users(self):
        from jarvisai.vdf import parse_vdf

        library = parse_vdf(
            '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"C:\\\\Program Files (x86)\\\\Steam"\n\t}\n}\n'
        )
        self.assertEqual(
            library["libraryfolders"]["0"]["path"],
            "C:\\Program Files (x86)\\Steam",
        )
        users = parse_vdf(
            """
            "users"
            {
                "1"
                {
                    "AccountName" "alpha"
                    "PersonaName" "Alpha"
                    "RememberPassword" "1"
                    "AutoLogin" "1"
                }
            }
            """
        )
        self.assertEqual(users["users"]["1"]["PersonaName"], "Alpha")


class VolumeCommandTests(unittest.TestCase):
    def test_turn_this_up_is_immediate(self):
        self.assertEqual(extract_volume("Jarvis turn this up"), 10)
        self.assertEqual(extract_volume("Jarvis turn this up by 25 percent"), 25)
        self.assertEqual(extract_volume("turn this up by 25%"), 25)
        self.assertEqual(extract_volume("turn this up by twenty five percent"), 25)
        self.assertEqual(extract_volume("podgłośnij o 30 procent"), 30)
        self.assertEqual(extract_volume("hey jarvis, can you turn it up"), 10)
        self.assertEqual(extract_volume("głośniej"), 10)
        self.assertIsNone(extract_volume("play gothic 1"))
        brain = Brain()
        brain.begin()
        step = brain.handle("Jarvis, turn this up", catalog())
        self.assertEqual(step.volume, 10)
        by_number = brain.handle("Jarvis turn this up by 40 percent", catalog())
        self.assertEqual(by_number.volume, 40)
        self.assertFalse(by_number.listen)
        self.assertFalse(step.listen)
        self.assertIsNone(step.launch)


class SpotifyCommandTests(unittest.TestCase):
    def test_play_by_artist_is_a_song(self):
        ask = extract_spotify("can you play bohemian rhapsody by queen please")
        self.assertEqual(ask.title, "bohemian rhapsody")
        self.assertEqual(ask.artist, "queen")
        brain = Brain()
        brain.begin()
        step = brain.handle("play bohemian rhapsody by queen", catalog())
        self.assertIsNotNone(step.spotify)
        self.assertIsNone(step.launch)

    def test_random_song_and_polish(self):
        ask = extract_spotify("play random song by queen")
        self.assertIsNone(ask.title)
        self.assertEqual(ask.artist, "queen")
        polish = extract_spotify("odtwórz losową piosenkę zespołu queen")
        self.assertIsNone(polish.title)
        self.assertEqual(polish.artist, "queen")

    def test_a_game_is_not_a_song(self):
        self.assertIsNone(extract_spotify("play gothic 1"))
        brain = Brain()
        brain.begin()
        step = brain.handle("play gothic 1", catalog(profiles=[PROFILES[0]]))
        self.assertEqual(step.launch[0].name, "Gothic 1")


if __name__ == "__main__":
    unittest.main()
