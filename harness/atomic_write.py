"""Crash-safe text writes shared by every result-manifest writer.

A plain path.write_text(...) killed mid-write (OOM, SIGKILL, a container hitting its
--memory cap) leaves a truncated file at the final path -- for manifests that are later
json.load()'d for official scoring, that is a corrupted result, not just a missing one.
Write to a sibling temp file in the same directory, fsync it, then atomically rename it
into place, so the final path always holds either the previous complete content or the
new complete content, never a partial write. Extracted from harness/spend.py's
_save_spend_unlocked, which already used this pattern for the spend ledger.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    """Byte-exact counterpart to atomic_write_text.

    Text mode's universal-newline handling silently rewrites CRLF to LF on read,
    which breaks any later byte-for-byte hash comparison against the original file
    (e.g. a submission's recorded sha256). Callers persisting a copy of a file whose
    bytes must match a content hash need this, not atomic_write_text.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as temp_file:
            temp_file.write(content)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
