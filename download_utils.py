"""Dependency-free helpers shared by the portable download modules."""

from __future__ import annotations

import hashlib
from pathlib import Path


SHA256_CHUNK_SIZE = 1024 * 1024


def sha256_file(path: Path) -> str:
    """Return the lowercase SHA256 hex digest for a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(SHA256_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()
