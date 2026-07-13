"""Tests for the static leaderboard generator."""

from __future__ import annotations

import json
import re
import runpy
import shutil
from pathlib import Path
from typing import Any

import pytest

from harness.cli import _default_agent_output, main as cli_main
from harness.schemas.canonical_json import compute_manifest_signature

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / "fixtures" / "eval"
AGENT_FIXTURE = Path(__file__).parent / "fixtures" / "agent"
TASKS_B_FIXTURE = Path(__file__).parent / "fixtures" / "tasksB"
NAMESPACE = runpy.run_path(str(ROOT / "site" / "generate.py"))
generate_site = NAMESPACE["generate_site"]
SiteGenerationError = NAMESPACE["SiteGenerationError"]
CANARY_RE = re.compile(
    r"SILICONBENCH-CANARY-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-"
    r"[0-9A-F]{4}-[0-9A-F]{12}",
    re.IGNORECASE,
)


def _fixture_copy(tmp_path: Path) -> Path:
    target = tmp_path / "eval"
    shutil.copytree(FIXTURE, target)
    return target


def _all_fixture_copy(tmp_path: Path) -> tuple[Path, Path, Path]:
    eval_root = _fixture_copy(tmp_path)
    agent_root = tmp_path / "agent"
    tasks_root = tmp_path / "tasksB"
    shutil.copytree(AGENT_FIXTURE, agent_root)
    shutil.copytree(TASKS_B_FIXTURE, tasks_root)
    return eval_root, agent_root, tasks_root


def _summary(root: Path) -> Path:
    matches = list(root.glob("**/summary.json"))
    assert len(matches) == 1
    return matches[0]


def _artifact_bytes(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)).replace("\\", "/"): path.read_bytes()
        for path in sorted(item for item in root.rglob("*") if item.is_file())
    }


def test_real_haiku_smoke_renders_static_leaderboard(tmp_path: Path) -> None:
    results = _fixture_copy(tmp_path)
    output = tmp_path / "build"

    built = generate_site(results, output)

    assert set(built) == {
        "index.html",
        "leaderboard.json",
        "models/claude-haiku-4-5-20251001--smoke.html",
    }
    leaderboard = json.loads((output / "leaderboard.json").read_text(encoding="utf-8"))
    assert len(leaderboard["runs"]) == 1
    row = leaderboard["runs"][0]
    assert row["model"] == "claude-haiku-4-5-20251001"
    assert row["aggregate_score"] == pytest.approx(66.66666666666667)
    assert row["tasks_attempted"] == 1
    assert row["tasks_passed"] == 1
    assert row["cost_usd"] == pytest.approx(0.003268)
    assert row["badge"] == "DEV"
    index = (output / "index.html").read_text(encoding="utf-8")
    detail = (output / row["detail_page"]).read_text(encoding="utf-8")
    assert "claude-haiku-4-5-20251001" in index
    assert "66.67" in index
    assert "t1_gray_counter" in detail
    assert "lint: pass" in detail
    assert "power: pass" in detail


def test_build_has_no_canary_or_external_assets(tmp_path: Path) -> None:
    eval_root, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    output = tmp_path / "build"
    generate_site(
        eval_root,
        output,
        agent_results_root=agent_root,
        tasks_b_root=tasks_root,
    )

    for path in output.rglob("*"):
        if not path.is_file():
            continue
        content = path.read_text(encoding="utf-8")
        assert CANARY_RE.search(content) is None
        if path.suffix == ".html":
            lowered = content.lower()
            for forbidden in ("http://", "https://", "<script", "<link", "@import", "url("):
                assert forbidden not in lowered


@pytest.mark.parametrize("mode", ["tampered", "unsigned"])
def test_invalid_summary_is_refused_without_output(tmp_path: Path, mode: str) -> None:
    results = _fixture_copy(tmp_path)
    summary_path = _summary(results)
    raw: dict[str, Any] = json.loads(summary_path.read_text(encoding="utf-8"))
    if mode == "tampered":
        raw["aggregate_mean"] = 99.0
    else:
        raw.pop("signature")
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    output = tmp_path / "build"

    with pytest.raises(SiteGenerationError):
        generate_site(results, output)

    assert not output.exists()


def test_build_is_byte_deterministic_and_official_is_explicit(tmp_path: Path) -> None:
    results, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    summary_path = _summary(results)
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["official"] = True
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    first = tmp_path / "first"
    second = tmp_path / "second"

    generate_site(
        results,
        first,
        agent_results_root=agent_root,
        tasks_b_root=tasks_root,
    )
    generate_site(
        results,
        second,
        agent_results_root=agent_root,
        tasks_b_root=tasks_root,
    )

    assert _artifact_bytes(first) == _artifact_bytes(second)
    leaderboard = json.loads((first / "leaderboard.json").read_text(encoding="utf-8"))
    assert leaderboard["runs"][0]["badge"] == "OFFICIAL"
    assert leaderboard["track_b_runs"][0]["badge"] == "DEV"


def test_cli_site_subcommand(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    results, agent_root, _ = _all_fixture_copy(tmp_path)
    output = tmp_path / "build"

    assert cli_main(
        [
            "site",
            "--results",
            str(results),
            "--agent-results",
            str(agent_root),
            "--out",
            str(output),
        ]
    ) == 0

    stdout = capsys.readouterr().out
    assert str(output / "index.html") in stdout
    assert (output / "leaderboard.json").is_file()
    assert (output / "agents/claude-haiku-4-5-20251001--smoke.html").is_file()


def test_track_b_real_smoke_metadata_renders(tmp_path: Path) -> None:
    eval_root, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    output = tmp_path / "build"

    generate_site(
        eval_root,
        output,
        agent_results_root=agent_root,
        tasks_b_root=tasks_root,
    )

    leaderboard = json.loads((output / "leaderboard.json").read_text(encoding="utf-8"))
    assert len(leaderboard["track_b_runs"]) == 1
    row = leaderboard["track_b_runs"][0]
    assert row == {
        "badge": "DEV",
        "budget_exceeded": "tokens",
        "cost_usd": 0.00215,
        "detail_page": "agents/claude-haiku-4-5-20251001--smoke.html",
        "disqualified": False,
        "model": "claude-haiku-4-5-20251001",
        "objective_pass": False,
        "official": False,
        "provider": "anthropic",
        "run_date": "2026-07-13T08:09:37.476300Z",
        "run_id": "smoke",
        "signature": "fa79d234d86fbed6be6d57c3353635107a6759c04102bfa79d2b3f3ef6a59b6e",
        "task_id": "toy_taskB",
        "tokens_in": 1000,
        "tokens_out": 230,
    }
    index = (output / "index.html").read_text(encoding="utf-8")
    detail = (output / row["detail_page"]).read_text(encoding="utf-8")
    assert "Track B (agentic)" in index
    assert "toy_taskB" in index
    assert "area_reduction" in detail
    assert "pass" in detail
    assert "1.0000x" in detail
    assert "+0.0000 ns" in detail


def test_tampered_track_b_manifest_refuses_without_output(tmp_path: Path) -> None:
    eval_root, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    manifest_path = next(agent_root.glob("**/toy_taskB.json"))
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw["cost_usd"] = 99.0
    manifest_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    output = tmp_path / "build"

    with pytest.raises(SiteGenerationError):
        generate_site(
            eval_root,
            output,
            agent_results_root=agent_root,
            tasks_b_root=tasks_root,
        )

    assert not output.exists()


def test_track_b_official_requires_both_signed_reviews(tmp_path: Path) -> None:
    eval_root, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    task_yaml = tasks_root / "toy_taskB" / "task.yaml"
    text = task_yaml.read_text(encoding="utf-8")
    text = text.replace("baseline_review: PENDING", "baseline_review: SIGNED-OFF-BY-MEET-2026-07-13")
    text = text.replace("tb_review: PENDING", "tb_review: SIGNED-OFF-BY-MEET-2026-07-13")
    task_yaml.write_text(text, encoding="utf-8")
    output = tmp_path / "build"

    generate_site(
        eval_root,
        output,
        agent_results_root=agent_root,
        tasks_b_root=tasks_root,
    )

    leaderboard = json.loads((output / "leaderboard.json").read_text(encoding="utf-8"))
    assert leaderboard["track_b_runs"][0]["badge"] == "OFFICIAL"


def test_run_agent_default_path_uses_canonical_layout() -> None:
    assert _default_agent_output("smoke", "anthropic/haiku", "toy_taskB") == Path(
        "results/agent/smoke/anthropic_haiku/toy_taskB.json"
    )
