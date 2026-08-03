"""Regression tests for the failure-taxonomy generator and its lint diagnostics ledger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.schemas.canonical_json import compute_manifest_signature
from paper.data.generate_failure_taxonomy import TaxonomyDataError, collect, summarize
from scripts.generate_lint_diagnostics_ledger import generate_ledger

DOCKER_DIGEST = "sha256:" + "ab" * 32
MODELS = [
    "claude-opus-4-8",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "gpt-5",
    "gpt-5-mini",
    "google_gemini-2.5-pro",
    "meta-llama_llama-4-maverick",
]


_STAGE_IDS = {"lint": 0, "sim": 1, "formal": 2, "synth": 3, "sta": 4, "power": 5, "route": 6}
_PASS_METRICS = {
    "lint": {"warnings": 0},
    "sim": {"tests_run": 8, "tests_passed": 8},
    "formal": {},
    "synth": {"area_um2": 100.0, "cell_count": 10},
    "sta": {"wns_ns": 1.0, "tns_ns": 0.0, "fmax_mhz": 500.0},
    "power": {"power_mw": 0.5},
}


def _stage(name: str, status: str) -> dict:
    metrics = _PASS_METRICS[name] if status == "pass" else {}
    return {"stage": _STAGE_IDS[name], "name": name, "status": status, **metrics}


def _all_stages(first_fail: str | None) -> list[dict]:
    order = ["lint", "sim", "formal", "synth", "sta", "power"]
    stages = []
    failed_yet = False
    for name in order:
        if failed_yet:
            stages.append(_stage(name, "fail"))
        elif name == first_fail:
            stages.append(_stage(name, "fail"))
            failed_yet = True
        else:
            stages.append(_stage(name, "pass"))
    stages.append(_stage("route", "skip"))
    return stages


def _write_sample(
    root: Path,
    *,
    model: str,
    task_id: str,
    task_score: float,
    ppa: float = 0.0,
    first_fail: str | None = None,
    generation_error: str | None = None,
    log_text: str | None = None,
) -> None:
    task_dir = root / model / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    if generation_error is not None:
        stages = _all_stages("lint") if task_score == 0 else _all_stages(None)
    else:
        stages = _all_stages(first_fail)
    raw = {
        "task_id": task_id,
        "suite_version": "v0.2",
        "docker_digest": DOCKER_DIGEST,
        "platform": "linux/amd64",
        "stages": stages,
        "sec": 1.0 if task_score > 0 else 0.0,
        "ppa": ppa,
        "task_score": task_score,
        "wall_clock_s": 1.0,
        "provider": "anthropic",
        "model": model,
        "temperature": 0.0,
        "tokens_in": 100,
        "tokens_out": 50,
        "cost_usd": 0.01,
        "prompt_version": "track-a-rtl-v1",
        "timestamp": "2026-07-30T12:00:00.000000Z",
    }
    if generation_error is not None:
        raw["generation_error"] = generation_error
    raw["signature"] = compute_manifest_signature(raw)
    (task_dir / "sample_1.json").write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    if log_text is not None:
        (task_dir / "sample_1.log").write_text(log_text, encoding="utf-8")


def _build_full_campaign(root: Path, ledger_path: Path, tasks_root: Path) -> None:
    """60 tasks x 7 models, all passing except a handful of engineered failures."""

    for i in range(60):
        tier = "t1" if i < 20 else "t2" if i < 40 else "t3"
        task_id = f"{tier}_task_{i:02d}"
        (tasks_root / task_id).mkdir(parents=True, exist_ok=True)
        (tasks_root / task_id / "task.yaml").write_text("id: " + task_id + "\n", encoding="utf-8")
        for model in MODELS:
            _write_sample(root, model=model, task_id=task_id, task_score=66.67, ppa=1.0)

    # overwrite a handful of pairs with engineered failures
    _write_sample(
        root,
        model="claude-opus-4-8",
        task_id="t1_task_00",
        task_score=0,
        generation_error="ValueError: generation contained an unterminated code fence",
    )
    _write_sample(
        root,
        model="claude-sonnet-4-6",
        task_id="t1_task_01",
        task_score=0,
        generation_error="provider error: ProviderTransportError: connection reset",
    )
    _write_sample(
        root,
        model="gpt-5",
        task_id="t2_task_20",
        task_score=0,
        first_fail="lint",
        log_text=(
            "%Warning-WIDTHEXPAND: bad.sv:1: expands\n"
            "                      ... For warning description see https://verilator.org/warn/WIDTHEXPAND\n"
            "%Error: Exiting due to 1 warning(s)\n"
        ),
    )
    _write_sample(
        root,
        model="gpt-5-mini",
        task_id="t2_task_21",
        task_score=0,
        first_fail="lint",
        log_text="%Error: Syntax error near 'endmodule'\n",
    )
    _write_sample(
        root,
        model="google_gemini-2.5-pro",
        task_id="t3_task_40",
        task_score=0,
        first_fail="sim",
    )
    _write_sample(
        root,
        model="meta-llama_llama-4-maverick",
        task_id="t3_task_41",
        task_score=0,
        first_fail="formal",
    )

    ledger = generate_ledger(root)
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture
def campaign(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "eval-16384"
    ledger_path = tmp_path / "ledger.json"
    tasks_root = tmp_path / "tasks"
    _build_full_campaign(root, ledger_path, tasks_root)
    return root, ledger_path, tasks_root


def test_collect_classifies_every_failure_mode(campaign: tuple[Path, Path, Path]) -> None:
    root, ledger_path, tasks_root = campaign
    data = collect(root, ledger_path, tasks_root=tasks_root)
    by_key = {(r["model"], r["task_id"]): r["category"] for r in data["rows"]}

    assert by_key[("claude-opus-4-8", "t1_task_00")] == "no_extraction"
    assert by_key[("claude-sonnet-4-6", "t1_task_01")] == "provider_error"
    assert by_key[("gpt-5", "t2_task_20")] == "lint_width_only"
    assert by_key[("gpt-5-mini", "t2_task_21")] == "lint_other"
    assert by_key[("google_gemini-2.5-pro", "t3_task_40")] == "sim"
    assert by_key[("meta-llama_llama-4-maverick", "t3_task_41")] == "formal"

    summary = summarize(data)
    assert summary["total_pairs"] == 420
    assert summary["failing_pairs"] == 6
    assert summary["no_extraction"] == 1
    assert summary["provider_error"] == 1
    assert summary["lint_width_only"] == 1
    assert summary["lint_other"] == 1
    assert summary["sim_fail"] == 1
    assert summary["formal_fail"] == 1


def test_unrecognized_generation_error_is_refused(campaign: tuple[Path, Path, Path]) -> None:
    root, ledger_path, tasks_root = campaign
    _write_sample(
        root,
        model="claude-opus-4-8",
        task_id="t1_task_02",
        task_score=0,
        generation_error="RuntimeError: something scoring-internal broke",
    )
    with pytest.raises(TaxonomyDataError, match="unrecognized generation_error prefix"):
        collect(root, ledger_path, tasks_root=tasks_root)


def test_lint_failure_missing_from_ledger_is_refused(campaign: tuple[Path, Path, Path]) -> None:
    root, ledger_path, tasks_root = campaign
    _write_sample(
        root,
        model="claude-opus-4-8",
        task_id="t1_task_03",
        task_score=0,
        first_fail="lint",
    )
    with pytest.raises(TaxonomyDataError, match="no lint_diagnostics_ledger entry"):
        collect(root, ledger_path, tasks_root=tasks_root)


def test_stale_ledger_entry_is_refused(campaign: tuple[Path, Path, Path]) -> None:
    root, ledger_path, tasks_root = campaign
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["pairs"]["claude-opus-4-8/t1_task_05"] = ["WIDTHTRUNC"]
    ledger_path.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(TaxonomyDataError, match="stale ledger"):
        collect(root, ledger_path, tasks_root=tasks_root)


def test_missing_model_is_refused(campaign: tuple[Path, Path, Path]) -> None:
    root, ledger_path, tasks_root = campaign
    import shutil

    shutil.rmtree(root / "gpt-5")
    with pytest.raises(TaxonomyDataError):
        collect(root, ledger_path, tasks_root=tasks_root)


def test_ppa_degeneracy_uses_a_tolerance(tmp_path: Path) -> None:
    root = tmp_path / "eval"
    tasks_root = tmp_path / "tasks2"
    for i in range(60):
        tier = "t1" if i < 20 else "t2" if i < 40 else "t3"
        task_id = f"{tier}_task_{i:02d}"
        (tasks_root / task_id).mkdir(parents=True, exist_ok=True)
        (tasks_root / task_id / "task.yaml").write_text("id: " + task_id + "\n", encoding="utf-8")
        for model in MODELS:
            close_but_not_exact = model == MODELS[0] and i == 0
            ppa = 1.0 + 1e-9 if close_but_not_exact else 0.9
            _write_sample(root, model=model, task_id=task_id, task_score=66.67, ppa=ppa)

    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps({"pairs": {}}), encoding="utf-8")

    data = collect(root, ledger_path, tasks_root=tasks_root)
    summary = summarize(data)
    degenerate, total_passed = summary["ppa_degenerate"]
    assert total_passed == 420
    # exactly one pair is within 1e-6 of 1.0; the rest sit at 0.9 and must not count.
    assert degenerate == 1
