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
from paper.data.generate_tables import (
    TableDataError,
    _git_sha,
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
TRACK_B_FIXTURE = (
    REPO_ROOT
    / "site"
    / "tests"
    / "fixtures"
    / "agent"
    / "smoke"
    / "claude-haiku-4-5-20251001"
    / "toy_taskB.json"
)
CANARY_PREFIX = "SILICONBENCH-" + "CANARY-"


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
) -> dict:
    raw = json.loads(
        (TRACK_A_FIXTURE / "t1_gray_counter" / "sample_1.json").read_text(
            encoding="utf-8"
        )
    )
    raw.update(task_id=task_id, provider=provider, model=model)
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
    aggregate_score: float,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    destination = root / run_name / model
    tasks: dict[str, dict] = {}
    for task_id in task_ids:
        relative = f"{task_id}/sample_1.json"
        manifest = _write_track_a_manifest(
            destination / relative,
            task_id=task_id,
            provider=provider,
            model=model,
        )
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
        "aggregate_mean": aggregate_score,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "pre_run_estimate_usd": cost_usd,
        "timestamp": "2026-01-02T00:00:00Z",
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    (destination / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_agent_summary(
    root: Path,
    *,
    run_name: str,
    provider: str,
    model: str,
    task_ids: list[str],
    objective_met: int,
    area_ratio: float | None,
    power_ratio: float | None,
    wns_delta_ns: float | None,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
) -> None:
    destination = root / run_name / provider / model
    destination.mkdir(parents=True)
    tasks: dict[str, dict] = {}
    for task_id in task_ids:
        manifest = json.loads(TRACK_B_FIXTURE.read_text(encoding="utf-8"))
        manifest.update(task_id=task_id, provider=provider, model=model)
        manifest["signature"] = compute_manifest_signature(manifest)
        manifest_name = f"{task_id}.json"
        (destination / manifest_name).write_text(
            json.dumps(manifest, indent=2) + "\n",
            encoding="utf-8",
        )
        tasks[task_id] = {
            "skipped": False,
            "manifest": manifest_name,
            "objective_pass": False,
            "disqualified": False,
            "budget_exceeded": None,
            "tokens_in": manifest["tokens_in"],
            "tokens_out": manifest["tokens_out"],
            "cost_usd": manifest["cost_usd"],
            "ppa_delta": manifest["ppa_delta"],
        }
    attempted = len(task_ids)
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
            "area_ratio": area_ratio,
            "power_ratio": power_ratio,
            "wns_delta_ns": wns_delta_ns,
        },
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
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
    _write_task(tasks, "t1_alpha", "T1", True, "AAAAAAAA-BBBB-CCCC-DDDD-000000000001")
    _write_task(tasks, "t2_beta", "T2", False, "AAAAAAAA-BBBB-CCCC-DDDD-000000000002")
    _write_agent_task(agent_tasks, "b1_alpha")
    _write_agent_task(agent_tasks, "b2_beta")

    refs.mkdir()
    manifest = json.loads(
        (TRACK_A_FIXTURE / "t1_gray_counter" / "sample_1.json").read_text(encoding="utf-8")
    )
    manifest["task_id"] = "t1_alpha"
    manifest["signature"] = compute_manifest_signature(manifest)
    (refs / "t1_alpha.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    mutations.mkdir()
    (mutations / "cert-001.json").write_text(
        json.dumps(
            {"task": "t1_alpha", "total": 4, "killed": 3, "kill_rate": 75.0},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    _write_track_a_summary(
        evaluations,
        run_name="official",
        provider="mock",
        model="model-one",
        task_ids=["t1_alpha", "t2_beta"],
        aggregate_score=12.5,
        tokens_in=100,
        tokens_out=25,
        cost_usd=0.00125,
    )
    _write_track_a_summary(
        evaluations,
        run_name="diagnostic",
        provider="mock",
        model="model-one",
        task_ids=["t1_alpha"],
        aggregate_score=99.0,
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.0001,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="official",
        provider="provider-z",
        model="model-zeta",
        task_ids=["b1_alpha", "b2_beta"],
        objective_met=1,
        area_ratio=0.8,
        power_ratio=None,
        wns_delta_ns=-0.125,
        tokens_in=300,
        tokens_out=75,
        cost_usd=0.02,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="official",
        provider="provider-b",
        model="model-beta",
        task_ids=["b1_alpha", "b2_beta"],
        objective_met=2,
        area_ratio=0.75,
        power_ratio=0.7,
        wns_delta_ns=0.5,
        tokens_in=250,
        tokens_out=50,
        cost_usd=0.015,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="official",
        provider="provider-a",
        model="model-alpha",
        task_ids=["b1_alpha", "b2_beta"],
        objective_met=1,
        area_ratio=None,
        power_ratio=0.9,
        wns_delta_ns=0.25,
        tokens_in=100,
        tokens_out=25,
        cost_usd=0.01,
    )
    _write_agent_summary(
        agent_evaluations,
        run_name="diagnostic",
        provider="provider-b",
        model="model-beta",
        task_ids=["b1_alpha"],
        objective_met=1,
        area_ratio=0.1,
        power_ratio=0.1,
        wns_delta_ns=9.0,
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


def test_agent_evaluations_are_sorted_and_extract_tokens(tmp_path: Path) -> None:
    *_, agent_evaluations, agent_tasks = _build_fixture(tmp_path)

    expected = frozenset(path.parent.name for path in agent_tasks.glob("*/objective.yaml"))
    rows = load_agent_evaluations(agent_evaluations, expected)

    assert [row.model for row in rows] == [
        "model-beta",
        "model-alpha",
        "model-zeta",
    ]
    assert [row.tokens for row in rows] == [300, 125, 375]


def test_complete_runs_win_over_partial_diagnostics(tmp_path: Path) -> None:
    tasks, _, _, evaluations, agent_evaluations, agent_tasks = _build_fixture(tmp_path)
    track_a_ids = frozenset(path.parent.name for path in tasks.glob("*/task.yaml"))
    track_b_ids = frozenset(
        path.parent.name for path in agent_tasks.glob("*/objective.yaml")
    )

    track_a_rows = load_evaluations(evaluations, track_a_ids)
    track_b_rows = load_agent_evaluations(agent_evaluations, track_b_ids)

    assert [(row.model, row.tasks, row.aggregate_score) for row in track_a_rows] == [
        ("model-one", 2, 12.5)
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
        task_ids=["t1_alpha", "t2_beta"],
        aggregate_score=31.06,
        tokens_in=999,
        tokens_out=999,
        cost_usd=3.43,
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
        task_ids=["b1_alpha", "b2_beta"],
        objective_met=2,
        area_ratio=0.75,
        power_ratio=0.7,
        wns_delta_ns=0.5,
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
        task_ids=["t1_alpha"],
        aggregate_score=99.0,
        tokens_in=10,
        tokens_out=5,
        cost_usd=0.0001,
    )

    assert load_evaluations(
        evaluations,
        frozenset({"t1_alpha", "t2_beta"}),
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
        / "t1_alpha"
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
        / "b1_alpha.json"
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
        timeout=30,
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
    assert "| mock | model-one | 2 | 12.50 | 125 | 0.001250 |" in (
        output / "eval_table.md"
    ).read_text(encoding="utf-8")
    assert "| provider-b | model-beta | 2/2 | 100.00% |" in (
        output / "trackb_table.md"
    ).read_text(encoding="utf-8")


def test_git_sha_resolves_the_real_commit_even_under_dubious_ownership():
    """_git_sha() used to shell out to plain `git rev-parse`, which refuses to run at
    all ("detected dubious ownership") whenever the repo is owned by a different user
    than the one running it -- exactly the situation every sandboxed docker run in
    this project is in (the bind mount is owned by the host user, not the container's
    uid 10001). That made every table generated inside the actual pinned sandbox this
    project mandates silently carry "git-sha: unknown", while a plain host run (owner
    matches, no dubious-ownership refusal) looked fine -- backwards for a provenance
    field, since the sandboxed run is the one whose output should be trusted. Verified
    the bug directly against a real sandboxed docker run before fixing this."""

    sha = _git_sha(REPO_ROOT)

    assert sha != "unknown"
    assert len(sha) == 12
    assert all(c in "0123456789abcdef" for c in sha)
    expected = subprocess.run(
        ["git", "-c", f"safe.directory={REPO_ROOT}", "rev-parse", "--short=12", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert sha == expected
