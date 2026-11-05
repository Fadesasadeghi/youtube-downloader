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


class BotUrlValidationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.update = MagicMock()
        self.context = MagicMock()
        self.context.user_data = {}

    async def test_handle_url_valid_youtube_urls(self):
        valid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        ]
        for url in valid_urls:
            with self.subTest(url=url):
                self.context.user_data.clear()
                self.update.message.text = url
                self.update.message.reply_text = AsyncMock()

                await bot.handle_url(self.update, self.context)

                self.assertEqual(self.context.user_data.get("youtube_url"), url)
                self.update.message.reply_text.assert_called_once()
                args, kwargs = self.update.message.reply_text.call_args
                self.assertIn("لینک دریافت شد", args[0])
                self.assertIn("reply_markup", kwargs)

    async def test_handle_url_rejects_empty_or_whitespace(self):
        for text in ("", "   ", None):
            with self.subTest(text=text):
                self.context.user_data.clear()
                self.update.message.text = text
                self.update.message.reply_text = AsyncMock()

                await bot.handle_url(self.update, self.context)

                self.assertNotIn("youtube_url", self.context.user_data)
                self.update.message.reply_text.assert_called_once()
                args, _ = self.update.message.reply_text.call_args
                self.assertIn("غیرخالی", args[0])

    async def test_handle_url_rejects_missing_scheme(self):
        self.update.message.text = "www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.update.message.reply_text = AsyncMock()

        await bot.handle_url(self.update, self.context)

        self.assertNotIn("youtube_url", self.context.user_data)
        args, _ = self.update.message.reply_text.call_args
        self.assertIn("https://", args[0])

    async def test_handle_url_rejects_playlists_and_unsupported_urls(self):
        unsupported = [
            "https://www.youtube.com/playlist?list=PL12345",
            "https://www.youtube.com/@username",
            "https://vimeo.com/12345678901",
            "https://youtu.be/invalid_short",
            "random text not a url",
        ]
        for text in unsupported:
            with self.subTest(text=text):
                self.context.user_data.clear()
                self.update.message.text = text
                self.update.message.reply_text = AsyncMock()

                await bot.handle_url(self.update, self.context)

                self.assertNotIn("youtube_url", self.context.user_data)
                args, _ = self.update.message.reply_text.call_args
                self.assertIn("نامعتبر", args[0])

    async def test_choose_type_rejects_empty_or_invalid_stored_url(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "video"
        self.update.callback_query = query

        # Case 1: Missing URL
        self.context.user_data = {}
        await bot.choose_type(self.update, self.context)
        query.edit_message_text.assert_called_with("لینک YouTube پیدا نشد. لطفاً دوباره لینک رو بفرست.")

        # Case 2: Invalid stored URL
        self.context.user_data = {"youtube_url": "https://vimeo.com/123"}
        await bot.choose_type(self.update, self.context)
        query.edit_message_text.assert_called_with("❌ لینک ذخیره‌شده نامعتبر است. لطفاً دوباره یک لینک معتبر YouTube بفرستید.")
        self.assertNotIn("youtube_url", self.context.user_data)

    async def test_choose_quality_rejects_invalid_url_before_download(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "quality:720"
        self.update.callback_query = query

        self.context.user_data = {"youtube_url": "invalid_url"}
        with patch("bot.download_video") as mock_download:
            await bot.choose_quality(self.update, self.context)
            mock_download.assert_not_called()

        query.edit_message_text.assert_called_with("❌ لینک ذخیره‌شده نامعتبر است. لطفاً دوباره یک لینک معتبر YouTube بفرستید.")
        self.assertNotIn("youtube_url", self.context.user_data)

    async def test_choose_audio_format_rejects_invalid_url_before_download(self):
        query = MagicMock()
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.data = "audio:mp3"
        self.update.callback_query = query

        self.context.user_data = {"youtube_url": "invalid_url"}
        with patch("bot.download_audio") as mock_download:
            await bot.choose_audio_format(self.update, self.context)
            mock_download.assert_not_called()

        query.edit_message_text.assert_called_with("❌ لینک ذخیره‌شده نامعتبر است. لطفاً دوباره یک لینک معتبر YouTube بفرستید.")
        self.assertNotIn("youtube_url", self.context.user_data)


if __name__ == "__main__":
    unittest.main()
