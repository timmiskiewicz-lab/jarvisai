import unittest

from jarvisai.spotify import choose_track, spotify_id_from_relations
from jarvisai.volume import next_level


class ChooseTrackTests(unittest.TestCase):
    def test_named_song_prefers_the_artist(self):
        results = [
            {"trackName": "Bohemian Rhapsody", "artistName": "Queen"},
            {"trackName": "Bohemian Rhapsody", "artistName": "Somebody Else"},
        ]
        self.assertEqual(choose_track(results, "Queen", "Bohemian Rhapsody"), ("Bohemian Rhapsody", "Queen"))

    def test_random_uses_the_picker(self):
        results = [
            {"trackName": "We Will Rock You", "artistName": "Queen"},
            {"trackName": "Another One Bites the Dust", "artistName": "Queen"},
        ]
        chosen = choose_track(results, "Queen", None, picker=lambda songs: songs[-1])
        self.assertEqual(chosen, ("Another One Bites the Dust", "Queen"))

    def test_volume_step_stops_at_full(self):
        self.assertEqual(next_level(40, 10), 50)
        self.assertEqual(next_level(95, 10), 100)
        self.assertIsNone(next_level(100, 10))

    def test_spotify_id_comes_from_the_track_link(self):
        recordings = [
            {"relations": [{"url": {"resource": "https://musicbrainz.org/recording/1"}}]},
            {"relations": [{"url": {"resource": "https://open.spotify.com/track/60a0Rd6pjrkxjPbaKzXjfq"}}]},
        ]
        self.assertEqual(spotify_id_from_relations(recordings), "60a0Rd6pjrkxjPbaKzXjfq")
