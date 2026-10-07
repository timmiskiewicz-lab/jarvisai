import tempfile
import unittest
from pathlib import Path

from jarvisai.wallpaper import copy_project


class WallpaperCopyTests(unittest.TestCase):
    def test_project_is_copied_intact(self):
        with tempfile.TemporaryDirectory() as source_name, tempfile.TemporaryDirectory() as dest_name:
            source = Path(source_name) / "jarvis"
            source.mkdir()
            (source / "project.json").write_text('{"title":"J.A.R.V.I.S."}', encoding="utf-8")
            (source / "index.html").write_text("<html></html>", encoding="utf-8")
            destination = Path(dest_name) / "myprojects" / "jarvisai"
            copy_project(source, destination)
            self.assertEqual((destination / "project.json").read_text(encoding="utf-8"), '{"title":"J.A.R.V.I.S."}')
            self.assertTrue((destination / "index.html").exists())
