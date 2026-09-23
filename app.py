import re
from urllib.parse import parse_qs, urlparse

import streamlit as st

from src.downloader import get_video_info


def validate_video_url(url: str) -> str:
    """Validate an individual YouTube video URL before fetching metadata."""
    url = url.strip()
    if not url:
        raise ValueError("Please paste a YouTube video URL.")

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Please enter a YouTube URL starting with https://.")

    host = parsed.hostname
    parts = parsed.path.strip("/").split("/")
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"} and len(parts) == 1:
        video_id = parts[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}:
            video_id = parts[1]

    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Please enter a valid individual YouTube video URL.")
    return url


def format_duration(seconds: int | float | None) -> str:
    """Format seconds as MM:SS or HH:MM:SS, with a missing-value fallback."""
    if seconds is None:
        return "Unavailable"
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def main() -> None:
    st.set_page_config(page_title="YouTube Downloader", page_icon="▶️")
    st.title("YouTube Downloader")
    st.caption("Paste a YouTube video link to view its details.")

    url = st.text_input("YouTube URL", placeholder="https://www.youtube.com/watch?v=...")

    if st.button("Get Video Info", type="primary"):
        try:
            video_url = validate_video_url(url)
            with st.spinner("Getting video information..."):
                info = get_video_info(video_url)

            if info.get("thumbnail"):
                st.image(info["thumbnail"])
            st.subheader(info.get("title") or "Untitled video")
            st.write("Uploader:", info.get("uploader") or "Unavailable")
            st.write("Duration:", format_duration(info.get("duration")))
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Unable to load video information. Please try again.")


if __name__ == "__main__":
    main()
