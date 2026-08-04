from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from harness import agentb, cli, evalagent
from harness.agentb import provider_usage
from harness.evalagent import eval_agent
from harness.providers import GenParams
from harness.providers.mock import MockProvider
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest_b import AgentTrackBManifest, TrackBManifest
from harness.spend import SpendCapExceeded
from harness.trackb import _track_b_review_fields, resolve_track_b_task

ROOT = Path(__file__).resolve().parents[2]
AGENT_FIXTURE = (
    ROOT
    / "site"
    / "tests"
    / "fixtures"
    / "agent"
    / "smoke"
    / "claude-haiku-4-5-20251001"
    / "toy_taskB.json"
)
SITE_NAMESPACE = runpy.run_path(str(ROOT / "site" / "generate.py"))
GENERATE_SITE = SITE_NAMESPACE["generate_site"]
SITE_ERROR = SITE_NAMESPACE["SiteGenerationError"]


def _fake_runner(task_id: str, provider, *, out: str | Path) -> AgentTrackBManifest:
    provider.generate(
        json.dumps({"task_id": task_id}),
        "mock system",
        GenParams(model=provider.model, max_tokens=32, seed=0),
    )
    usage = provider_usage(provider)
    package = resolve_track_b_task(task_id)
    objective_pass = task_id == "b1_close_timing_mac"
    ratios = {
        "b1_close_timing_mac": (0.8, 0.7, 1.0),
        "b4_reduce_power_iir": (1.0, 0.9, 3.0),
    }[task_id]
    raw = json.loads(AGENT_FIXTURE.read_text(encoding="utf-8"))
    raw.update(
        {
            "task_id": task_id,
            "submission_dir": f"/tmp/{task_id}",
            "submission_sha256": None,
            "objective_type": package.objective.objective_type,
            "objective_pass": objective_pass,
            "task_score": 100.0 if objective_pass else 0.0,
            "provider": provider.name,
            "model": provider.model,
            "tokens_in": int(usage["tokens_in"]),
            "tokens_out": int(usage["tokens_out"]),
            "cost_usd": float(usage["cost_usd"]),
            "budget_exceeded": None,
            "wall_clock_s": 1.0,
            "timestamp": "2026-07-13T12:00:00Z",
            "signature": "0" * 64,
            **_track_b_review_fields(package.root),
        }
    )
    raw["stages"][-1]["status"] = "pass" if objective_pass else "fail"
    raw["ppa_delta"].update(
        {"area_ratio": ratios[0], "power_ratio": ratios[1], "wns_delta_ns": ratios[2]}
    )
    raw["signature"] = compute_manifest_signature(raw)
    manifest = AgentTrackBManifest.model_validate(raw)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    return manifest


def test_two_task_mock_run_emits_deterministic_summary_and_site_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evalagent, "run_agent_task", _fake_runner)
    tasks = ["b1_close_timing_mac", "b4_reduce_power_iir"]

    def run_once(path: Path) -> dict:
        provider = MockProvider(
            [{"tool": "done"}, {"tool": "done"}],
            tokens_in_per_call=10,
            tokens_out_per_call=5,
            cost_usd_per_call=0.001,
        )
        provider.spend_path = tmp_path / "spend.json"
        return eval_agent(tasks, provider, out_dir=path)

    agent_root = tmp_path / "agent"
    first = run_once(agent_root / "dryrun")
    second = run_once(tmp_path / "second" / "dryrun")
    model_root = agent_root / "dryrun" / "mock-scripted"

    assert first["signature"] == second["signature"]
    assert first["signature"] == compute_manifest_signature(first)
    assert first["objective_met_rate"] == 0.5
    assert first["median_ppa_delta"] == {
        "area_ratio": 0.9,
        "power_ratio": 0.8,
        "wns_delta_ns": 2.0,
    }
    assert (first["tokens_in"], first["tokens_out"], first["cost_usd"]) == (20, 10, 0.002)
    assert (model_root / "b1_close_timing_mac.json").is_file()
    assert (model_root / "b4_reduce_power_iir.json").is_file()
    assert json.loads((model_root / "summary.json").read_text(encoding="utf-8")) == first

    site_out = tmp_path / "site"
    GENERATE_SITE(tmp_path / "no-eval", site_out, agent_results_root=agent_root)
    leaderboard = json.loads((site_out / "leaderboard.json").read_text(encoding="utf-8"))
    assert {row["task_id"] for row in leaderboard["track_b_runs"]} == set(tasks)

    summary_path = model_root / "summary.json"
    tampered = json.loads(summary_path.read_text(encoding="utf-8"))
    tampered["cost_usd"] = 99.0
    summary_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(SITE_ERROR, match="tampered agent summary"):
        GENERATE_SITE(
            tmp_path / "no-eval",
            tmp_path / "tampered-site",
            agent_results_root=agent_root,
        )
    assert not (tmp_path / "tampered-site").exists()


def test_official_skips_unsigned_task_without_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        evalagent,
        "run_agent_task",
        lambda *args, **kwargs: pytest.fail("unsigned official task must not run"),
    )
    provider = MockProvider([{"tool": "done"}])
    provider.spend_path = tmp_path / "spend.json"

    summary = eval_agent(
        ["toy_taskB"],
        provider,
        out_dir=tmp_path / "official",
        official=True,
    )

    row = summary["tasks"]["toy_taskB"]
    assert row["skipped"] is True
    assert "baseline_review=PENDING" in row["skip_reason"]
    assert "tb_review=PENDING" in row["skip_reason"]
    assert summary["tasks_attempted"] == 0
    assert provider.usage == {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    assert not (tmp_path / "official/mock-scripted/toy_taskB.json").exists()


def test_preflight_cap_refuses_before_any_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MockProvider([{"tool": "done"}])
    provider.name = "anthropic"
    provider.model = "claude-haiku-4-5-20251001"
    provider.spend_path = tmp_path / "spend.json"
    monkeypatch.setenv("SILICONBENCH_SPEND_CAP_USD", "0.001")

    with pytest.raises(SpendCapExceeded, match="pre-run estimate"):
        eval_agent(
            ["b1_close_timing_mac"],
            provider,
            out_dir=tmp_path / "refused",
        )

    assert provider.usage == {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}
    assert not (tmp_path / "refused").exists()


def test_rejected_immutable_edit_still_lands_disqualified_summary_row(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def disqualified_evaluator(task_id: str, submission_dir, out) -> TrackBManifest:
        raw = json.loads(AGENT_FIXTURE.read_text(encoding="utf-8"))
        raw.pop("budget_exceeded")
        raw.update(
            {
                "task_id": task_id,
                "submission_dir": str(submission_dir),
                "disqualified": True,
                "disqualification_reason": "immutable edit attempt rejected",
                "objective_pass": False,
                "task_score": 0.0,
                "provider": "local",
                "model": "track-b-evaluator",
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "tool_calls": 0,
                "signature": "0" * 64,
            }
        )
        raw["signature"] = compute_manifest_signature(raw)
        return TrackBManifest.model_validate(raw)

    monkeypatch.setattr(agentb, "run_track_b", disqualified_evaluator)
    provider = MockProvider(
        [
            {"tool": "write_design", "path": "task.yaml", "content": "tamper"},
            {"tool": "done"},
        ]
    )
    provider.spend_path = tmp_path / "spend.json"
    out_dir = tmp_path / "agent" / "rejected"

    summary = eval_agent(["toy_taskB"], provider, out_dir=out_dir)

    row = summary["tasks"]["toy_taskB"]
    assert row["skipped"] is False
    assert row["disqualified"] is True
    assert row["objective_pass"] is False
    manifest_path = out_dir / "mock-scripted" / "toy_taskB.json"
    transcript = json.loads(
        manifest_path.with_suffix(".transcript.json").read_text(encoding="utf-8")
    )
    assert transcript[0]["observation"]["status"] == "rejected"
    assert "keys must be" in transcript[0]["observation"]["error"]


def test_estimate_only_prints_budget_cost_without_provider_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    constructed = 0

    def forbidden_provider(*args, **kwargs):
        nonlocal constructed
        constructed += 1
        raise AssertionError("estimate-only must not construct a provider")

    monkeypatch.setattr(cli, "AnthropicProvider", forbidden_provider)
    monkeypatch.chdir(tmp_path)

    result = cli.main(
        [
            "eval-agent",
            "--tasks",
            "toy_taskB",
            "--provider",
            "anthropic",
            "--model",
            "claude-haiku-4-5-20251001",
            "--estimate-only",
        ]
    )

    output = capsys.readouterr().out
    projected = float(output.split("projected_total_usd=", 1)[1].splitlines()[0])
    assert result == 0
    assert projected > 0
    assert constructed == 0
    assert list(tmp_path.iterdir()) == []
