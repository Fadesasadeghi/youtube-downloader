import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / "app.py"
URL = "https://www.youtube.com/watch?v=abcdefghijk"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.mocks = {}
        for name in ("get_video_info", "get_video_qualities", "download_video", "download_audio"):
            patcher = patch(f"src.downloader.{name}")
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)
        self.info = self.mocks["get_video_info"]
        self.qualities = self.mocks["get_video_qualities"]
        self.download = self.mocks["download_video"]
        self.audio = self.mocks["download_audio"]
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
        self.assertEqual(self.app.selectbox(key="quality").options, ["720p", "360p"])
        self.app.selectbox(key="quality").select(360).run()
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
            self.app.selectbox(key="quality").select(360).run()
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
            self.app.selectbox(key="quality").select(720).run()
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
        self.assertEqual(len(self.app.selectbox), 1)
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

    def select_audio(self):
        self.app.selectbox(key="download_type").select("Audio").run()
        self.assertFalse(self.app.exception)

    def audio_result(self, directory, audio_format="mp3"):
        filepath = Path(directory) / f"example.{audio_format}"
        filepath.write_bytes(b"mock audio")
        self.audio.return_value = {
            "filepath": str(filepath), "audio_format": audio_format, "ext": audio_format,
        }
        return filepath

    def test_mode_controls_and_defaults(self):
        self.load()
        mode = self.app.selectbox(key="download_type")
        self.assertEqual(mode.options, ["Video", "Audio"])
        self.assertEqual(mode.value, "Video")
        self.assertEqual(self.app.selectbox(key="quality").options, ["720p", "360p"])
        self.select_audio()
        self.assertEqual([box.label for box in self.app.selectbox],
                         ["Download type", "Audio format"])
        audio_format = self.app.selectbox(key="audio_format")
        self.assertEqual(audio_format.options, ["MP3", "M4A"])
        self.assertEqual(audio_format.value, "MP3")
        self.assertEqual(self.app.button[1].label, "Download Audio")

    def test_audio_download_arguments_mime_and_browser_rerun(self):
        for audio_format, mime in (("mp3", "audio/mpeg"), ("m4a", "audio/mp4")):
            with self.subTest(audio_format=audio_format), TemporaryDirectory() as directory:
                self.audio.reset_mock()
                filepath = self.audio_result(directory, audio_format)
                self.load()
                self.select_audio()
                self.app.selectbox(key="audio_format").select(audio_format.upper()).run()
                with patch("streamlit.download_button", wraps=st.download_button) as save:
                    self.app.button[1].click().run()
                    self.assertEqual(save.call_args.kwargs["mime"], mime)
                    self.assertEqual(save.call_args.kwargs["file_name"], filepath.name)
                self.assertFalse(self.app.exception)
                self.audio.assert_called_once_with(URL, APP.parent / "downloads", audio_format)
                self.download.assert_not_called()
                self.assertEqual(self.app.success[0].value, "Audio downloaded successfully!")
                text = " ".join(item.value for item in self.app.markdown)
                for value in (filepath.name, "0.00 MiB", audio_format.upper()):
                    self.assertIn(value, text)
                button = self.app.get("download_button")[0]
                self.assertEqual(button.label, "Save audio to your device")
                # AppTest exposes download buttons as UnknownElement. Send the
                # browser's trigger state explicitly to exercise its rerun.
                states = self.app._tree.get_widget_states()
                states.widgets.add(id=button.proto.id, trigger_value=True)
                self.app._run(states)
                self.assertFalse(self.app.exception)
                self.assertEqual(len(self.app.get("download_button")), 1)
                self.assertEqual(self.app.subheader[0].value, "Example video")
                self.audio.assert_called_once()

    def test_mode_switches_clear_completed_files(self):
        with TemporaryDirectory() as directory:
            filepath = self.audio_result(directory)
            self.download.return_value = {
                "filepath": str(filepath.with_suffix(".mp4")),
                "height": 720, "requested_height": 720,
            }
            filepath.with_suffix(".mp4").write_bytes(b"mock video")
            self.load()
            self.app.button[1].click().run()
            self.assertEqual(len(self.app.get("download_button")), 1)
            self.select_audio()
            self.assertEqual(len(self.app.get("download_button")), 0)
            self.app.button[1].click().run()
            self.assertEqual(len(self.app.get("download_button")), 1)
            self.app.selectbox(key="download_type").select("Video").run()
            self.assertEqual(len(self.app.get("download_button")), 0)
            self.select_audio()
            self.assertEqual(len(self.app.get("download_button")), 0)

    def test_audio_format_change_clears_completed_file(self):
        with TemporaryDirectory() as directory:
            self.audio_result(directory)
            self.load()
            self.select_audio()
            self.app.button[1].click().run()
            self.app.selectbox(key="audio_format").select("M4A").run()
            self.assertEqual(len(self.app.get("download_button")), 0)
            self.assertEqual(len(self.app.success), 0)
            self.audio.assert_called_once()

    def test_url_change_resets_audio_result_and_selectors(self):
        with TemporaryDirectory() as directory:
            self.audio_result(directory, "m4a")
            self.load()
            self.select_audio()
            self.app.selectbox(key="audio_format").select("M4A").run()
            self.app.button[1].click().run()
            self.app.text_input[0].set_value("https://youtu.be/12345678901").run()
            self.assertEqual(len(self.app.get("download_button")), 0)
            self.assertEqual(len(self.app.selectbox), 0)
            self.assertEqual(len(self.app.subheader), 0)
            for key in ("completed_download", "quality", "audio_format", "download_type"):
                self.assertNotIn(key, self.app.session_state)
            self.app.button[0].click().run()
            self.assertEqual(self.app.selectbox(key="download_type").value, "Video")
            self.select_audio()
            self.assertEqual(self.app.selectbox(key="audio_format").value, "MP3")

    def test_audio_without_video_qualities(self):
        with TemporaryDirectory() as directory:
            self.audio_result(directory)
            self.qualities.return_value = []
            self.load()
            self.assertIn("No video qualities", self.app.info[0].value)
            self.select_audio()
            self.app.button[1].click().run()
            self.assertFalse(self.app.exception)
            self.assertEqual(len(self.app.success), 1)
            self.audio.assert_called_once_with(URL, APP.parent / "downloads", "mp3")

    def test_audio_backend_errors(self):
        for error in (ValueError("Invalid input"), RuntimeError("Download failed"),
                      Exception("unexpected internal details")):
            with self.subTest(error=type(error)):
                self.audio.side_effect = error
                self.load()
                self.select_audio()
                self.app.button[1].click().run()
                self.assertFalse(self.app.exception)
                expected = (str(error) if isinstance(error, (ValueError, RuntimeError))
                            else "Unable to download the audio. Please try again.")
                self.assertEqual(self.app.error[0].value, expected)
                self.assertEqual(len(self.app.get("download_button")), 0)

    def test_unexpected_video_and_metadata_errors(self):
        for name in ("get_video_info", "get_video_qualities", "download_video"):
            with self.subTest(name=name):
                self.mocks[name].side_effect = Exception("internal details")
                self.load()
                if name == "download_video":
                    self.app.button[1].click().run()
                self.assertFalse(self.app.exception)
                self.assertIn("Please try again", self.app.error[0].value)
                self.assertNotIn("internal details", self.app.error[0].value)
                self.mocks[name].side_effect = None

    def test_missing_completed_audio_file(self):
        with TemporaryDirectory() as directory:
            filepath = self.audio_result(directory)
            self.load()
            self.select_audio()
            self.app.button[1].click().run()
            filepath.unlink()
            self.app.run()
            self.assertFalse(self.app.exception)
            self.assertIn("could not be read", self.app.error[0].value)
            self.assertEqual(len(self.app.success), 0)
            self.assertEqual(len(self.app.get("download_button")), 0)
            self.assertNotIn("completed_download", self.app.session_state)
            self.audio.assert_called_once()

    def test_invalid_url_never_calls_backend(self):
        self.app.text_input[0].set_value("invalid")
        self.app.button[0].click().run()
        self.assertEqual(len(self.app.error), 1)
        for mock in self.mocks.values():
            mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
