"""Download a YouTube video page and extract its public metadata.

No API is used. YouTube embeds the data it needs to draw the page inside the HTML
(`ytInitialPlayerResponse`, `ytInitialData`, meta tags, optional JSON-LD), so we
read that instead of relying on fragile CSS selectors.
"""

import json
import re
from collections.abc import Iterator
from typing import Any

import requests
from bs4 import BeautifulSoup

from app import config
from app.models import ExtractionError, PageAccessError, VideoData
from app.utils import (
    build_video_url,
    clean_text,
    extract_video_id,
    normalize_date,
    parse_count,
)

ACCESS_ERROR_MESSAGE = "Unable to access the YouTube video page."
EXTRACTION_ERROR_MESSAGE = "Could not extract video metadata."


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def scrape_video(url: str) -> VideoData:
    """Validate the URL, download the page and return the scraped data."""
    video_id = extract_video_id(url)
    html_text = fetch_html(build_video_url(video_id))
    return parse_video_page(html_text, video_id)


# --------------------------------------------------------------------------
# Step 1: download
# --------------------------------------------------------------------------
def fetch_html(video_url: str) -> str:
    headers = {
        "User-Agent": config.USER_AGENT,
        "Accept-Language": config.ACCEPT_LANGUAGE,
    }
    try:
        response = requests.get(video_url, headers=headers, timeout=config.REQUEST_TIMEOUT)
    except requests.Timeout as exc:
        raise PageAccessError("The request to YouTube timed out. Please try again.") from exc
    except requests.RequestException as exc:
        raise PageAccessError(ACCESS_ERROR_MESSAGE) from exc

    if "consent." in response.url:
        raise PageAccessError(
            "YouTube asked for cookie consent instead of showing the video page."
        )
    if response.status_code != 200:
        raise PageAccessError(ACCESS_ERROR_MESSAGE)
    return response.text


# --------------------------------------------------------------------------
# Step 2: parse (pure function - easy to test with saved HTML)
# --------------------------------------------------------------------------
def parse_video_page(html_text: str, video_id: str) -> VideoData:
    player = extract_json_variable(html_text, "ytInitialPlayerResponse") or {}
    initial_data = extract_json_variable(html_text, "ytInitialData") or {}
    soup = BeautifulSoup(html_text, "html.parser")
    json_ld = extract_json_ld(soup)

    check_playability(player)
    details = player.get("videoDetails") or {}
    micro = (player.get("microformat") or {}).get("playerMicroformatRenderer") or {}

    title = pick_text(
        details.get("title"),
        micro.get("title"),
        json_ld.get("name"),
        meta_content(soup, "property", "og:title"),
        meta_content(soup, "itemprop", "name"),
    )
    if title is None:
        raise ExtractionError(EXTRACTION_ERROR_MESSAGE)

    return VideoData(
        video_id=video_id,
        video_url=build_video_url(video_id),
        title=title,
        channel_name=pick_text(
            details.get("author"),
            micro.get("ownerChannelName"),
            ld_author(json_ld),
            channel_from_markup(soup),
        ),
        description=pick_text(
            details.get("shortDescription"),
            micro.get("description"),
            json_ld.get("description"),
            meta_content(soup, "itemprop", "description"),
            meta_content(soup, "property", "og:description"),
            keep_newlines=True,
        ),
        published_date=pick_date(
            micro.get("publishDate"),
            micro.get("uploadDate"),
            json_ld.get("datePublished"),
            json_ld.get("uploadDate"),
            meta_content(soup, "itemprop", "datePublished"),
            meta_content(soup, "itemprop", "uploadDate"),
        ),
        view_count=pick_count(
            details.get("viewCount"),
            micro.get("viewCount"),
            ld_view_count(json_ld),
            meta_content(soup, "itemprop", "interactionCount"),
        ),
        like_count=find_like_count(initial_data),
        comment_count=find_comment_count(initial_data),
    )


def check_playability(player: dict[str, Any]) -> None:
    """Raise if YouTube says the video cannot be shown (deleted, private, ...)."""
    status = (player.get("playabilityStatus") or {}).get("status")
    if "videoDetails" not in player and status in {"ERROR", "LOGIN_REQUIRED", "UNPLAYABLE"}:
        raise PageAccessError(
            "The video is unavailable (it may be private, deleted or restricted)."
        )


# --------------------------------------------------------------------------
# Embedded-data helpers
# --------------------------------------------------------------------------
def extract_json_variable(html_text: str, name: str) -> dict[str, Any] | None:
    """Find `name = {...}` in the page scripts and decode that JSON object.

    raw_decode reads exactly one JSON value, so nested braces are handled for us.
    """
    decoder = json.JSONDecoder()
    for match in re.finditer(rf'{name}["\]]*\s*=\s*', html_text):
        try:
            value, _ = decoder.raw_decode(html_text, match.end())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def extract_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    """Return the schema.org VideoObject from a JSON-LD script, if there is one."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "VideoObject":
                return item
    return {}


def meta_content(soup: BeautifulSoup, attribute: str, value: str) -> str | None:
    tag = soup.find("meta", attrs={attribute: value})
    return tag.get("content") if tag else None


def channel_from_markup(soup: BeautifulSoup) -> str | None:
    tag = soup.select_one('span[itemprop="author"] link[itemprop="name"]')
    return tag.get("content") if tag else None


def ld_author(json_ld: dict[str, Any]) -> Any:
    author = json_ld.get("author")
    if isinstance(author, list) and author:
        author = author[0]
    return author.get("name") if isinstance(author, dict) else author


def ld_view_count(json_ld: dict[str, Any]) -> Any:
    stats = json_ld.get("interactionStatistic") or []
    if isinstance(stats, dict):
        stats = [stats]
    for stat in stats:
        if isinstance(stat, dict) and "Watch" in str(stat.get("interactionType", "")):
            return stat.get("userInteractionCount")
    return None


# --------------------------------------------------------------------------
# Likes and comments live deep inside ytInitialData, so we search for them
# --------------------------------------------------------------------------
LIKE_ALONG_WITH = re.compile(r"like this video along with ([\d.,]+\s?[kmb]?) other people", re.I)
LIKE_LABEL = re.compile(r"([\d.,]+\s?[kmb]?) likes?", re.I)
LABEL_KEYS = {"label", "accessibilityText"}


def iter_items(node: Any) -> Iterator[tuple[str, Any]]:
    """Yield every (key, value) pair found anywhere in nested dicts/lists."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key, value
            yield from iter_items(value)
    elif isinstance(node, list):
        for item in node:
            yield from iter_items(item)


def find_like_count(initial_data: dict[str, Any]) -> int | None:
    for key, value in iter_items(initial_data):
        if key not in LABEL_KEYS or not isinstance(value, str):
            continue
        match = LIKE_ALONG_WITH.search(value) or LIKE_LABEL.fullmatch(value.strip())
        if match:
            count = parse_count(match.group(1))
            if count is not None:
                return count
    return None


def find_comment_count(initial_data: dict[str, Any]) -> int | None:
    for key, value in iter_items(initial_data):
        if not isinstance(value, dict):
            continue
        count = None
        if key == "commentsEntryPointHeaderRenderer":
            count = parse_count(simple_text(value.get("commentCount")))
        elif key == "engagementPanelTitleHeaderRenderer":
            title = str(simple_text(value.get("title")) or "")
            if "comment" in title.lower():
                count = parse_count(simple_text(value.get("contextualInfo")))
        if count is not None:
            return count
    return None


# --------------------------------------------------------------------------
# Value helpers: try candidates in order, return the first usable one
# --------------------------------------------------------------------------
def simple_text(node: Any) -> Any:
    """YouTube text is a plain string, {"simpleText": ...} or {"runs": [...]}."""
    if isinstance(node, dict):
        if "simpleText" in node:
            return node["simpleText"]
        runs = node.get("runs")
        if isinstance(runs, list):
            return "".join(str(run.get("text", "")) for run in runs if isinstance(run, dict))
        return None
    return node


def pick_text(*candidates: Any, keep_newlines: bool = False) -> str | None:
    for candidate in candidates:
        cleaned = clean_text(simple_text(candidate), keep_newlines)
        if cleaned:
            return cleaned
    return None


def pick_count(*candidates: Any) -> int | None:
    for candidate in candidates:
        count = parse_count(simple_text(candidate))
        if count is not None:
            return count
    return None


def pick_date(*candidates: Any) -> str | None:
    for candidate in candidates:
        normalized = normalize_date(simple_text(candidate))
        if normalized:
            return normalized
    return None
