import unittest
from unittest.mock import patch

from yt_dlp.utils import YoutubeDLError

from src.downloader import get_video_info, get_video_qualities


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


if __name__ == "__main__":
    unittest.main()
