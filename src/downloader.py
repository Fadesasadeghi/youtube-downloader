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
