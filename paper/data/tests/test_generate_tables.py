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
from paper.data.generate_tables import TableDataError, generate_tables

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


def _build_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    tasks = tmp_path / "tasks"
    refs = tmp_path / "refs"
    mutations = tmp_path / "mutation"
    evaluations = tmp_path / "eval" / "smoke" / "model-one"
    _write_task(tasks, "t1_alpha", "T1", True, "AAAAAAAA-BBBB-CCCC-DDDD-000000000001")
    _write_task(tasks, "t2_beta", "T2", False, "AAAAAAAA-BBBB-CCCC-DDDD-000000000002")

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

    evaluations.mkdir(parents=True)
    summary = {
        "aggregate_mean": 12.5,
        "cost_usd": 0.00125,
        "model": "model-one",
        "provider": "mock",
        "tasks": {"t1_alpha": {"skipped": False}},
        "tokens_in": 100,
        "tokens_out": 25,
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    (evaluations / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return tasks, refs, mutations, tmp_path / "eval"


def test_all_tables_match_golden_files(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations = _build_fixture(tmp_path)
    output = tmp_path / "output"
    generated = generate_tables(
        out_dir=output,
        tasks_root=tasks,
        refs_dir=refs,
        mutation_dir=mutations,
        eval_dir=evaluations,
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
    tasks, refs, mutations, evaluations = _build_fixture(tmp_path)
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
            generated_date=date(2026, 1, 2),
            git_sha="abc123def456",
        )


def test_script_entrypoint_bootstraps_repo_imports(tmp_path: Path) -> None:
    tasks, refs, mutations, evaluations = _build_fixture(tmp_path)
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
    ]
    assert "| mock | model-one | 1 | 12.50 | 125 | 0.001250 |" in (
        output / "eval_table.md"
    ).read_text(encoding="utf-8")
