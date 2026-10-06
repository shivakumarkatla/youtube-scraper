# YouTube Web Scraper

## Project overview

A small Python command-line tool that takes a YouTube video URL and scrapes the
publicly visible information from that video's page.

**This project scrapes publicly accessible YouTube video information. It does not
use the official YouTube Data API and does not need an API key.**

## Features

- Accepts `watch`, `youtu.be` and `shorts` URLs
- Extracts title, channel name, description, published date, view count,
  like count, comment count and video URL
- Fields that cannot be found are returned as `null` instead of crashing the scraper
- Cleans text (whitespace, HTML entities) and numbers (`"1.2K"` becomes `1200`)
- Prints a readable summary, or JSON with `--json`
- Saves results to JSON (`--output`) and CSV (`--csv`)
- Simple, readable error messages (no stack traces by default)
- Unit tests that run offline

## How the scraper works

1. `extract_video_id()` validates the URL and pulls out the 11-character video ID.
2. The page `https://www.youtube.com/watch?v=<ID>` is downloaded with `requests`
   (browser-like User-Agent, 10-second timeout).
3. YouTube embeds its own page data inside the HTML. The scraper reads:
   - `ytInitialPlayerResponse`: title, channel, description, views, publish date
   - `ytInitialData`: like count and comment count
   - JSON-LD and meta tags as fallbacks
4. Each field tries several sources in order and uses the first usable value.
5. Values are cleaned and returned as a `VideoData` object.

## Technology used

- Python 3.11+
- `requests` (HTTP), `beautifulsoup4` (meta tags / JSON-LD), standard library
  (`json`, `re`, `csv`, `argparse`, `dataclasses`)
- `python-dotenv` (optional `.env` settings), `pytest` (tests)

## Installation

```bash
git clone <your-repo-url>
cd youtube-scraper
```

### Virtual environment setup

Windows (PowerShell):

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

If PowerShell blocks the script, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first.

macOS / Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Dependency installation

```bash
pip install -r requirements.txt
```

Optional: copy `.env.example` to `.env` to change the timeout or User-Agent.

## Usage

Always wrap the URL in quotes (URLs contain `&`, which shells treat specially).

```bash
python -m app.main "https://www.youtube.com/watch?v=VIDEO_ID"
python -m app.main "https://youtu.be/VIDEO_ID"
python -m app.main "https://www.youtube.com/shorts/VIDEO_ID"

# Save results
python -m app.main "URL" --output output/video.json
python -m app.main "URL" --csv output/video.csv

# Print JSON instead of the readable summary
python -m app.main "URL" --json
```

| Option | Meaning |
| --- | --- |
| `--output FILE` | Save the result as JSON |
| `--csv FILE` | Save the result as CSV |
| `--json` | Print JSON to the terminal |
| `--debug` | Show the full error traceback |

## JSON output example

Illustrative values:

```json
{
  "video_id": "abc123DEF45",
  "video_url": "https://www.youtube.com/watch?v=abc123DEF45",
  "title": "Example Video",
  "channel_name": "Example Channel",
  "description": "Example description",
  "published_date": "2026-01-01",
  "view_count": 123456,
  "like_count": 5000,
  "comment_count": null
}
```

## CSV output example

```csv
video_id,video_url,title,channel_name,description,published_date,view_count,like_count,comment_count
abc123DEF45,https://www.youtube.com/watch?v=abc123DEF45,Example Video,Example Channel,Example description,2026-01-01,123456,5000,
```

Missing values are empty cells. The CSV is saved as UTF-8 with a BOM so Excel
shows non-English characters correctly.

## Testing

```bash
python -m pytest
```

Tests use fake HTML and never contact YouTube.

## Limitations

- YouTube can change its page structure at any time, which may break extraction.
- Like and comment counts are the most fragile fields; they may come back `null`.
- Likes can be hidden by the creator and comments can be disabled (both give `null`).
- Only one video per run; no playlists, channels or comment text.
- Private, deleted, age-restricted or region-locked videos may not be accessible.
- Counts depend on what YouTube shows to anonymous visitors, and `"1.2K"` style
  values are rounded by YouTube.
- Intended for learning and assessment use. Automated access may be restricted by
  YouTube's Terms of Service, so scrape politely and at low volume.

## Troubleshooting

| Message | What to try |
| --- | --- |
| `Error: Invalid YouTube video URL.` | Check the link and that the video ID is 11 characters. |
| `Error: Unsupported URL...` | Only YouTube video links are supported. |
| `Error: Unable to access the YouTube video page.` | Check your internet connection, then retry. |
| `Error: The request to YouTube timed out...` | Retry, or raise `REQUEST_TIMEOUT` in `.env`. |
| `Error: Could not extract video metadata.` | The page layout may have changed or YouTube served a different page. Try another video, run with `--debug`. |
| Cookie-consent message | YouTube showed a consent page (common in some regions). The scraper does not bypass it. |
| `ModuleNotFoundError: app` | Run commands from the project root (the folder containing `app/`). |
