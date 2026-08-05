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
    _code_fingerprint,
    verify_reference_unchanged,
)
from scripts.measure_pre_revision_gate import main as measure_main

WORKTREE_LINE = re.compile(r"restored in isolated worktree: (.+)$", re.MULTILINE)


def test_code_fingerprint_ignores_a_comment_that_changed_length() -> None:
    """Pins the exact bug this function exists to avoid: a raw masked comparison
    (harness.sv_mask.mask_code alone) blanks comments to spaces in place, so
    "DRAFT" (5 chars) vs "REVIEWED reference implementation" (34 chars) produces
    masked strings of different length and compares unequal even though nothing
    code-shaped changed. _code_fingerprint must treat these as identical."""
    before = "// t2_x - DRAFT reference implementation\nmodule m;\nendmodule\n"
    after = "// t2_x - REVIEWED reference implementation\nmodule m;\nendmodule\n"
    assert _code_fingerprint(before) == _code_fingerprint(after)


def test_code_fingerprint_still_distinguishes_real_code_changes() -> None:
    """The fingerprint must not be so forgiving it hides an actual logic edit."""
    before = "module m;\n  assign y = a & b;\nendmodule\n"
    after = "module m;\n  assign y = a | b;\nendmodule\n"
    assert _code_fingerprint(before) != _code_fingerprint(after)


def test_verify_reference_unchanged_accepts_the_real_current_references() -> None:
    """GTFS-037 rewrote every ref.sv's DRAFT/PENDING review banner (comment lines
    only). That must not trip this gate: the mutation generator masks comments
    before enumerating sites, so a comment-only edit cannot change the mutant set.
    Ran against the real repository, not a fixture, because the whole point is
    proving today's actual tree still clears the gate after that real commit."""
    for task_id in REVISED_TASKS:
        assert verify_reference_unchanged(task_id), task_id


def test_verify_reference_unchanged_still_refuses_a_genuine_functional_edit(
    tmp_path: Path,
) -> None:
    """Comment-masking must not blind the gate to a real logic change. Commits a
    one-line functional edit in a disposable worktree (never REPO_ROOT itself,
    GTFS-032) and points ``head_ref`` at that commit instead of real HEAD."""
    task_id = REVISED_TASKS[0]
    ref = f"tasks/{task_id}/ref/ref.sv"
    worktree_dir = tmp_path / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    try:
        target = worktree_dir / ref
        text = target.read_text(encoding="utf-8")
        assert "endmodule" in text
        target.write_text(text.replace("endmodule", "endmodule\nwire _pre_revision_gate_test_probe;"), encoding="utf-8")
        subprocess.run(["git", "add", ref], cwd=worktree_dir, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@test.invalid",
                "-c",
                "user.name=test",
                "commit",
                "-m",
                "test: inject a real content change for the refusal test",
            ],
            cwd=worktree_dir,
            check=True,
            capture_output=True,
        )
        head_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=worktree_dir,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        assert verify_reference_unchanged(task_id, head_ref=head_sha) is False
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_dir)],
            cwd=REPO_ROOT,
            check=False,
            capture_output=True,
        )
        subprocess.run(["git", "worktree", "prune"], cwd=REPO_ROOT, check=False, capture_output=True)


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
