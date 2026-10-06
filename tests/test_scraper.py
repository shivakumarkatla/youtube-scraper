"""Tests. None of them touch the network: YouTube pages are faked."""

import csv
import json

import pytest
import requests

from app import scraper
from app.main import main, save_csv, save_json
from app.models import ExtractionError, InvalidURLError, PageAccessError, UnsupportedURLError, VideoData
from app.scraper import find_comment_count, parse_video_page, scrape_video
from app.utils import clean_text, extract_video_id, normalize_date, parse_count

VIDEO_ID = "dQw4w9WgXcQ"
VIDEO_URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"

PLAYER = {
    "playabilityStatus": {"status": "OK"},
    "videoDetails": {
        "videoId": VIDEO_ID,
        "title": "Example &amp; Video",
        "author": "Example Channel",
        "shortDescription": "Line one\n\nLine two  with   spaces",
        "viewCount": "123456",
    },
    "microformat": {"playerMicroformatRenderer": {"publishDate": "2026-01-01T10:00:00-08:00"}},
}
INITIAL_DATA = {
    "contents": {
        "likeButton": {"accessibilityText": "like this video along with 5,000 other people"},
        "commentsEntryPointHeaderRenderer": {"commentCount": {"simpleText": "300"}},
    }
}


def build_page(player=None, initial=None, head="", body=""):
    scripts = ""
    if player is not None:
        scripts += f"<script>var ytInitialPlayerResponse = {json.dumps(player)};</script>"
    if initial is not None:
        scripts += f"<script>var ytInitialData = {json.dumps(initial)};</script>"
    return f"<html><head>{head}</head><body>{body}{scripts}</body></html>"


class FakeResponse:
    def __init__(self, text="", status_code=200, url=VIDEO_URL):
        self.text = text
        self.status_code = status_code
        self.url = url


# ---------------------------------------------------------------- URL parsing
def test_standard_url():
    assert extract_video_id(f"https://www.youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID


def test_standard_url_with_extra_parameters():
    assert extract_video_id(f"https://www.youtube.com/watch?list=PL1&v={VIDEO_ID}&t=30s") == VIDEO_ID


def test_url_without_scheme_and_mobile_host():
    assert extract_video_id(f"youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID
    assert extract_video_id(f"https://m.youtube.com/watch?v={VIDEO_ID}") == VIDEO_ID


def test_short_url():
    assert extract_video_id(f"https://youtu.be/{VIDEO_ID}") == VIDEO_ID
    assert extract_video_id(f"https://youtu.be/{VIDEO_ID}?si=abc") == VIDEO_ID


def test_shorts_url():
    assert extract_video_id(f"https://www.youtube.com/shorts/{VIDEO_ID}") == VIDEO_ID


@pytest.mark.parametrize("url", ["", "   ", "not a url", "ftp://youtube.com/watch?v=dQw4w9WgXcQ", None])
def test_invalid_url(url):
    with pytest.raises(InvalidURLError):
        extract_video_id(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch",
        "https://www.youtube.com/watch?v=",
        "https://www.youtube.com/watch?v=tooshort",
        "https://youtu.be/",
        "https://www.youtube.com/shorts/",
        "https://www.youtube.com/channel/abc",
    ],
)
def test_missing_or_bad_video_id(url):
    with pytest.raises(InvalidURLError):
        extract_video_id(url)


def test_unsupported_site():
    with pytest.raises(UnsupportedURLError):
        extract_video_id("https://vimeo.com/123456789")


# ---------------------------------------------------------------- Value cleaning
@pytest.mark.parametrize(
    "raw, expected",
    [
        (123456, 123456),
        ("123,456", 123456),
        ("123,456 views", 123456),
        ("1.2K", 1200),
        ("2.5M views", 2_500_000),
        ("No views", 0),
        ("", None),
        ("abc", None),
        (None, None),
    ],
)
def test_parse_count(raw, expected):
    assert parse_count(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2026-01-01", "2026-01-01"),
        ("2026-01-01T10:00:00-08:00", "2026-01-01"),
        ("Jan 5, 2026", "2026-01-05"),
        ("2026-13-45", None),
        ("yesterday", None),
        (None, None),
    ],
)
def test_normalize_date(raw, expected):
    assert normalize_date(raw) == expected


def test_clean_text_unescapes_and_collapses_whitespace():
    assert clean_text("  Tom &amp;\n  Jerry\u00a0 &quot;show&quot; ") == 'Tom & Jerry "show"'
    assert clean_text("   ") is None
    assert clean_text("a  b\n\n\n\nc", keep_newlines=True) == "a b\n\nc"


# ---------------------------------------------------------------- Metadata parsing
def test_metadata_parsing():
    video = parse_video_page(build_page(PLAYER, INITIAL_DATA), VIDEO_ID)
    assert video.video_id == VIDEO_ID
    assert video.video_url == VIDEO_URL
    assert video.title == "Example & Video"
    assert video.channel_name == "Example Channel"
    assert video.description == "Line one\n\nLine two with spaces"
    assert video.published_date == "2026-01-01"
    assert video.view_count == 123456
    assert video.like_count == 5000
    assert video.comment_count == 300


def test_missing_optional_metadata_gives_none():
    player = {"videoDetails": {"title": "Only a title"}}
    video = parse_video_page(build_page(player, {}), VIDEO_ID)
    assert video.title == "Only a title"
    assert video.channel_name is None
    assert video.description is None
    assert video.published_date is None
    assert video.view_count is None
    assert video.like_count is None
    assert video.comment_count is None


def test_fallback_to_meta_tags():
    head = (
        '<meta property="og:title" content="Meta Title">'
        '<meta itemprop="datePublished" content="2026-02-03">'
        '<meta itemprop="interactionCount" content="42">'
    )
    body = '<span itemprop="author"><link itemprop="name" content="Meta Channel"></span>'
    video = parse_video_page(build_page(head=head, body=body), VIDEO_ID)
    assert video.title == "Meta Title"
    assert video.channel_name == "Meta Channel"
    assert video.published_date == "2026-02-03"
    assert video.view_count == 42


def test_fallback_to_json_ld():
    ld = {
        "@type": "VideoObject",
        "name": "LD Title",
        "author": {"name": "LD Channel"},
        "uploadDate": "2026-03-04",
        "interactionStatistic": {
            "interactionType": "https://schema.org/WatchAction",
            "userInteractionCount": 77,
        },
    }
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    video = parse_video_page(build_page(head=head), VIDEO_ID)
    assert (video.title, video.channel_name) == ("LD Title", "LD Channel")
    assert video.published_date == "2026-03-04"
    assert video.view_count == 77


def test_comment_count_from_engagement_panel():
    data = {
        "engagementPanelTitleHeaderRenderer": {
            "title": {"runs": [{"text": "Comments"}]},
            "contextualInfo": {"runs": [{"text": "1.2K"}]},
        }
    }
    assert find_comment_count(data) == 1200


# ---------------------------------------------------------------- Bad pages
@pytest.mark.parametrize(
    "page",
    [
        "",
        "<html><body>Nothing useful here</body></html>",
        "<script>var ytInitialPlayerResponse = {broken json;</script>",
    ],
)
def test_unexpected_html_raises_extraction_error(page):
    with pytest.raises(ExtractionError):
        parse_video_page(page, VIDEO_ID)


def test_unavailable_video_raises_access_error():
    player = {"playabilityStatus": {"status": "ERROR", "reason": "Video unavailable"}}
    with pytest.raises(PageAccessError):
        parse_video_page(build_page(player, {}), VIDEO_ID)


# ---------------------------------------------------------------- Fetching (mocked)
def test_scrape_video_with_mocked_response(monkeypatch):
    page = build_page(PLAYER, INITIAL_DATA)
    monkeypatch.setattr(scraper.requests, "get", lambda *args, **kwargs: FakeResponse(page))
    video = scrape_video(f"https://youtu.be/{VIDEO_ID}")
    assert video.title == "Example & Video"
    assert video.video_url == VIDEO_URL


def test_timeout_is_reported(monkeypatch):
    def raise_timeout(*args, **kwargs):
        raise requests.Timeout()

    monkeypatch.setattr(scraper.requests, "get", raise_timeout)
    with pytest.raises(PageAccessError, match="timed out"):
        scrape_video(VIDEO_URL)


def test_network_failure_is_reported(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError()

    monkeypatch.setattr(scraper.requests, "get", raise_connection_error)
    with pytest.raises(PageAccessError, match="Unable to access"):
        scrape_video(VIDEO_URL)


def test_http_error_status(monkeypatch):
    monkeypatch.setattr(scraper.requests, "get", lambda *a, **k: FakeResponse(status_code=404))
    with pytest.raises(PageAccessError):
        scrape_video(VIDEO_URL)


# ---------------------------------------------------------------- Output files and CLI
def make_video():
    return VideoData(
        video_id=VIDEO_ID,
        video_url=VIDEO_URL,
        title="Hello, world",
        channel_name="Chan",
        description="Line 1\nLine 2",
        view_count=10,
    )


def test_json_output(tmp_path):
    path = tmp_path / "nested" / "video.json"
    save_json(make_video(), path)
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    assert data == make_video().to_dict()
    assert data["like_count"] is None
    assert '"like_count": null' in text


def test_csv_output(tmp_path):
    path = tmp_path / "nested" / "video.csv"
    save_csv(make_video(), path)
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 1
    assert rows[0]["title"] == "Hello, world"
    assert rows[0]["description"] == "Line 1\nLine 2"
    assert rows[0]["view_count"] == "10"
    assert rows[0]["like_count"] == ""


def test_cli_invalid_url_shows_simple_error(capsys):
    assert main(["not a url"]) == 1
    assert capsys.readouterr().err == "Error: Invalid YouTube video URL.\n"


def test_cli_success_with_files(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("app.main.scrape_video", lambda url: make_video())
    json_path, csv_path = tmp_path / "v.json", tmp_path / "v.csv"
    assert main([VIDEO_URL, "--output", str(json_path), "--csv", str(csv_path)]) == 0
    assert "Hello, world" in capsys.readouterr().out
    assert json_path.exists() and csv_path.exists()


def test_cli_json_flag_prints_json(monkeypatch, capsys):
    monkeypatch.setattr("app.main.scrape_video", lambda url: make_video())
    assert main([VIDEO_URL, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["video_id"] == VIDEO_ID
