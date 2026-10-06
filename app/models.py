"""Data model and error types used across the project."""

from dataclasses import asdict, dataclass, fields


class ScraperError(Exception):
    """Base class for errors whose message is safe to show to the user."""


class InvalidURLError(ScraperError):
    """The input is not a valid YouTube video URL."""


class UnsupportedURLError(InvalidURLError):
    """The URL is well-formed but is not a supported YouTube video link."""


class PageAccessError(ScraperError):
    """The video page could not be downloaded, or the video is unavailable."""


class ExtractionError(ScraperError):
    """The page was downloaded but no usable metadata could be found."""


@dataclass
class VideoData:
    """Everything we scrape. None means "could not be extracted"."""

    video_id: str
    video_url: str
    title: str | None = None
    channel_name: str | None = None
    description: str | None = None
    published_date: str | None = None  # ISO format: YYYY-MM-DD
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        return asdict(self)


FIELD_NAMES: list[str] = [field.name for field in fields(VideoData)]
