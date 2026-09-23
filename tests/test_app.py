import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"
URL = "https://www.youtube.com/watch?v=abcdefghijk"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.mocks = {}
        for name in ("get_video_info", "get_video_qualities", "download_video"):
            patcher = patch(f"src.downloader.{name}")
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.info = self.mocks["get_video_info"]
        self.qualities = self.mocks["get_video_qualities"]
        self.download = self.mocks["download_video"]
        self.info.return_value = {
            "title": "Example video", "uploader": "Example uploader",
            "duration": 93, "thumbnail": "https://example.invalid/thumb.jpg",
        }
        self.qualities.return_value = [
            {"height": 720}, {"height": 360}, {"height": 720.0}, {"height": None},
        ]
        self.app = AppTest.from_file(str(APP)).run()

    def load(self):
        self.app.text_input[0].set_value(URL)
        self.app.button[0].click().run()
        self.assertFalse(self.app.exception)

    def test_metadata_unique_labels_and_selection_survive_reruns(self):
        self.load()
        self.assertEqual(self.app.selectbox[0].options, ["720p", "360p"])
        self.app.selectbox[0].select(360).run()
        self.assertEqual(self.app.subheader[0].value, "Example video")
        self.assertEqual(self.app.image[0].value, ["https://example.invalid/thumb.jpg"])
        text = " ".join(item.value for item in self.app.markdown)
        self.assertIn("Example uploader", text)
        self.assertIn("01:33", text)
        self.info.assert_called_once_with(URL)
        self.qualities.assert_called_once_with(URL)
        self.download.assert_not_called()

    def test_download_and_browser_button_persist_without_redownloading(self):
        with TemporaryDirectory() as directory:
            filepath = Path(directory) / "example.mkv"
            filepath.write_bytes(b"mock completed file")
            self.download.return_value = {
                "filepath": str(filepath), "height": 240,
                "requested_height": 360, "ext": "mkv",
            }
            self.load()
            self.app.selectbox[0].select(360).run()
            self.app.button[1].click().run()
            self.assertFalse(self.app.exception)
            self.download.assert_called_once_with(URL, 360, APP.parent / "downloads")
            self.assertIn("successfully", self.app.success[0].value)
            button = self.app.get("download_button")[0]
            self.assertEqual(button.label, "Save video to your device")
            text = " ".join(item.value for item in self.app.markdown)
            for value in ("example.mkv", "240p", "MiB"):
                self.assertIn(value, text)
            self.app.run()
            self.assertEqual(len(self.app.get("download_button")), 1)
            self.download.assert_called_once()
            self.app.selectbox[0].select(720).run()
            self.assertEqual(len(self.app.get("download_button")), 0)

    def test_url_change_clears_old_metadata_and_controls(self):
        self.load()
        self.app.text_input[0].set_value("https://youtu.be/12345678901").run()
        self.assertEqual(len(self.app.subheader), 0)
        self.assertEqual(len(self.app.selectbox), 0)
        self.assertEqual(len(self.app.button), 1)

    def test_no_known_heights(self):
        self.qualities.return_value = [{"height": None}]
        self.load()
        self.assertEqual(len(self.app.selectbox), 0)
        self.assertIn("No video qualities", self.app.info[0].value)
        self.download.assert_not_called()

    def test_backend_errors_are_displayed(self):
        for name in ("get_video_info", "get_video_qualities", "download_video"):
            for error in (ValueError("Please check your input."),
                          RuntimeError("Service unavailable. Please try again.")):
                with self.subTest(name=name, error=type(error)):
                    self.mocks[name].side_effect = error
                    self.load()
                    if name == "download_video":
                        self.app.button[1].click().run()
                    self.assertFalse(self.app.exception)
                    self.assertEqual(self.app.error[0].value, str(error))
                    if name == "get_video_qualities":
                        self.assertEqual(self.app.subheader[0].value, "Example video")
                    self.mocks[name].side_effect = None

    def test_missing_download_file_is_friendly_error(self):
        self.download.return_value = {
            "filepath": "/nonexistent/mock-video.mp4", "requested_height": 720,
        }
        self.load()
        self.app.button[1].click().run()
        self.assertFalse(self.app.exception)
        self.assertIn("could not be read", self.app.error[0].value)
        self.assertEqual(len(self.app.success), 0)

    def test_invalid_url_never_calls_backend(self):
        self.app.text_input[0].set_value("invalid")
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.error), 1)
        for mock in self.mocks.values():
            mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
