from math import isfinite

import yt_dlp
from yt_dlp.utils import YoutubeDLError


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
