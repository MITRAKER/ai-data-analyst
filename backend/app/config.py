"""Load settings from a .env file (KEY=value lines) without an extra dependency."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from app.files import read_capped

REPO_ROOT: Final = Path(__file__).resolve().parents[2]
MAX_DOTENV_BYTES: Final = 64 * 1024  # a .env file is a few lines; refuse anything huge


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `KEY=value` lines. Blank lines, `# comments` and empty values are skipped.

    Args:
        text: The contents of a .env file.

    Returns:
        The keys and values, with surrounding quotes removed from each value.
    """
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and value:
            values[key] = value
    return values


def load_dotenv(paths: tuple[Path, ...] | None = None) -> None:
    """Copy settings from .env files into `os.environ`.

    Real environment variables win over the file, so a deployment's settings
    can never be overridden by a stray .env file.

    Args:
        paths: The files to read, in order. By default: `.env` in the current
            folder, then `.env` in the repository root.
    """
    candidates = paths if paths is not None else (Path.cwd() / ".env", REPO_ROOT / ".env")
    for path in candidates:
        content = read_capped(path, MAX_DOTENV_BYTES) if path.is_file() else None
        if content is None:  # no file, or one too large to be a real .env file
            continue
        for key, value in parse_dotenv(content.decode("utf-8")).items():
            if key not in os.environ:
                os.environ[key] = value
