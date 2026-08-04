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

    # -c safe.directory=<repo_root>: plain `git rev-parse` refuses to run at all
    # ("detected dubious ownership") whenever the repo is owned by a different user
    # than the one invoking it -- exactly the situation every sandboxed docker run in
    # this project is in (bind mounts are owned by the host user, not the container's
    # uid 10001). This still returns "unavailable" against a .git-free `git archive`
    # snapshot (docs/SECURE_EXECUTION.md's own staging convention, used by
    # ci.yml/pages.yml/nightly.yml) -- there is genuinely no repository metadata left
    # to query there. That is exactly why GATETRUTH_GIT_COMMIT/GITHUB_SHA are checked
    # first above: GITHUB_SHA in particular is set automatically by every GitHub
    # Actions runner, so passing it through to the container (`-e GITHUB_SHA`) is
    # enough to recover real provenance even from a .git-free tree.
    result = subprocess.run(
        ["git", "-c", f"safe.directory={repo_root}", "rev-parse", "HEAD"],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    value = result.stdout.strip().lower()
    return value if result.returncode == 0 and GIT_SHA_RE.fullmatch(value) else "unavailable"
