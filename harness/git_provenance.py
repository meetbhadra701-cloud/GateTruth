"""Resolve the harness's own git commit for manifest provenance.

Shared by harness/runner.py and harness/evalmodel.py so both record the same commit under the
same rules external-audit/run_audit.py already established: trust an explicitly set env var only
if it looks like a real hex SHA, otherwise fall back to asking git directly. Recording a fixed
env-var value (rather than always re-deriving from git) matters for a paired reproducibility
check -- two runs meant to be compared against each other should record the same commit even if
the actual git HEAD moved in between, as long as no harness code relevant to either run changed.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from harness.env_compat import read_env

GIT_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")

REPO_ROOT = Path(__file__).resolve().parents[1]


def harness_git(repo_root: Path = REPO_ROOT) -> str:
    candidates = [read_env("GIT_COMMIT"), os.environ.get("GITHUB_SHA")]
    for candidate in candidates:
        value = (candidate or "").lower()
        if GIT_SHA_RE.fullmatch(value):
            return value

    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and GIT_SHA_RE.fullmatch(value) else "unavailable"
