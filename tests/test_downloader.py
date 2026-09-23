import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from yt_dlp import YoutubeDL
from yt_dlp.utils import YoutubeDLError

from src.downloader import download_video, get_video_info, get_video_qualities


def video(format_id, height=720, **overrides):
    return {
        "format_id": format_id,
        "url": "https://example.invalid/media",
        "height": height,
        "ext": "mp4",
        "vcodec": "avc1",
        "acodec": "none",
        **overrides,
    }


class VideoQualitiesTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("src.downloader.yt_dlp.YoutubeDL")
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.extract = self.factory.return_value.__enter__.return_value.extract_info

    def qualities(self, formats):
        self.extract.return_value = {"formats": formats}
        return get_video_qualities(" https://example.invalid/watch?v=test ")

    def test_filters_unusable_formats_and_sorts_actual_heights(self):
        results = self.qualities([
            video("low", 432), video("high", 1440), video("middle", 864),
            video("audio", vcodec="none"), video("unknown-codec", vcodec=None),
            video("storyboard", ext="mhtml"), video("storyboard-protocol", protocol="mhtml"),
            video("no-url", url=None), video(None), video("drm", has_drm=True),
            None, {},
        ])
        self.assertEqual([r["height"] for r in results], [1440, 864, 432])
        self.assertEqual([r["resolution"] for r in results], ["1440p", "864p", "432p"])
        self.extract.assert_called_once_with("https://example.invalid/watch?v=test", download=False)
        self.assertTrue(self.factory.call_args.args[0]["noplaylist"])

    def test_deduplication_preserves_meaningful_variants(self):
        results = self.qualities([
            video("duplicate-low", tbr=100), video("duplicate-best", tbr=200),
            video("with-audio", acodec="aac"), video("webm", ext="webm", vcodec="vp9"),
            video("high-fps", fps=60), video("other-codec", vcodec="av01"),
        ])
        self.assertEqual(
            {r["format_id"] for r in results},
            {"duplicate-best", "with-audio", "webm", "high-fps", "other-codec"},
        )
        self.assertEqual(results[0]["format_id"], "high-fps")

    def test_missing_metadata_and_size_normalization(self):
        results = self.qualities([
            video("exact", 1080, filesize=123, filesize_approx=456),
            video("approx", 720, filesize_approx=456),
            video("unknown", None, ext=None, acodec=None),
            video("invalid", "bad", fps=float("nan"), filesize=-1),
        ])
        exact, approx, invalid, unknown = results
        self.assertEqual(exact["filesize"], 123)
        self.assertFalse(exact["filesize_is_approximate"])
        self.assertEqual(approx["filesize"], 456)
        self.assertTrue(approx["filesize_is_approximate"])
        for field in ("height", "fps", "filesize", "filesize_is_approximate"):
            self.assertIsNone(invalid[field])
        for field in ("height", "resolution", "ext", "acodec", "filesize"):
            self.assertIsNone(unknown[field])

    def test_absent_or_malformed_formats(self):
        for formats in (None, [], {}, "invalid"):
            with self.subTest(formats=formats):
                self.assertEqual(self.qualities(formats), [])

    def test_blank_url_does_not_extract(self):
        with self.assertRaises(ValueError):
            get_video_qualities("  ")
        self.factory.assert_not_called()

    def test_extraction_failures(self):
        self.extract.side_effect = YoutubeDLError("mock failure")
        with self.assertRaisesRegex(RuntimeError, "Unable to retrieve video qualities"):
            get_video_qualities("test")

    def test_empty_metadata_and_playlists_are_rejected(self):
        for info in (None, {}, {"_type": "playlist"}, {"entries": []}):
            with self.subTest(info=info):
                self.extract.return_value = info
                with self.assertRaises(RuntimeError):
                    get_video_qualities("test")

    def test_existing_video_info_behavior(self):
        self.extract.return_value = {"title": "Example", "duration": 42, "formats": []}
        self.assertEqual(get_video_info(" test "), {
            "title": "Example", "duration": 42, "thumbnail": None,
            "uploader": None, "webpage_url": None,
        })
        self.extract.assert_called_once_with("test", download=False)


class VideoDownloadTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.filepath = self.directory / "safe [test].mkv"
        patcher = patch("src.downloader.yt_dlp.YoutubeDL")
        self.factory = patcher.start()
        self.addCleanup(patcher.stop)
        self.ydl = self.factory.return_value.__enter__.return_value
        self.ydl.extract_info.return_value = {"id": "test", "title": "Example"}
        self.ydl.process_ie_result.side_effect = self.finish

    def finish(self, info, download):
        self.assertTrue(download)
        if not self.filepath.exists():
            self.filepath.write_bytes(b"mock media")
        recorder = self.ydl.add_post_processor.call_args.args[0]
        recorder.run({**info, "filepath": str(self.filepath), "height": 480,
                      "ext": self.filepath.suffix[1:]})
        # Extraction results can retain stale pre-merge filenames.
        return {**info, "_filename": "stale.mp4"}

    def test_download_options_and_final_merged_path(self):
        result = download_video(" test ", 720, self.directory)
        options = self.factory.call_args.args[0]
        self.assertEqual(options["format"], "bv[height<=720]+ba/b[height<=720]")
        self.assertEqual(options["merge_output_format"], "mp4/mkv")
        self.assertEqual(options["format_sort"], ["res", "vcodec:h264", "acodec:aac"])
        self.assertEqual(options["js_runtimes"], {"node": {"path": "/usr/bin/node"}})
        self.assertTrue(options["noplaylist"])
        self.assertFalse(options["overwrites"])
        self.assertTrue(options["restrictfilenames"])
        self.assertTrue(options["windowsfilenames"])
        self.assertIn("%(id)s", options["outtmpl"])
        self.assertIn("max-720p", options["outtmpl"])
        self.assertEqual(options["paths"]["home"], str(self.directory))
        self.ydl.extract_info.assert_called_once_with("test", download=False, process=False)
        self.assertEqual(self.ydl.add_post_processor.call_args.kwargs, {"when": "after_move"})
        self.assertEqual(result, {"filepath": str(self.filepath), "id": "test",
                                 "title": "Example", "height": 480,
                                 "requested_height": 720, "ext": "mkv"})

    def test_existing_completed_file_and_single_stream_mp4(self):
        self.filepath = self.directory / "existing.mp4"
        self.filepath.write_bytes(b"existing download")
        result = download_video("test", 1080, self.directory)
        self.assertEqual(result["filepath"], str(self.filepath))
        self.assertEqual(self.filepath.read_bytes(), b"existing download")
        self.assertIn("height<=1080", self.factory.call_args.args[0]["format"])

    def test_creates_output_directory(self):
        destination = self.directory / "new" / "nested"
        self.filepath = destination / "video.mp4"
        download_video("test", 720, destination)
        self.assertTrue(destination.is_dir())

    def test_invalid_inputs_do_not_extract(self):
        for url in ("", "  ", None, 123):
            with self.subTest(url=url), self.assertRaises(ValueError):
                download_video(url, 720, self.directory)
        for height in (0, -1, True, None, "720", 720.0, float("nan")):
            with self.subTest(height=height), self.assertRaises(ValueError):
                download_video("test", height, self.directory)
        self.filepath.touch()
        for directory in (None, "", "  ", 123, b"bytes", "bad\x00path", self.filepath):
            with self.subTest(directory=directory), self.assertRaises(ValueError):
                download_video("test", 720, directory)
        self.factory.assert_not_called()

    def test_extraction_and_download_failures(self):
        for method in (self.ydl.extract_info, self.ydl.process_ie_result):
            original = method.side_effect
            for error in (YoutubeDLError("mock failure"), OSError("disk failure")):
                method.side_effect = error
                with self.assertRaisesRegex(RuntimeError, "Unable to download video"):
                    download_video("test", 720, self.directory)
            method.side_effect = original

    def test_playlist_and_empty_metadata_never_download(self):
        for info in (None, {}, {"_type": "playlist"}, {"entries": []},
                     {"_type": "multi_video"}):
            self.ydl.extract_info.return_value = info
            with self.subTest(info=info), self.assertRaises(RuntimeError):
                download_video("test", 720, self.directory)
        self.ydl.process_ie_result.assert_not_called()

    def test_missing_final_path_or_file_is_an_error(self):
        self.ydl.process_ie_result.side_effect = None
        with self.assertRaisesRegex(RuntimeError, "completed output file path"):
            download_video("test", 720, self.directory)

        def missing_file(info, download):
            recorder = self.ydl.add_post_processor.call_args.args[0]
            recorder.run({"filepath": str(self.directory / "missing.mp4")})

        self.ydl.process_ie_result.side_effect = missing_file
        with self.assertRaisesRegex(RuntimeError, "could not be found"):
            download_video("test", 720, self.directory)

    def test_directory_creation_failure(self):
        with patch("src.downloader.Path.mkdir", side_effect=PermissionError("denied")):
            with self.assertRaisesRegex(RuntimeError, "Unable to download video"):
                download_video("test", 720, self.directory)
        self.factory.assert_not_called()

    def test_real_selector_with_synthetic_formats_never_exceeds_cap(self):
        download_video("test", 720, self.directory)
        options = self.factory.call_args.args[0]
        audio = video("audio", None, vcodec="none", acodec="mp4a.40.2", ext="m4a")
        cases = [
            ([audio, video("low", 480), video("high", 1080)], "low+audio"),
            ([video("combined", 360, acodec="mp4a.40.2"),
              video("too-high", 1080, acodec="mp4a.40.2")], "combined"),
            ([audio, video("unknown", None), video("too-high", 1080)], None),
            ([video("opus", None, ext="webm", vcodec="none", acodec="opus"),
              video("vp9", 720, ext="webm", vcodec="vp9")], "vp9+opus"),
        ]
        # Only evaluate yt-dlp's selector against local metadata; no extraction
        # or network/media download occurs in this check.
        with YoutubeDL(options) as ydl:
            selector = ydl.build_format_selector(options["format"])
            for formats, expected in cases:
                with self.subTest(expected=expected):
                    selected = list(selector({"formats": formats,
                                              "has_merged_format": False,
                                              "incomplete_formats": False}))
                    self.assertEqual([f["format_id"] for f in selected],
                                     [expected] if expected else [])
                    for item in selected:
                        self.assertLessEqual(item["height"], 720)
                        if expected == "vp9+opus":
                            self.assertEqual(item["ext"], "mkv")


if __name__ == "__main__":
    unittest.main()
