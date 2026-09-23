import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import streamlit as st

from src.downloader import download_video, get_video_info, get_video_qualities


DOWNLOADS_DIR = Path(__file__).resolve().parent / "downloads"


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
    if st.session_state.get("video_url") != url.strip():
        for key in ("video_info", "video_heights", "completed_download", "quality"):
            st.session_state.pop(key, None)

    if st.button("Get Video Info", type="primary"):
        for key in ("video_info", "video_heights", "completed_download", "quality"):
            st.session_state.pop(key, None)
        try:
            video_url = validate_video_url(url)
            st.session_state.video_url = video_url
            with st.spinner("Getting video information..."):
                st.session_state.video_info = get_video_info(video_url)
            with st.spinner("Getting available qualities..."):
                qualities = get_video_qualities(video_url)
                st.session_state.video_heights = sorted({
                    int(item["height"]) for item in qualities
                    if isinstance(item.get("height"), (int, float))
                    and not isinstance(item["height"], bool)
                    and item["height"] > 0
                    and float(item["height"]).is_integer()
                }, reverse=True)
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Unable to load video information. Please try again.")

    info = st.session_state.get("video_info")
    if info is None:
        return
    if info.get("thumbnail"):
        st.image(info["thumbnail"])
    st.subheader(info.get("title") or "Untitled video")
    st.write("Uploader:", info.get("uploader") or "Unavailable")
    st.write("Duration:", format_duration(info.get("duration")))

    heights = st.session_state.get("video_heights", [])
    if not heights:
        st.info("No video qualities are available. Try getting video information again.")
        return
    height = st.selectbox("Maximum video quality", heights,
                          format_func=lambda value: f"{value}p", key="quality")
    st.caption("The downloaded video may have a lower resolution than this maximum.")
    completed = st.session_state.get("completed_download")
    if completed and completed["requested_height"] != height:
        st.session_state.pop("completed_download", None)

    if st.button("Download Video"):
        st.session_state.pop("completed_download", None)
        try:
            with st.spinner("Downloading video and merging audio..."):
                st.session_state.completed_download = download_video(
                    st.session_state.video_url, height, DOWNLOADS_DIR
                )
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Unable to download the video. Please try again.")

    completed = st.session_state.get("completed_download")
    if completed:
        filepath = Path(completed["filepath"])
        try:
            with filepath.open("rb") as file:
                st.download_button(
                    "Save video to your device", file, file_name=filepath.name,
                    mime={".mp4": "video/mp4", ".mkv": "video/x-matroska"}.get(
                        filepath.suffix.lower(), "application/octet-stream"
                    ),
                )
            st.success("Video downloaded successfully!")
            st.write("File:", filepath.name)
            st.write("Size:", f"{filepath.stat().st_size / (1024 * 1024):.2f} MiB")
            st.write("Actual quality:", f"{completed['height']}p"
                     if completed.get("height") else "Unavailable")
        except OSError:
            st.session_state.pop("completed_download", None)
            st.error("The downloaded file could not be read. Please download it again.")


if __name__ == "__main__":
    main()
