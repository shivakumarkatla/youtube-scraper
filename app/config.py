"""Settings. Defaults work out of the box; a .env file can override them."""

import os

from dotenv import load_dotenv

load_dotenv()


def _read_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return default


REQUEST_TIMEOUT: float = _read_float("REQUEST_TIMEOUT", 10.0)

USER_AGENT: str = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)

# Ask for English so labels like "5,000 likes" are formatted consistently.
ACCEPT_LANGUAGE: str = "en-US,en;q=0.9"
