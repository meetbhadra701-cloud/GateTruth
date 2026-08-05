"""Regression test for the public contamination gate."""

from pathlib import Path

import pytest

from scripts.contamination_check import REPO_ROOT, ContaminationError, run_checks


def test_repository_contamination_gate() -> None:
    report = run_checks(REPO_ROOT)
    assert report.track_a_tasks == 60
    assert report.hidden_markers == 0
    assert report.hidden_loaders == 68
    assert report.package_canaries == 70
    assert report.signed_packages_checked == 68


def _fixture_canary(suffix: str) -> str:
    """Build a syntactically valid fixture canary without ever spelling the
    real pattern contiguously in this source file -- contamination_check.py
    scans .py sources too, and a literal match here would be a real, if
    fictitious, "undeclared canary" finding against this very file."""

    return "SILICONBENCH-" + "CANARY-" + f"DEADBEEF-0000-0000-0000-{suffix}"


def _minimal_task_package(root: Path, task_id: str, canary: str) -> None:
    task_root = root / "tasks" / task_id
    task_root.mkdir(parents=True)
    (task_root / "task.yaml").write_text(
        f"id: {task_id}\ncanary: {canary}\n", encoding="utf-8"
    )
    tb_root = task_root / "tb"
    tb_root.mkdir()
    (tb_root / f"test_{task_id}.py").write_text(
        f'load_hidden(globals(), "{task_id}")\n', encoding="utf-8"
    )


def test_generated_result_tree_cannot_leak_a_canary_outside_its_task(
    tmp_path: Path,
) -> None:
    """A result artifact that echoes a task's canary outside tasks/<id>/ must fail
    the gate closed -- this is the exact shape of a model completion that copies
    spec text (and its canary) into a committed results/ sample."""

    canary = _fixture_canary("000000000000")
    _minimal_task_package(tmp_path, "t1_fixture_task", canary)

    leaked = tmp_path / "results" / "eval" / "official" / "some-model" / "t1_fixture_task"
    leaked.mkdir(parents=True)
    (leaked / "sample_1.sv").write_text(
        f"// echoes the spec\n// {canary}\nmodule m; endmodule\n", encoding="utf-8"
    )

    with pytest.raises(ContaminationError, match="canary escaped"):
        run_checks(tmp_path)


def _signed_task_package(root: Path, task_id: str, canary: str, *, ref_review: str) -> Path:
    task_root = root / "tasks" / task_id
    task_root.mkdir(parents=True)
    (task_root / "task.yaml").write_text(
        f"id: {task_id}\ncanary: {canary}\n"
        f"ref_review: {ref_review}\nhidden_review: {ref_review}\n",
        encoding="utf-8",
    )
    tb_root = task_root / "tb"
    tb_root.mkdir()
    (tb_root / f"test_{task_id}.py").write_text(
        f'load_hidden(globals(), "{task_id}")\n', encoding="utf-8"
    )
    return task_root


def test_signed_package_with_leftover_pending_boilerplate_fails_closed(
    tmp_path: Path,
) -> None:
    """GTFS-037: once task.yaml's review fields are genuinely signed off, any file in
    that same package still claiming HUMAN REVIEW: PENDING is a real, verifiable
    contradiction of the metadata a reviewer can independently check -- this must
    fail the gate, not pass silently."""

    canary = _fixture_canary("000000000002")
    task_root = _signed_task_package(
        tmp_path, "t1_fixture_signed", canary, ref_review="SIGNED-OFF-BY-MEET-2026-08-05"
    )
    (task_root / "spec.md").write_text(
        "# t1_fixture_signed - Spec\nHUMAN REVIEW: PENDING\n", encoding="utf-8"
    )

    with pytest.raises(ContaminationError, match="stale.*PENDING.*boilerplate"):
        run_checks(tmp_path)


def test_genuinely_pending_package_is_not_flagged_for_its_own_pending_text(
    tmp_path: Path,
) -> None:
    """Sanity check for the fixture above: a package whose task.yaml review fields are
    still honestly PENDING must not be flagged just because its files also say
    PENDING -- that boilerplate is accurate for it, and only tightens once the
    package is actually signed off."""

    canary = _fixture_canary("000000000003")
    task_root = _signed_task_package(
        tmp_path, "t1_fixture_pending", canary, ref_review="PENDING"
    )
    (task_root / "spec.md").write_text(
        "# t1_fixture_pending - Spec\nHUMAN REVIEW: PENDING\n", encoding="utf-8"
    )

    with pytest.raises(ContaminationError, match="expected 60 Track A tasks") as exc_info:
        run_checks(tmp_path)
    assert "stale" not in str(exc_info.value)


def test_generated_result_tree_without_a_leaked_canary_is_not_flagged_as_leaked(
    tmp_path: Path,
) -> None:
    """Sanity check for the fixture above: a result tree that only ever repeats a
    canary inside its owning task directory must not itself be flagged as a leak.
    (This minimal fixture still fails the unrelated "exactly 60 Track A tasks"
    repository-shape check, so the gate still raises -- but not for a canary leak.)"""

    canary = _fixture_canary("000000000001")
    _minimal_task_package(tmp_path, "t1_fixture_task", canary)

    clean = tmp_path / "results" / "eval" / "official" / "some-model" / "t1_fixture_task"
    clean.mkdir(parents=True)
    (clean / "sample_1.sv").write_text("module m; endmodule\n", encoding="utf-8")

    with pytest.raises(ContaminationError, match="expected 60 Track A tasks") as exc_info:
        run_checks(tmp_path)
    assert "canary escaped" not in str(exc_info.value)
