import inspect
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import bot


class BotDownloadsDirTests(unittest.TestCase):
    def test_downloads_dir_is_absolute_and_points_to_repo_downloads(self):
        expected_dir = (Path(bot.__file__).resolve().parent / "downloads").resolve()
        self.assertTrue(bot.DOWNLOADS_DIR.is_absolute())
        self.assertEqual(bot.DOWNLOADS_DIR.resolve(), expected_dir)

    def test_downloads_dir_is_independent_of_current_working_directory(self):
        original_cwd = os.getcwd()
        with TemporaryDirectory() as temp_dir:
            try:
                os.chdir(temp_dir)
                self.assertNotEqual(Path.cwd(), Path(original_cwd))
                self.assertFalse(str(bot.DOWNLOADS_DIR.resolve()).startswith(temp_dir))
                expected_dir = (Path(bot.__file__).resolve().parent / "downloads").resolve()
                self.assertEqual(bot.DOWNLOADS_DIR.resolve(), expected_dir)
            finally:
                os.chdir(original_cwd)

    def test_choose_quality_uses_downloads_dir(self):
        source = inspect.getsource(bot.choose_quality)
        self.assertIn("DOWNLOADS_DIR", source)
        self.assertNotIn('"downloads"', source)

    def test_choose_audio_format_uses_downloads_dir(self):
        source = inspect.getsource(bot.choose_audio_format)
        self.assertIn("DOWNLOADS_DIR", source)
        self.assertNotIn('"downloads"', source)


if __name__ == "__main__":
    unittest.main()
