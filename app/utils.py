"""Small helpers: URL parsing and cleaning of scraped values."""

import html
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import ParseResult, parse_qs, urlparse

from app.models import InvalidURLError, UnsupportedURLError

VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
SHORT_LINK_HOSTS = {"youtu.be", "www.youtu.be"}
ID_IN_PATH_PREFIXES = {"shorts", "embed", "live"}

INVALID_URL_MESSAGE = "Invalid YouTube video URL."


def extract_video_id(url: str) -> str:
    """Return the 11-character video ID from a YouTube URL.

    Supports watch, youtu.be, shorts (plus embed/live) links.
    Raises InvalidURLError or UnsupportedURLError otherwise.
    """
    if not isinstance(url, str) or not url.strip():
        raise InvalidURLError(INVALID_URL_MESSAGE)

    url = url.strip()
    if re.search(r"\s", url):
        raise InvalidURLError(INVALID_URL_MESSAGE)
    if "://" not in url:
        url = "https://" + url  # allow "youtube.com/watch?v=..."

    try:
        parsed = urlparse(url)
    except ValueError as exc:
        raise InvalidURLError(INVALID_URL_MESSAGE) from exc

    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise InvalidURLError(INVALID_URL_MESSAGE)

    if host in SHORT_LINK_HOSTS:
        candidate = parsed.path.strip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS:
        candidate = _id_from_youtube_url(parsed)
    else:
        raise UnsupportedURLError("Unsupported URL. Please provide a YouTube video link.")

    if not VIDEO_ID_PATTERN.fullmatch(candidate):
        raise InvalidURLError(INVALID_URL_MESSAGE)
    return candidate


def _id_from_youtube_url(parsed: ParseResult) -> str:
    if parsed.path.rstrip("/") == "/watch":
        values = parse_qs(parsed.query).get("v", [])
        return values[0] if values else ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[0] in ID_IN_PATH_PREFIXES:
        return parts[1]
    return ""


def build_video_url(video_id: str) -> str:
    """Canonical watch URL, used for every input format (including Shorts)."""
    return f"https://www.youtube.com/watch?v={video_id}"


def clean_text(value: Any, keep_newlines: bool = False) -> str | None:
    """Unescape HTML entities and normalise whitespace. Empty result -> None."""
    if value is None:
        return None
    text = html.unescape(str(value))
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    if keep_newlines:
        lines = [" ".join(line.split()) for line in text.split("\n")]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    else:
        text = " ".join(text.split())
    return text or None


_COUNT_PATTERN = re.compile(r"(\d[\d.,]*)\s*([kmb])?(?![a-z])")
_MULTIPLIERS = {"k": 1_000, "m": 1_000_000, "b": 1_000_000_000}


def parse_count(value: Any) -> int | None:
    """Turn 123456, "123,456", "1.2K views" or "No views" into an int."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip().lower()
    if re.match(r"no\b", text):
        return 0

    match = _COUNT_PATTERN.match(text)
    if not match:
        return None
    number, suffix = match.group(1), match.group(2)

    if suffix:
        try:
            return int(round(float(number.replace(",", "")) * _MULTIPLIERS[suffix]))
        except ValueError:
            return None
    digits = re.sub(r"\D", "", number)
    return int(digits) if digits else None


def normalize_date(value: Any) -> str | None:
    """Return a date as YYYY-MM-DD, or None if it cannot be understood."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()

    match = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)  # ISO, with or without time
    if match:
        try:
            return date(int(match[1]), int(match[2]), int(match[3])).isoformat()
        except ValueError:
            return None

    for fmt in ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None
