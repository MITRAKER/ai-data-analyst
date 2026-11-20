"""Read files with a size limit, so memory use stays bounded (Power of Ten rule 3).

`Path.read_bytes()` reads a whole file, however large it is. `read_capped()`
reads at most one byte more than the limit, so a huge file is refused after
reading a small, fixed amount.
"""

from __future__ import annotations

from pathlib import Path

from app.invariants import require


def read_capped(path: Path, max_bytes: int) -> bytes | None:
    """The bytes of a file, or None if the file is larger than `max_bytes`.

    Raises:
        OSError: If the file cannot be opened or read.
    """
    require(max_bytes > 0, f"max_bytes must be positive, got {max_bytes}")
    with path.open("rb") as handle:
        data = handle.read(max_bytes + 1)
    return data if len(data) <= max_bytes else None
