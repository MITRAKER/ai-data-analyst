"""Load settings from a .env file (KEY=value lines) without an extra dependency."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv() -> None:
    """Read .env from the current folder or the repo root. Real environment
    variables win over the file, so production settings can't be overridden by it."""
    for path in (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                if value.strip():
                    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
