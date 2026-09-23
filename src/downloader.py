from math import isfinite
from os import PathLike, fspath
from pathlib import Path

import yt_dlp
from yt_dlp.postprocessor import PostProcessor
from yt_dlp.utils import YoutubeDLError


class _CompletedDownload(PostProcessor):
    """Capture the actual output after merging and moving have finished."""

    def __init__(self):
        super().__init__()
        self.info = None

    def run(self, info):
        self.info = dict(info)
        return [], info


def download_video(url: str, height: int, output_dir: str | PathLike) -> dict:
    """Download one video with a strict maximum height (a positive integer).

    Creates output_dir when needed. Returns filepath (an absolute string), id,
    title, height (actual), requested_height, and ext. Existing completed files
    are reused. yt-dlp generates filenames including video ID and quality cap.

    Prefer H.264/AAC at comparable resolution and MP4 when compatible; other
    codecs and MKV remain available without transcoding. Unknown-height formats
    are excluded so the cap cannot be silently exceeded. Raises ValueError for
    invalid inputs and RuntimeError for extraction, download, or filesystem
    failures. Requires FFmpeg on PATH and Node at /usr/bin/node.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Please provide a non-empty video URL.")
    if isinstance(height, bool) or not isinstance(height, int) or height <= 0:
        raise ValueError("Requested height must be a positive integer, such as 720.")
    try:
        directory = fspath(output_dir)
        if not isinstance(directory, str) or not directory.strip() or "\x00" in directory:
            raise ValueError
        destination = Path(directory).expanduser().resolve()
        if destination.exists() and not destination.is_dir():
            raise ValueError
    except (TypeError, ValueError, OSError) as exc:
        raise ValueError("Please provide a valid output directory path.") from exc

    completed = _CompletedDownload()
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "js_runtimes": {"node": {"path": "/usr/bin/node"}},
        "format": f"bv[height<={height}]+ba/b[height<={height}]",
        "format_sort": ["res", "vcodec:h264", "acodec:aac"],
        "merge_output_format": "mp4/mkv",
        "paths": {"home": str(destination)},
        "outtmpl": f"%(title).150B [%(id)s] [max-{height}p].%(ext)s",
        "restrictfilenames": True,
        "windowsfilenames": True,
        "overwrites": False,
    }
    try:
        destination.mkdir(parents=True, exist_ok=True)
        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.add_post_processor(completed, when="after_move")
            # Inspect without processing to reject playlist-only URLs before
            # yt-dlp can walk their entries or download any media.
            info = ydl.extract_info(url.strip(), download=False, process=False)
            if not isinstance(info, dict) or not info:
                raise RuntimeError("No video information was returned for this URL.")
            if info.get("_type", "video") != "video" or "entries" in info:
                raise RuntimeError("Please provide a single video URL, not a playlist.")
            ydl.process_ie_result(info, download=True)

        result = completed.info
        if not result or not result.get("filepath"):
            raise RuntimeError("Download did not produce a completed output file path.")
        filepath = Path(result["filepath"]).resolve()
        if not filepath.is_file():
            raise RuntimeError("The completed download file could not be found.")
    except (YoutubeDLError, OSError) as exc:
        raise RuntimeError(f"Unable to download video: {exc}") from exc

    return {
        "filepath": str(filepath),
        "id": result.get("id"),
        "title": result.get("title"),
        "height": result.get("height"),
        "requested_height": height,
        "ext": result.get("ext"),
    }


def get_video_info(url: str) -> dict:
    """Return video metadata without downloading any media.

    Duration is in seconds. Missing metadata fields are returned as None.
    Raises ValueError for a blank URL and RuntimeError if extraction fails.
    """
    url = url.strip()
    if not url:
        raise ValueError("Please provide a non-empty video URL.")

    options = {"quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except YoutubeDLError as exc:
        raise RuntimeError(f"Unable to retrieve video information: {exc}") from exc

    if not info:
        raise RuntimeError("No video information was returned for this URL.")

    return {
        "title": info.get("title"),
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "uploader": info.get("uploader"),
        "webpage_url": info.get("webpage_url"),
    }


def _positive_number(value):
    """Normalize optional numeric metadata without guessing missing values."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isfinite(value) and value > 0:
            return value
    return None


def _video_qualities(formats) -> list[dict]:
    """Filter, normalize, and deduplicate yt-dlp format metadata."""
    choices = {}
    if not isinstance(formats, (list, tuple)):
        return []

    for item in formats:
        if not isinstance(item, dict):
            continue
        if (
            not item.get("format_id")
            or not item.get("url")
            or item.get("vcodec") in (None, "", "none")
            or item.get("ext") == "mhtml"
            or item.get("protocol") == "mhtml"
            or item.get("has_drm")
        ):
            continue

        height = _positive_number(item.get("height"))
        width = _positive_number(item.get("width"))
        fps = _positive_number(item.get("fps"))
        exact_size = _positive_number(item.get("filesize"))
        size = exact_size or _positive_number(item.get("filesize_approx"))
        choice = {
            "format_id": str(item["format_id"]),
            "height": height,
            "width": width,
            "resolution": f"{height:g}p" if height else item.get("resolution") or None,
            "ext": item.get("ext") or None,
            "vcodec": item["vcodec"],
            "acodec": item.get("acodec") or None,
            "fps": fps,
            "filesize": size,
            "filesize_is_approximate": (exact_size is None) if size else None,
        }
        # Unknown dimensions cannot establish that two formats are equivalent.
        key = (
            height, width, choice["ext"], choice["vcodec"], choice["acodec"], fps,
            choice["format_id"] if height is None else None,
        )
        rank = (
            _positive_number(item.get("tbr")) or 0,
            exact_size is not None,
            size is not None,
        )
        if key not in choices or rank > choices[key][0]:
            choices[key] = (rank, choice)

    return sorted(
        (choice for _, choice in choices.values()),
        key=lambda choice: (
            -(choice["height"] or 0),
            -(choice["width"] or 0),
            -(choice["fps"] or 0),
            choice["format_id"],
        ),
    )


def get_video_qualities(url: str) -> list[dict]:
    """Return available video formats for one video without downloading media.

    Entries contain format_id, height, width, resolution (a height label), ext,
    vcodec, acodec, fps, filesize (bytes), and filesize_is_approximate.
    Missing fields are None; acodec='none' means video-only. Unknown heights
    sort last. Equivalent dimensions/container/codecs/fps collapse to the
    highest reported bitrate, preferring known sizes when bitrates tie.
    Distinct codecs, containers, frame rates, and audio variants remain options.

    Returns an empty list when no usable formats exist. Raises ValueError for
    blank URLs and RuntimeError for failed, empty, or playlist extraction.
    """
    url = url.strip()
    if not url:
        raise ValueError("Please provide a non-empty video URL.")

    options = {"quiet": True, "no_warnings": True, "noplaylist": True}
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except YoutubeDLError as exc:
        raise RuntimeError(f"Unable to retrieve video qualities: {exc}") from exc

    if not isinstance(info, dict) or not info:
        raise RuntimeError("No video information was returned for this URL.")
    if info.get("_type") in ("playlist", "multi_video") or "entries" in info:
        raise RuntimeError("Please provide a single video URL, not a playlist.")

    return _video_qualities(info.get("formats"))
