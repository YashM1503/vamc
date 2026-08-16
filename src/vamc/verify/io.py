"""No-follow reads for files produced across the untrusted execution boundary."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def read_regular_file(path: Path, limit: int) -> bytes | None:
    """Read a bounded regular file without following a final symbolic link."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            return None
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        return content if len(content) <= limit else None
    finally:
        os.close(descriptor)
