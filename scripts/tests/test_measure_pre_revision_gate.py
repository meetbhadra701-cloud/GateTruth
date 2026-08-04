"""Regression test for GTFS-032: this script must never mutate the checkout it is
invoked from. Runs the real script against the real repository (the only way to
prove the safety property end to end) and cleans up the worktree it creates."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from scripts.measure_pre_revision_gate import (
    BASELINE_COMMIT,
    REPO_ROOT,
    REVISED_TASKS,
)
from scripts.measure_pre_revision_gate import main as measure_main

WORKTREE_LINE = re.compile(r"restored in isolated worktree: (.+)$", re.MULTILINE)


def _tracked_bytes(relative_path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"HEAD:{relative_path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def test_restore_only_never_touches_the_real_checkout(
    tmp_path: Path, capsys
) -> None:
    revised_paths = [f"tasks/{t}/tb/test_{t}.py" for t in REVISED_TASKS]
    before = {p: (REPO_ROOT / p).read_bytes() for p in revised_paths}
    status_before = subprocess.run(
        ["git", "status", "--porcelain", "--", *revised_paths],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    out_path = tmp_path / "pre_revision_results.json"
    worktree: Path | None = None
    try:
        exit_code = measure_main(["--out", str(out_path), "--restore-only"])
        assert exit_code == 0

        captured = capsys.readouterr()
        match = WORKTREE_LINE.search(captured.out)
        assert match is not None, f"no worktree path printed:\n{captured.out}"
        worktree = Path(match.group(1).strip())
        assert worktree.is_dir()

        # The real checkout must be byte-identical to before the run, for every
        # revised testbench and according to git itself.
        after = {p: (REPO_ROOT / p).read_bytes() for p in revised_paths}
        assert after == before
        status_after = subprocess.run(
            ["git", "status", "--porcelain", "--", *revised_paths],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        assert status_after == status_before

        # The restore actually happened -- inside the isolated worktree, not here.
        for task_id, relative_path in zip(REVISED_TASKS, revised_paths):
            expected = subprocess.run(
                ["git", "show", f"{BASELINE_COMMIT}:{relative_path}"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
            ).stdout
            restored = (worktree / relative_path).read_bytes()
            assert restored == expected, task_id
    finally:
        if worktree is not None and worktree.is_dir():
            subprocess.run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=REPO_ROOT,
                check=False,
                capture_output=True,
            )
        subprocess.run(
            ["git", "worktree", "prune"], cwd=REPO_ROOT, check=False, capture_output=True
        )

    # And after cleanup, git agrees no worktree metadata was left behind.
    worktree_list = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert str(worktree) not in worktree_list
