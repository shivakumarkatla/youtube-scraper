"""Command-line interface.

Usage:
    python -m app.main "https://www.youtube.com/watch?v=VIDEO_ID"
    python -m app.main "URL" --output output/video.json --csv output/video.csv
"""

import argparse
import csv
import json
import sys
import textwrap
from pathlib import Path

from app.models import FIELD_NAMES, ScraperError, VideoData
from app.scraper import scrape_video

DESCRIPTION_PREVIEW_LENGTH = 500


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.main",
        description="Scrape public information from a YouTube video page (no API key needed).",
    )
    parser.add_argument("url", help="YouTube video URL (watch, youtu.be or shorts link)")
    parser.add_argument("--output", metavar="FILE", help="save the result as JSON")
    parser.add_argument("--csv", metavar="FILE", help="save the result as CSV")
    parser.add_argument("--json", action="store_true", help="print JSON instead of the readable summary")
    parser.add_argument("--debug", action="store_true", help="show full error details")
    return parser


def format_value(value: object) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def format_readable(video: VideoData) -> str:
    description = video.description
    if description and len(description) > DESCRIPTION_PREVIEW_LENGTH:
        description = description[:DESCRIPTION_PREVIEW_LENGTH].rstrip() + "..."
    lines = [
        f"Title:     {format_value(video.title)}",
        f"Channel:   {format_value(video.channel_name)}",
        f"Published: {format_value(video.published_date)}",
        f"Views:     {format_value(video.view_count)}",
        f"Likes:     {format_value(video.like_count)}",
        f"Comments:  {format_value(video.comment_count)}",
        f"URL:       {video.video_url}",
        "Description:",
        textwrap.indent(description or "Not available", "  "),
    ]
    return "\n".join(lines)


def save_json(video: VideoData, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(video.to_dict(), file, indent=2, ensure_ascii=False)
        file.write("\n")


def save_csv(video: VideoData, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # utf-8-sig lets Excel on Windows display non-English characters correctly.
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELD_NAMES)
        writer.writeheader()
        writer.writerow(video.to_dict())  # None values are written as empty cells


def _use_utf8_output() -> None:
    """Avoid crashes when printing emoji/non-English titles in a Windows console."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _use_utf8_output()

    try:
        video = scrape_video(args.url)
    except ScraperError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception:
        if args.debug:
            raise
        print("Error: An unexpected problem occurred. Re-run with --debug for details.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(video.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(format_readable(video))

    try:
        if args.output:
            save_json(video, args.output)
            print(f"Saved JSON to {args.output}", file=sys.stderr)
        if args.csv:
            save_csv(video, args.csv)
            print(f"Saved CSV to {args.csv}", file=sys.stderr)
    except OSError as exc:
        print(f"Error: Could not save the output file ({exc.strerror or exc}).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
