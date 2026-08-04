"""Golden-file tests for paper table generation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from harness.schemas.canonical_json import compute_manifest_signature
from harness.scoring import load_reference_metrics
from paper.data.generate_tables import (
    TableDataError,
    generate_tables,
    load_agent_evaluations,
    load_evaluations,
    load_mutations,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
GOLDEN = Path(__file__).parent / "golden"
TRACK_A_FIXTURE = (
    REPO_ROOT
    / "site"
    / "tests"
    / "fixtures"
    / "eval"
    / "smoke"
    / "claude-haiku-4-5-20251001"
)
CANARY_PREFIX = "SILICONBENCH-" + "CANARY-"

# Real, resolvable canonical task IDs -- score_manifest()/validate_track_b_semantics()
# resolve reference metrics and objective.yaml against the actual repository tree
# (harness/reference_metrics.json, REPO_ROOT/tasksB), not whatever synthetic tasks_root
# a test passes in, so these fixtures must name real tasks rather than invented ones
# (GTFS-034: the old "t1_alpha"/"b1_alpha" placeholders stopped resolving once
# load_evaluations/load_agent_evaluations started independently recomputing scores).
TRACK_A_TASK_1 = "t1_gray_counter"
TRACK_A_TASK_2 = "t1_pwm"
# behavior_preserving=false (no SEC gate) and =true (SEC gate required) respectively --
# exercises both branches of validate_track_b_semantics.
TRACK_B_TASK_1 = "b5_remove_latches_decoder"
TRACK_B_TASK_2 = "b1_close_timing_mac"


def _write_task(root: Path, task_id: str, tier: str, formal: bool, suffix: str) -> None:
    task_root = root / task_id
    task_root.mkdir(parents=True)
    (task_root / "task.yaml").write_text(
        f"""id: {task_id}
tier: {tier}
tags: [fixture]
clock_target_ns: 10.0
formal: {'true' if formal else 'false'}
route_t3: false
weights: {{area: 1, delay: 1, power: 1}}
canary: "{CANARY_PREFIX}{suffix}"
ref_review: PENDING
hidden_review: PENDING
""",
        encoding="utf-8",
    )


def _write_agent_task(root: Path, task_id: str) -> None:
    """Only needs to exist for _canonical_task_ids' glob count -- the real
    objective.yaml consulted by validate_track_b_semantics lives under the real
    REPO_ROOT/tasksB/<task_id>/, not this fixture root."""

    task_root = root / task_id
    task_root.mkdir(parents=True)
    (task_root / "objective.yaml").write_text(
        f"id: {task_id}\nobjective: fixture\n",
        encoding="utf-8",
    )


def _write_track_a_manifest(
    path: Path,
    *,
    task_id: str,
    provider: str,
    model: str,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_usd: float | None = None,
    passing: bool = True,
) -> dict:
    """A manifest whose stage metrics are genuinely dimensionally consistent with
    task_id's real committed reference metrics (score_manifest independently
    recomputes PPA from these, GTFS-007) -- not hand-picked round numbers."""

    raw = json.loads(
        (TRACK_A_FIXTURE / "t1_gray_counter" / "sample_1.json").read_text(
            encoding="utf-8"
        )
    )
    if passing:
        reference = load_reference_metrics(task_id)
        for stage in raw["stages"]:
            if stage["stage"] == 3:
                stage["area_um2"] = reference.area_um2
            elif stage["stage"] == 4:
                stage["wns_ns"] = reference.clock_target_ns - reference.delay_ns
            elif stage["stage"] == 5:
                stage["power_mw"] = reference.power_mw
        raw["ppa"] = 1.0
        raw["task_score"] = round(66.66666666666667, 10)
    else:
        for stage in raw["stages"]:
            if stage["stage"] == 0:
                stage["status"] = "fail"
                stage.pop("warnings", None)
            elif stage["stage"] in {1, 2, 3, 4, 5}:
                stage["status"] = "fail"
                for key in (
                    "tests_run",
                    "tests_passed",
                    "area_um2",
                    "cell_count",
                    "wns_ns",
                    "tns_ns",
                    "fmax_mhz",
                    "power_mw",
                ):
                    stage.pop(key, None)
        raw["ppa"] = 0.0
        raw["task_score"] = 0.0
    raw.update(task_id=task_id, provider=provider, model=model)
    if tokens_in is not None:
        raw["tokens_in"] = tokens_in
    if tokens_out is not None:
        raw["tokens_out"] = tokens_out
    if cost_usd is not None:
        raw["cost_usd"] = cost_usd
    raw["signature"] = compute_manifest_signature(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    return raw


def _write_track_a_summary(
    root: Path,
    *,
    run_name: str,
    provider: str,
    model: str,
    task_ids: list[str],
    failing_tasks: frozenset[str] = frozenset(),
) -> None:
    """tokens/cost/aggregate_mean are always derived from the manifests actually
    written, never passed in -- since load_evaluations independently recomputes
    them from the same children (GTFS-034), a hand-picked summary total would
    just be a self-inflicted mismatch, not a meaningful test input."""

    destination = root / run_name / model
    tasks: dict[str, dict] = {}
    manifests: list[dict] = []
    for task_id in task_ids:
        relative = f"{task_id}/sample_1.json"
        manifest = _write_track_a_manifest(
            destination / relative,
            task_id=task_id,
            provider=provider,
            model=model,
            passing=task_id not in failing_tasks,
        )
        manifests.append(manifest)
        tasks[task_id] = {
            "scores": [manifest["task_score"]],
            "mean_score": manifest["task_score"],
            "samples": [
                {
                    "sample": 1,
                    "score": manifest["task_score"],
                    "manifest": relative,
                    "manifest_signature": manifest["signature"],
                }
            ],
            "skipped": False,
        }
    summary = {
        "suite_version": "v0.2",
        "prompt_version": "track-a-v1",
        "provider": provider,
        "model": model,
        "temperature": 0.0,
        "official": True,
        "samples_per_task": 1,
        "task_ids": task_ids,
        "tasks": tasks,
        "aggregate_mean": sum(m["task_score"] for m in manifests) / len(manifests),
        "tokens_in": sum(m["tokens_in"] for m in manifests),
        "tokens_out": sum(m["tokens_out"] for m in manifests),
        "cost_usd": sum(m["cost_usd"] for m in manifests),
        "pre_run_estimate_usd": sum(m["cost_usd"] for m in manifests),
        "timestamp": "2026-01-02T00:00:00Z",
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    (destination / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_track_b_manifest(
    path: Path,
    *,
    task_id: str,
    provider: str,
    model: str,
    objective_pass: bool,
    behavior_preserving: bool,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> dict:
    if behavior_preserving:
        stage2_status = "pass" if objective_pass else "fail"
        stage2 = {"stage": 2, "name": "sec", "status": stage2_status}
        sec = {"status": stage2_status, "backend": "yosys-equiv", "seconds": 1.0}
    else:
        stage2 = {"stage": 2, "name": "correctness", "status": "skip"}
        sec = {"status": "skip", "backend": None, "seconds": None}
    manifest = {
        "task_id": task_id,
        "suite_version": "v0.2",
        "track": "B",
        "docker_digest": "sha256:" + "0" * 64,
        "docker_digest_source": "env",
        "platform": "linux/amd64",
        "submission_dir": "/tmp/fixture/submission",
        "submission_sha256": None,
        "disqualified": False,
        "disqualification_reason": None,
        "objective_type": "add_property",
        "objective_pass": objective_pass,
        "stages": [
            {"stage": 0, "name": "lint", "status": "pass", "warnings": 0},
            {
                "stage": 1,
                "name": "sim",
                "status": "pass",
                "tests_run": 4,
                "tests_passed": 4,
            },
            stage2,
            {"stage": 3, "name": "objective", "status": "pass" if objective_pass else "fail"},
        ],
        "sec": sec,
        "ppa_delta": {
            "design": {
                "area_um2": 80.0,
                "wns_ns": 1.0,
                "tns_ns": 0.0,
                "fmax_mhz": 100.0,
                "power_mw": 0.5,
            },
            "baseline": None,
            "area_ratio": None,
            "power_ratio": None,
            "wns_delta_ns": None,
        },
        "task_score": 100.0 if objective_pass else 0.0,
        "wall_clock_s": 12.5,
        "provider": provider,
        "model": model,
        "temperature": 0.0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "tool_calls": 5,
        "baseline_review": None,
        "tb_review": None,
        "hidden_module_sha256": None,
        "hidden_test_count": None,
        "timestamp": "2026-01-02T00:00:00Z",
        "signature": "0" * 64,
    }
    manifest["signature"] = compute_manifest_signature(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


_BEHAVIOR_PRESERVING = {TRACK_B_TASK_1: False, TRACK_B_TASK_2: True}


def _write_agent_summary(
    root: Path,
    *,
    run_name: str,
    provider: str,
    model: str,
    task_ids: list[str],
    objective_met_tasks: frozenset[str],
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    destination = root / run_name / provider / model
    destination.mkdir(parents=True)
    tasks: dict[str, dict] = {}
    per_task_tokens = tokens_in // len(task_ids)
    per_task_tokens_out = tokens_out // len(task_ids)
    per_task_cost = cost_usd / len(task_ids)
    for task_id in task_ids:
        manifest = _write_track_b_manifest(
            destination / f"{task_id}.json",
            task_id=task_id,
            provider=provider,
            model=model,
            objective_pass=task_id in objective_met_tasks,
            behavior_preserving=_BEHAVIOR_PRESERVING[task_id],
            tokens_in=per_task_tokens,
            tokens_out=per_task_tokens_out,
            cost_usd=per_task_cost,
        )
        manifest_name = f"{task_id}.json"
        tasks[task_id] = {
            "skipped": False,
            "manifest": manifest_name,
            "objective_pass": manifest["objective_pass"],
            "disqualified": False,
            "budget_exceeded": None,
            "tokens_in": manifest["tokens_in"],
            "tokens_out": manifest["tokens_out"],
            "cost_usd": manifest["cost_usd"],
            "ppa_delta": manifest["ppa_delta"],
        }
    attempted = len(task_ids)
    objective_met = len(objective_met_tasks)
    summary = {
        "summary_version": "v1",
        "suite_version": "v0.2",
        "track": "B",
        "provider": provider,
        "model": model,
        "official": True,
        "task_ids": task_ids,
        "tasks": tasks,
        "tasks_attempted": attempted,
        "tasks_objective_met": objective_met,
        "objective_met_rate": objective_met / attempted if attempted else 0.0,
        "median_ppa_delta": {
            "area_ratio": None,
            "power_ratio": None,
            "wns_delta_ns": None,
        },
        "tokens_in": per_task_tokens * len(task_ids),
        "tokens_out": per_task_tokens_out * len(task_ids),
        "cost_usd": per_task_cost * len(task_ids),
        "pre_run_estimate_usd": cost_usd,
        "timestamp": "2026-01-02T00:00:00Z",
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    (destination / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )


def _build_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    tasks = tmp_path / "tasks"
    agent_tasks = tmp_path / "tasksB"
    refs = tmp_path / "refs"
    mutations = tmp_path / "mutation"
    evaluations = tmp_path / "eval"
    agent_evaluations = tmp_path / "evalB"
    _write_task(tasks, TRACK_A_TASK_1, "T1", True, "AAAAAAAA-BBBB-CCCC-DDDD-000000000001")
    _write_task(tasks, TRACK_A_TASK_2, "T1", False, "AAAAAAAA-BBBB-CCCC-DDDD-000000000002")
    _write_agent_task(agent_tasks, TRACK_B_TASK_1)
    _write_agent_task(agent_tasks, TRACK_B_TASK_2)

    refs.mkdir()
    manifest = json.loads(
        (TRACK_A_FIXTURE / "t1_gray_counter" / "sample_1.json").read_text(encoding="utf-8")
    )
    manifest["task_id"] = TRACK_A_TASK_1
    manifest["signature"] = compute_manifest_signature(manifest)
    (refs / f"{TRACK_A_TASK_1}.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    mutations.mkdir()
    (mutations / "cert-001.json").write_text(
        json.dumps(
            {"task": TRACK_A_TASK_1, "total": 4, "killed": 3, "kill_rate": 75.0},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    # Both tasks pass -> aggregate is exactly the per-task passing score.
    _write_track_a_summary(
        evaluations,
        run_name="official",
        provider="mock",
        model="model-one",
        task_ids=[TRACK_A_TASK_1, TRACK_A_TASK_2],
    )
    _write_track_a_summary(
        evaluations,
        run_name="diagnostic",
        provider="mock",
        model="model-one",
        task_ids=[TRACK_A_TASK_1],
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="official",
        provider="provider-z",
        model="model-zeta",
        task_ids=[TRACK_B_TASK_1, TRACK_B_TASK_2],
        objective_met_tasks=frozenset({TRACK_B_TASK_1}),
        tokens_in=300,
        tokens_out=75,
        cost_usd=0.02,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="official",
        provider="provider-b",
        model="model-beta",
        task_ids=[TRACK_B_TASK_1, TRACK_B_TASK_2],
        objective_met_tasks=frozenset({TRACK_B_TASK_1, TRACK_B_TASK_2}),
        tokens_in=250,
        tokens_out=50,
        cost_usd=0.015,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="official",
        provider="provider-a",
        model="model-alpha",
        task_ids=[TRACK_B_TASK_1, TRACK_B_TASK_2],
        objective_met_tasks=frozenset({TRACK_B_TASK_2}),
        tokens_in=100,
        tokens_out=25,
        cost_usd=0.01,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="diagnostic",
        provider="provider-b",
        model="model-beta",
        task_ids=[TRACK_B_TASK_1],
        objective_met_tasks=frozenset({TRACK_B_TASK_1}),
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.000001,
    )
    return tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks


def test_all_tables_match_golden_files(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    output = tmp_path / "output"
    generated = generate_tables(
        out_dir=output,
        tasks_root=tasks,
        refs_dir=refs,
        mutation_dir=mutations,
        eval_dir=evaluations,
        agent_eval_dir=agent_evaluations,
        agent_tasks_root=agent_tasks,
        generated_date=date(2026, 1, 2),
        git_sha="abc123def456",
    )
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.mkdir(parents=True, exist_ok=True)
        for name, path in generated.items():
            shutil.copyfile(path, GOLDEN / name)

    assert set(generated) == {path.name for path in GOLDEN.iterdir() if path.is_file()}
    for name, path in generated.items():
        assert path.read_bytes() == (GOLDEN / name).read_bytes()


def test_tampered_eval_summary_is_refused(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    summary_path = next(evaluations.glob("**/summary.json"))
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["aggregate_mean"] = 99.0
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="tampered"):
        generate_tables(
            out_dir=tmp_path / "output",
            tasks_root=tasks,
            refs_dir=refs,
            mutation_dir=mutations,
            eval_dir=evaluations,
            agent_eval_dir=agent_evaluations,
            agent_tasks_root=agent_tasks,
            generated_date=date(2026, 1, 2),
            git_sha="abc123def456",
        )


def test_eval_summary_with_untouched_children_but_forged_aggregate_is_refused(
    tmp_path: Path,
) -> None:
    """GTFS-034's exact reproduction: only summary.json's own claimed totals are
    changed, every signed child manifest is left byte-for-byte untouched."""

    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    summary_path = evaluations / "official" / "model-one" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["aggregate_mean"] = 99.0
    raw["tokens_in"] = 1
    raw["tokens_out"] = 1
    raw["cost_usd"] = 999.0
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="aggregate_mean"):
        load_evaluations(
            evaluations, frozenset({TRACK_A_TASK_1, TRACK_A_TASK_2})
        )


def test_agent_summary_with_untouched_children_but_forged_totals_is_refused(
    tmp_path: Path,
) -> None:
    """Same reproduction, Track B: only summary.json's claimed objective/PPA/cost
    totals move; every signed child manifest is untouched."""

    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    summary_path = agent_evaluations / "official" / "provider-z" / "model-zeta" / "summary.json"
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["tasks_objective_met"] = 2
    raw["objective_met_rate"] = 1.0
    raw["cost_usd"] = 999.0
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="tasks_objective_met"):
        load_agent_evaluations(
            agent_evaluations, frozenset({TRACK_B_TASK_1, TRACK_B_TASK_2})
        )


def test_agent_evaluations_are_sorted_and_extract_tokens(tmp_path: Path) -> None:
    *_, agent_evaluations, agent_tasks = _build_fixture(tmp_path)

    expected = frozenset(path.parent.name for path in agent_tasks.glob("*/objective.yaml"))
    rows = load_agent_evaluations(agent_evaluations, expected)

    assert [row.model for row in rows] == [
        "model-beta",
        "model-alpha",
        "model-zeta",
    ]
    assert [row.tokens for row in rows] == [300, 124, 374]


def test_complete_runs_win_over_partial_diagnostics(tmp_path: Path) -> None:
    tasks, _, _, evaluations, agent_evaluations, agent_tasks = _build_fixture(tmp_path)
    track_a_ids = frozenset(path.parent.name for path in tasks.glob("*/task.yaml"))
    track_b_ids = frozenset(
        path.parent.name for path in agent_tasks.glob("*/objective.yaml")
    )

    track_a_rows = load_evaluations(evaluations, track_a_ids)
    track_b_rows = load_agent_evaluations(agent_evaluations, track_b_ids)

    assert [(row.model, row.tasks, round(row.aggregate_score, 4)) for row in track_a_rows] == [
        ("model-one", 2, round(66.66666666666667, 4))
    ]
    assert [row.model for row in track_b_rows].count("model-beta") == 1
    beta = next(row for row in track_b_rows if row.model == "model-beta")
    assert (beta.tasks_attempted, beta.tasks_objective_met) == (2, 2)


def test_duplicate_complete_official_run_raises_instead_of_picking_one(
    tmp_path: Path,
) -> None:
    """A second, fully complete official summary for the same (provider, model)
    is always either an archival copy or a mistake -- the generator must refuse
    rather than silently pick the lexicographically-last one (the actual
    incident this regression covers, SB-114: a preserved sensitivity-run copy
    of a model briefly outranked the restored real official run)."""

    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    # _build_fixture's "official" run for model-one already covers both tasks
    # (complete); add a second, equally complete run under a different path.
    _write_track_a_summary(
        evaluations,
        run_name="archived-copy",
        provider="mock",
        model="model-one",
        task_ids=[TRACK_A_TASK_1, TRACK_A_TASK_2],
    )

    with pytest.raises(TableDataError, match="ambiguous Track A official run") as exc_info:
        generate_tables(
            out_dir=tmp_path / "output",
            tasks_root=tasks,
            refs_dir=refs,
            mutation_dir=mutations,
            eval_dir=evaluations,
            agent_eval_dir=agent_evaluations,
            agent_tasks_root=agent_tasks,
            generated_date=date(2026, 1, 2),
            git_sha="abc123def456",
        )
    message = str(exc_info.value)
    assert "official/model-one" in message
    assert "archived-copy/model-one" in message


def test_duplicate_complete_track_b_official_run_raises(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="archived-copy",
        provider="provider-b",
        model="model-beta",
        task_ids=[TRACK_B_TASK_1, TRACK_B_TASK_2],
        objective_met_tasks=frozenset({TRACK_B_TASK_1, TRACK_B_TASK_2}),
        tokens_in=250,
        tokens_out=50,
        cost_usd=0.015,
    )

    with pytest.raises(TableDataError, match="ambiguous Track B official run"):
        generate_tables(
            out_dir=tmp_path / "output",
            tasks_root=tasks,
            refs_dir=refs,
            mutation_dir=mutations,
            eval_dir=evaluations,
            agent_eval_dir=agent_evaluations,
            agent_tasks_root=agent_tasks,
            generated_date=date(2026, 1, 2),
            git_sha="abc123def456",
        )


def test_mutation_loader_ignores_a_stray_file_outside_the_scoped_directory(
    tmp_path: Path,
) -> None:
    """results/mutation/ has held ad hoc determinism-check repeats (repeat_a.json,
    repeat_b.json) alongside the real certification/ directory before. Pointing
    the loader at certification/ specifically -- and reading it non-recursively
    -- must not see a sibling file, even one with a colliding task id."""

    root = tmp_path / "mutation"
    certification = root / "certification"
    certification.mkdir(parents=True)
    (certification / "t1_alpha.json").write_text(
        json.dumps({"task": "t1_alpha", "total": 10, "killed": 10, "kill_rate": 100.0}),
        encoding="utf-8",
    )
    (root / "repeat_a.json").write_text(
        json.dumps({"task": "t1_alpha", "total": 8, "killed": 8, "kill_rate": 100.0}),
        encoding="utf-8",
    )

    rows = load_mutations(certification)

    assert len(rows) == 1
    assert rows[0].mutants == 10


def test_mutation_loader_rejects_two_files_claiming_the_same_task(
    tmp_path: Path,
) -> None:
    certification = tmp_path / "certification"
    certification.mkdir()
    (certification / "a.json").write_text(
        json.dumps({"task": "t1_alpha", "total": 10, "killed": 10, "kill_rate": 100.0}),
        encoding="utf-8",
    )
    (certification / "b.json").write_text(
        json.dumps({"task": "t1_alpha", "total": 8, "killed": 8, "kill_rate": 100.0}),
        encoding="utf-8",
    )

    with pytest.raises(TableDataError, match="duplicate mutation certification"):
        load_mutations(certification)


def test_mutation_loader_rejects_a_non_ok_status_report(tmp_path: Path) -> None:
    certification = tmp_path / "certification"
    certification.mkdir()
    (certification / "t1_alpha.json").write_text(
        json.dumps(
            {
                "task": "t1_alpha",
                "status": "setup_error",
                "total": 0,
                "killed": 0,
                "kill_rate": 0.0,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(TableDataError, match="status='setup_error'"):
        load_mutations(certification)


def test_mutation_loader_ignores_the_summary_file(tmp_path: Path) -> None:
    certification = tmp_path / "certification"
    certification.mkdir()
    (certification / "t1_alpha.json").write_text(
        json.dumps({"task": "t1_alpha", "total": 10, "killed": 10, "kill_rate": 100.0}),
        encoding="utf-8",
    )
    (certification / "summary.json").write_text(
        json.dumps({"all_above_floor": True, "tasks": {}}),
        encoding="utf-8",
    )

    rows = load_mutations(certification)

    assert len(rows) == 1


def test_partial_only_run_warns_and_is_omitted(tmp_path: Path, capsys) -> None:
    evaluations = tmp_path / "eval"
    _write_track_a_summary(
        evaluations,
        run_name="diagnostic",
        provider="mock",
        model="partial-only",
        task_ids=[TRACK_A_TASK_1],
    )

    assert load_evaluations(
        evaluations,
        frozenset({TRACK_A_TASK_1, TRACK_A_TASK_2}),
    ) == []
    warning = capsys.readouterr().err
    assert "warning: omitted Track A mock/partial-only" in warning
    assert "no complete official run" in warning


def test_track_a_tampered_task_manifest_omits_run(tmp_path: Path, capsys) -> None:
    tasks, _, _, evaluations, _, _ = _build_fixture(tmp_path)
    manifest_path = (
        evaluations
        / "official"
        / "model-one"
        / TRACK_A_TASK_1
        / "sample_1.json"
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["task_score"] = 99.0
    manifest_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    expected = frozenset(path.parent.name for path in tasks.glob("*/task.yaml"))

    assert load_evaluations(evaluations, expected) == []
    assert "manifest is missing or invalid" in capsys.readouterr().err


def test_track_b_tampered_task_manifest_omits_run(tmp_path: Path, capsys) -> None:
    *_, agent_evaluations, agent_tasks = _build_fixture(tmp_path)
    manifest_path = (
        agent_evaluations
        / "official"
        / "provider-b"
        / "model-beta"
        / f"{TRACK_B_TASK_1}.json"
    )
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["task_score"] = 99.0
    manifest_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    expected = frozenset(
        path.parent.name for path in agent_tasks.glob("*/objective.yaml")
    )

    rows = load_agent_evaluations(agent_evaluations, expected)

    assert "model-beta" not in {row.model for row in rows}
    assert "manifest is missing or invalid" in capsys.readouterr().err


def test_tampered_agent_eval_summary_is_refused(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    summary_path = next(agent_evaluations.glob("**/summary.json"))
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["tasks_objective_met"] = 0
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(TableDataError, match="tampered agent eval"):
        generate_tables(
            out_dir=tmp_path / "output",
            tasks_root=tasks,
            refs_dir=refs,
            mutation_dir=mutations,
            eval_dir=evaluations,
            agent_eval_dir=agent_evaluations,
            agent_tasks_root=agent_tasks,
            generated_date=date(2026, 1, 2),
            git_sha="abc123def456",
        )


def test_script_entrypoint_bootstraps_repo_imports(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = (
        _build_fixture(tmp_path)
    )
    output = tmp_path / "cli-output"
    script = REPO_ROOT / "paper" / "data" / "generate_tables.py"
    preserved = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "HOME", "TMP", "TEMP"}
    clean_env = {
        key: value for key, value in os.environ.items() if key.upper() in preserved
    }
    clean_env["PYTHONNOUSERSITE"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--out",
            str(output),
            "--tasks-root",
            str(tasks),
            "--refs-dir",
            str(refs),
            "--from-dir",
            str(mutations),
            "--eval-dir",
            str(evaluations),
            "--agent-eval-dir",
            str(agent_evaluations),
            "--agent-tasks-root",
            str(agent_tasks),
            "--date",
            "2026-01-02",
        ],
        cwd=tmp_path,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert sorted(path.name for path in output.iterdir()) == [
        "eval_table.md",
        "eval_table.tex",
        "mutation_table.md",
        "mutation_table.tex",
        "tasks_table.md",
        "tasks_table.tex",
        "trackb_table.md",
        "trackb_table.tex",
    ]
    eval_table = (output / "eval_table.md").read_text(encoding="utf-8")
    assert "| mock | model-one | 2 | 66.67 |" in eval_table
    trackb_table = (output / "trackb_table.md").read_text(encoding="utf-8")
    assert "| provider-b | model-beta | 2/2 | 100.00% |" in trackb_table


def test_git_sha_delegates_to_harness_git_not_its_own_implementation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """generate_tables.py used to shell out to plain `git rev-parse` itself, which
    refuses to run at all ("detected dubious ownership") whenever the repo is owned by
    a different user than the one running it -- exactly every sandboxed docker run in
    this project. That made every real table generated inside the pinned sandbox this
    project mandates silently carry "git-sha: unknown". Fixed by deleting that
    duplicate, inferior implementation entirely and delegating to
    harness.git_provenance.harness_git(), which already has its own dedicated test
    suite (harness/tests/test_git_provenance.py) covering the dubious-ownership case
    directly. This test only proves the delegation actually happened -- an env var
    harness_git() honors changes what generate_tables() writes, which a leftover local
    reimplementation would not react to.

    This also documents a real, separate limitation surfaced while verifying this fix
    by hand: a `git archive` snapshot (docs/SECURE_EXECUTION.md's own staging
    convention, used by ci.yml/pages.yml/nightly.yml) has no .git/ at all, so no git
    invocation -- dubious-ownership-safe or not -- can recover a real sha there. Real
    provenance in that environment requires GATETRUTH_GIT_COMMIT or GITHUB_SHA to be
    passed through to the container, which harness_git() already checks first."""

    monkeypatch.delenv("GATETRUTH_GIT_COMMIT", raising=False)
    monkeypatch.delenv("SILICONBENCH_GIT_COMMIT", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.setenv("GATETRUTH_GIT_COMMIT", "abc123def456abc123def456abc123def456abc")

    tasks, refs, mutations, evaluations, agent_evaluations, agent_tasks = _build_fixture(
        tmp_path
    )
    output = tmp_path / "out"
    generate_tables(
        out_dir=output,
        tasks_root=tasks,
        refs_dir=refs,
        mutation_dir=mutations,
        eval_dir=evaluations,
        agent_eval_dir=agent_evaluations,
        agent_tasks_root=agent_tasks,
        generated_date=date(2026, 1, 2),
    )

    assert "git-sha: abc123def456abc123def456abc123def456abc" in (
        output / "eval_table.tex"
    ).read_text(encoding="utf-8")
