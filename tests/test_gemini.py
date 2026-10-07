import unittest

from jarvisai.gemini import api_key, parse_intent, store_api_key
from jarvisai.paths import user_data_dir


class ParseIntentTests(unittest.TestCase):
    def test_json_fence_and_exact_game(self):
        raw = '```json\n{"intent":"launch","game":"Portal 2","choice":"first"}\n```'
        intent = parse_intent(raw)
        self.assertEqual(intent["intent"], "launch")
        self.assertEqual(intent["game"], "Portal 2")
        self.assertEqual(intent["choice"], "first")

    def test_spotify_random_flag_is_boolean(self):
        intent = parse_intent('{"intent":"spotify","song":"","artist":"Queen","random":"false"}')
        self.assertEqual(intent["intent"], "spotify")
        self.assertFalse(intent["random"])
        self.assertEqual(intent["artist"], "Queen")

    def test_volume_amount_is_a_percent(self):
        intent = parse_intent('{"intent":"volume_up","amount":"20 percent"}')
        self.assertEqual(intent["intent"], "volume_up")
        self.assertEqual(intent["amount"], 20)
        plain = parse_intent('{"intent":"volume_up","amount":""}')
        self.assertIsNone(plain["amount"])

    def test_settings_store_the_gemini_key_in_the_user_variable(self):
        original = api_key()
        config = user_data_dir() / "config.json"
        before = config.read_text(encoding="utf-8") if config.exists() else ""
        try:
            store_api_key("  test-jarvis-key  ")
            self.assertEqual(api_key(), "test-jarvis-key")
            if config.exists():
                self.assertNotIn("test-jarvis-key", config.read_text(encoding="utf-8"))
        finally:
            store_api_key(original)
        self.assertEqual(api_key(), original)
        if config.exists():
            self.assertEqual(config.read_text(encoding="utf-8"), before)

    def test_unknown_intent_is_kept_safe(self):
        intent = parse_intent('{"intent":"delete-everything","game":"","choice":""}')
        self.assertEqual(intent["intent"], "unknown")
