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
LeaderboardRow = NAMESPACE["LeaderboardRow"]
_reject_duplicate_detail_pages = NAMESPACE["_reject_duplicate_detail_pages"]
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


def _patch_canonical_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_ids: list[str]
) -> None:
    tasks_root = tmp_path / "canonical-tasks"
    for task_id in task_ids:
        task_dir = tasks_root / task_id
        task_dir.mkdir(parents=True)
        (task_dir / "task.yaml").write_text(f"id: {task_id}\n", encoding="utf-8")
    # runpy.run_path's returned namespace is a *copy*: the functions it defines keep
    # their own __globals__ dict, distinct from NAMESPACE, so patching NAMESPACE
    # directly is silently ineffective -- patch the real globals via any function
    # object pulled from it instead.
    monkeypatch.setitem(generate_site.__globals__, "TASKS_ROOT", tasks_root)


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
            for forbidden in (
                "<script src",
                "<link",
                "@import",
                "url(",
            ):
                assert forbidden not in lowered


def test_index_bundles_onboarding_tour_and_all_six_targets(tmp_path: Path) -> None:
    eval_root, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    output = tmp_path / "build"
    generate_site(
        eval_root,
        output,
        agent_results_root=agent_root,
        tasks_b_root=tasks_root,
    )

    index = (output / "index.html").read_text(encoding="utf-8")
    for target in (
        "silicon-score",
        "score-columns",
        "tier-toggle",
        "track-tabs",
        "submit-model",
        "methodology",
    ):
        assert f'data-tour="{target}"' in index
    assert 'const seenKey="has_seen_tour"' in index
    assert "localStorage.setItem(seenKey,\"true\")" in index
    assert "getBoundingClientRect()" in index
    assert "<script src" not in index.lower()


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


def test_build_is_byte_deterministic_and_official_is_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    results, agent_root, tasks_root = _all_fixture_copy(tmp_path)
    summary_path = _summary(results)
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["official"] = True
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    _patch_canonical_tasks(tmp_path, monkeypatch, raw["task_ids"])
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


def test_official_badge_requires_full_canonical_suite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run marked official=true over a strict subset of the canonical Track A
    suite must not wear the OFFICIAL badge: a partial run is not full-suite
    coverage, regardless of what its own official flag claims."""

    results = _fixture_copy(tmp_path)
    summary_path = _summary(results)
    raw = json.loads(summary_path.read_text(encoding="utf-8"))
    raw["official"] = True
    raw["signature"] = compute_manifest_signature(raw)
    summary_path.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    _patch_canonical_tasks(tmp_path, monkeypatch, [*raw["task_ids"], "t1_extra_task"])
    output = tmp_path / "build"

    generate_site(results, output)

    leaderboard = json.loads((output / "leaderboard.json").read_text(encoding="utf-8"))
    assert leaderboard["runs"][0]["badge"] == "DEV"


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


def _row(*, model: str, run_id: str, detail_page: str) -> LeaderboardRow:
    return LeaderboardRow(
        run_id=run_id,
        provider="anthropic",
        model=model,
        prompt_version="track-a-rtl-v1",
        aggregate_score=50.0,
        pass_at_1=80.0,
        mean_ppa=1.0,
        tasks_attempted=1,
        tasks_passed=1,
        tokens_in=1,
        tokens_out=1,
        cost_usd=0.0,
        run_date="2026-01-01T00:00:00Z",
        official=False,
        signature="0" * 64,
        detail_page=detail_page,
        tasks=(),
    )


def test_distinct_runs_with_distinct_detail_pages_are_accepted() -> None:
    rows = [
        _row(model="claude-opus-4-8", run_id="a", detail_page="models/opus--a.html"),
        _row(model="claude-opus-4-8", run_id="b", detail_page="models/opus--b.html"),
    ]
    _reject_duplicate_detail_pages(rows)  # must not raise


def test_two_different_runs_colliding_on_one_detail_page_are_refused() -> None:
    rows = [
        _row(model="claude-opus-4-8", run_id="a", detail_page="models/opus--x.html"),
        _row(model="claude-opus-4-8", run_id="a!", detail_page="models/opus--x.html"),
    ]
    with pytest.raises(SiteGenerationError, match="duplicate leaderboard detail page"):
        _reject_duplicate_detail_pages(rows)


def test_republish_into_the_same_output_leaves_no_staging_debris(tmp_path: Path) -> None:
    results = _fixture_copy(tmp_path)
    output = tmp_path / "build"

    generate_site(results, output)
    first_index = (output / "index.html").read_bytes()
    generate_site(results, output)
    second_index = (output / "index.html").read_bytes()

    assert first_index == second_index
    debris = {p.name for p in output.parent.iterdir() if p.name.startswith(".build")}
    assert debris == set()
