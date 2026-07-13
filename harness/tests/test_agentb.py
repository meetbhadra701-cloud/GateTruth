from __future__ import annotations

import json
from pathlib import Path

from harness import agentb
from harness.agentb import Budget, run_agent_task
from harness.providers.mock import MockProvider
from harness.schemas.manifest_b import load_agent_manifest_b

SCRIPT = Path("harness/tests/fixtures/toy_agent_script.json")
SOLUTION = Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv")


def load_script() -> list[dict]:
    return json.loads(SCRIPT.read_text(encoding="utf-8"))


def test_agentb_mock_solution_passes_objective(tmp_path):
    out = tmp_path / "agent.json"
    provider = MockProvider(
        load_script(),
        tokens_in_per_call=11,
        tokens_out_per_call=7,
        cost_usd_per_call=0.001,
    )
    manifest = run_agent_task("toy_taskB", provider, out=out)

    assert manifest.objective_pass is True
    assert manifest.task_score == 100.0
    assert manifest.budget_exceeded is None
    assert manifest.provider == "mock"
    assert manifest.model == "mock-scripted"
    assert manifest.tokens_in == 44
    assert manifest.tokens_out == 28
    assert manifest.cost_usd == 0.004
    assert manifest.tool_calls == 4
    assert load_agent_manifest_b(out).signature == manifest.signature
    transcript = json.loads(out.with_suffix(".transcript.json").read_text(encoding="utf-8"))
    assert [entry["action"]["tool"] for entry in transcript] == [
        "read_file",
        "write_design",
        "sb_sim",
        "done",
    ]


def test_agentb_tool_call_budget_scores_as_is(tmp_path, monkeypatch):
    monkeypatch.setattr(
        agentb,
        "load_budget",
        lambda _path: Budget(tokens=1000, wall_clock_s=60, tool_calls=2),
    )
    script = [
        {"tool": "read_file", "path": "objective.yaml"},
        {"tool": "sb_lint"},
        {"tool": "write_design", "content": SOLUTION.read_text(encoding="utf-8")},
        {"tool": "done"},
    ]
    out = tmp_path / "budget.json"
    manifest = run_agent_task("toy_taskB", MockProvider(script), out=out)

    assert manifest.budget_exceeded == "tool_calls"
    assert manifest.tool_calls == 2
    assert manifest.tokens_in == 20
    assert manifest.tokens_out == 10
    assert out.exists()
    assert manifest.stages


def test_agentb_rejects_immutable_and_escape_actions_but_continues(tmp_path):
    script = [
        {
            "tool": "write_design",
            "path": "design/second.sv",
            "content": "module second; endmodule",
        },
        {"tool": "read_file", "path": "../outside.txt"},
        {"tool": "done"},
    ]
    out = tmp_path / "immutable.json"
    manifest = run_agent_task("toy_taskB", MockProvider(script), out=out)

    assert manifest.disqualified is False
    assert manifest.tool_calls == 3
    transcript = json.loads(out.with_suffix(".transcript.json").read_text(encoding="utf-8"))
    assert transcript[0]["observation"]["status"] == "rejected"
    assert "keys must be" in transcript[0]["observation"]["error"]
    assert transcript[1]["observation"]["status"] == "rejected"
    assert "escapes the sandbox" in transcript[1]["observation"]["error"]
    assert transcript[2]["observation"]["status"] == "ok"
