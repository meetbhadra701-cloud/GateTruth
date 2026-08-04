"""Deterministic content hash for a directory tree.

Same algorithm as external-audit/fetch_vendor.py's tree_hash() (kept as a separate copy there
deliberately -- that module audits a vendored third-party tree and should not depend on harness
internals). Used here to bind a manifest to the exact public task-package files (task.yaml,
interface.sv, spec.md, tb/, formal/, constraints.sdc, ...) it was scored against, so a later
revision to a task's public files is visible in newly produced manifests rather than silently
assumed unchanged.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def tree_hash(root: Path, *, exclude_dirnames: frozenset[str] = frozenset({".git"})) -> str:
    digest = hashlib.sha256()
    paths = sorted(
        (path.relative_to(root).as_posix(), path)
        for path in root.rglob("*")
        if not exclude_dirnames.intersection(path.relative_to(root).parts)
    )
    for relative, path in paths:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"F")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        elif path.is_dir():
            digest.update(b"D")
        digest.update(b"\0")
    return digest.hexdigest()
