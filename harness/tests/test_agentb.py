from __future__ import annotations

import hashlib
from http.client import IncompleteRead
from io import BytesIO
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from harness import agentb
from harness.agentb import PER_CALL_MAX_OUTPUT_TOKENS, Budget, run_agent_task
from harness.providers import GenParams
from harness.providers import _http as http_module
from harness.providers import anthropic as anthropic_module
from harness.providers._http import ProviderTransportError
from harness.providers.anthropic import AnthropicProvider
from harness.providers.mock import MockProvider
from harness.providers.openai import OpenAIProvider
from harness.schemas.manifest_b import load_agent_manifest_b
from harness.spend import load_spend

SCRIPT = Path("harness/tests/fixtures/toy_agent_script.json")
SOLUTION = Path("harness/tests/fixtures/toy_taskB_solution/toy_trackb.sv")


def load_script() -> list[dict]:
    return json.loads(SCRIPT.read_text(encoding="utf-8"))


def anthropic_http_response(*, text: str = '{"tool":"done"}') -> BytesIO:
    return BytesIO(
        json.dumps(
            {
                "content": [{"type": "text", "text": text}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        ).encode("utf-8")
    )


def openai_http_response(*, text: str = '{"tool":"done"}') -> BytesIO:
    return BytesIO(
        json.dumps(
            {
                "choices": [{"message": {"content": text}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            }
        ).encode("utf-8")
    )


class RecordingMockProvider(MockProvider):
    def __init__(self, *, initial_tokens: int = 0) -> None:
        super().__init__([{"tool": "done"}], tokens_in_per_call=0, tokens_out_per_call=0)
        self._tokens_in = initial_tokens
        self.params: list[GenParams] = []

    def generate(self, spec: str, interface: str, params: GenParams) -> str:
        self.params.append(params)
        return super().generate(spec, interface, params)


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
    written_design = out.with_suffix(".sv").read_text(encoding="utf-8")
    submitted_content = load_script()[1]["content"]
    assert written_design == submitted_content
    assert manifest.submission_sha256 == hashlib.sha256(submitted_content.encode("utf-8")).hexdigest()


def test_agentb_design_sidecar_preserves_crlf_bytes_exactly(tmp_path):
    """The sidecar must be a byte-exact copy of what was hashed, not a text
    round-trip: read_text()'s universal-newline handling silently rewrites CRLF to
    LF, which would make the persisted .sv permanently disagree with its own
    recorded submission_sha256 for any design containing Windows line endings."""

    crlf_content = SOLUTION.read_text(encoding="utf-8").replace("\n", "\r\n")
    script = [
        {"tool": "write_design", "content": crlf_content},
        {"tool": "done"},
    ]
    out = tmp_path / "crlf.json"
    manifest = run_agent_task("toy_taskB", MockProvider(script), out=out)

    sidecar_bytes = out.with_suffix(".sv").read_bytes()
    assert sidecar_bytes == crlf_content.encode("utf-8")
    assert manifest.submission_sha256 == hashlib.sha256(sidecar_bytes).hexdigest()


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
    assert manifest.objective_pass is False
    assert manifest.task_score == 0.0
    assert manifest.tool_calls == 2
    assert manifest.tokens_in == 20
    assert manifest.tokens_out == 10
    assert out.exists()
    assert manifest.stages


def test_agentb_clamps_per_call_output_without_changing_episode_budget(
    tmp_path,
    monkeypatch,
):
    episode_tokens = 250_000
    monkeypatch.setattr(
        agentb,
        "load_budget",
        lambda _path: Budget(
            tokens=episode_tokens,
            wall_clock_s=60,
            tool_calls=2,
        ),
    )

    fresh = RecordingMockProvider()
    run_agent_task("toy_taskB", fresh, out=tmp_path / "fresh.json")

    remaining_tokens = 100
    near_exhausted = RecordingMockProvider(
        initial_tokens=episode_tokens - remaining_tokens
    )
    run_agent_task(
        "toy_taskB",
        near_exhausted,
        out=tmp_path / "near-exhausted.json",
    )

    assert fresh.params[0].max_tokens == PER_CALL_MAX_OUTPUT_TOKENS
    assert fresh.params[0].max_tokens != episode_tokens
    assert near_exhausted.params[0].max_tokens == remaining_tokens


def test_agentb_retries_transport_then_completes_without_leaking_spend(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    attempts = 0
    delays: list[float] = []

    def flaky_post(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise ProviderTransportError("provider transport error: timed out")
        return {
            "content": [{"type": "text", "text": '{"tool":"done"}'}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

    monkeypatch.setattr(anthropic_module, "post_json", flaky_post)
    monkeypatch.setattr(agentb, "_retry_sleep", delays.append)
    spend_path = tmp_path / "spend.json"
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=spend_path,
    )

    manifest = run_agent_task("toy_taskB", provider, out=tmp_path / "retry.json")
    spend = load_spend(spend_path)

    assert attempts == 3
    assert delays == list(agentb.TRANSPORT_RETRY_DELAYS_S)
    assert manifest.tool_calls == 1
    assert manifest.tokens_in == 10
    assert manifest.tokens_out == 5
    assert manifest.cost_usd == provider.price.cost(10, 5)
    assert spend["total_usd"] == manifest.cost_usd
    assert all("reservation" not in run for run in spend["runs"])


def test_agentb_exhausted_transport_retries_terminate_once(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    attempts = 0

    def failed_post(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise ProviderTransportError("provider transport error: offline")

    monkeypatch.setattr(anthropic_module, "post_json", failed_post)
    monkeypatch.setattr(agentb.time, "sleep", lambda _seconds: None)
    spend_path = tmp_path / "spend.json"
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=spend_path,
    )
    out = tmp_path / "exhausted.json"

    manifest = run_agent_task("toy_taskB", provider, out=out)
    transcript = json.loads(
        out.with_suffix(".transcript.json").read_text(encoding="utf-8")
    )
    spend = load_spend(spend_path)

    assert attempts == 3
    assert manifest.tool_calls == 0
    assert len(transcript) == 1
    assert transcript[0]["observation"]["status"] == "provider_error"
    assert spend["total_usd"] == 0.0
    assert all("reservation" not in run for run in spend["runs"])


def test_agentb_retries_http_529_then_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    attempts = 0
    delays: list[float] = []

    def overloaded_then_ok(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise HTTPError(
                "https://provider.invalid",
                529,
                "overloaded",
                {},
                BytesIO(b"temporary overload"),
            )
        return anthropic_http_response()

    monkeypatch.setattr(http_module, "urlopen", overloaded_then_ok)
    monkeypatch.setattr(agentb.time, "sleep", delays.append)
    spend_path = tmp_path / "spend.json"
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=spend_path,
    )

    manifest = run_agent_task(
        "toy_taskB",
        provider,
        out=tmp_path / "http-529.json",
    )
    spend = load_spend(spend_path)

    assert attempts == 2
    assert delays == [agentb.TRANSPORT_RETRY_DELAYS_S[0]]
    assert manifest.tool_calls == 1
    assert spend["total_usd"] == manifest.cost_usd
    assert all("reservation" not in run for run in spend["runs"])


@pytest.mark.parametrize(
    "first_failure",
    ["incomplete-read", "invalid-json"],
)
def test_agentb_retries_corrupt_response_then_completes(
    first_failure,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    attempts = 0
    delays: list[float] = []

    def corrupt_then_ok(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            return anthropic_http_response()
        if first_failure == "incomplete-read":
            raise IncompleteRead(b'{"content":', 100)
        if first_failure == "invalid-json":
            return BytesIO(b"{not-json")
        raise AssertionError(f"unknown response failure: {first_failure}")

    monkeypatch.setattr(http_module, "urlopen", corrupt_then_ok)
    monkeypatch.setattr(agentb.time, "sleep", delays.append)
    spend_path = tmp_path / "spend.json"
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=spend_path,
    )

    manifest = run_agent_task(
        "toy_taskB",
        provider,
        out=tmp_path / f"{first_failure}.json",
    )
    spend = load_spend(spend_path)

    assert attempts == 2
    assert delays == [agentb.TRANSPORT_RETRY_DELAYS_S[0]]
    assert manifest.tool_calls == 1
    assert spend["total_usd"] == manifest.cost_usd
    assert all("reservation" not in run for run in spend["runs"])


def test_agentb_retries_openai_empty_completion_then_completes(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-key")
    attempts = 0
    delays: list[float] = []

    def empty_then_ok(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return openai_http_response(text="")
        return openai_http_response()

    monkeypatch.setattr(http_module, "urlopen", empty_then_ok)
    monkeypatch.setattr(agentb.time, "sleep", delays.append)
    spend_path = tmp_path / "spend.json"
    provider = OpenAIProvider("gpt-5-mini", spend_path=spend_path)

    manifest = run_agent_task(
        "toy_taskB",
        provider,
        out=tmp_path / "openai-empty.json",
    )
    spend = load_spend(spend_path)

    assert attempts == 2
    assert delays == [agentb.TRANSPORT_RETRY_DELAYS_S[0]]
    assert manifest.tool_calls == 1
    assert spend["total_usd"] == manifest.cost_usd
    assert all("reservation" not in run for run in spend["runs"])


def test_agentb_does_not_retry_http_status_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    attempts = 0
    delays: list[float] = []

    def bad_request(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise HTTPError(
            "https://provider.invalid",
            400,
            "bad request",
            {},
            BytesIO(b"deterministic failure"),
        )

    monkeypatch.setattr(http_module, "urlopen", bad_request)
    monkeypatch.setattr(agentb.time, "sleep", delays.append)
    spend_path = tmp_path / "spend.json"
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=spend_path,
    )

    manifest = run_agent_task(
        "toy_taskB",
        provider,
        out=tmp_path / "http-error.json",
    )
    spend = load_spend(spend_path)

    assert attempts == 1
    assert delays == []
    assert manifest.tool_calls == 0
    assert spend["total_usd"] == 0.0
    assert all("reservation" not in run for run in spend["runs"])


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


def test_agentb_spend_cap_abort_is_scored_as_is(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unit-test-key")
    monkeypatch.setenv("SILICONBENCH_SPEND_CAP_USD", "0.01")

    def huge_usage_response(*args, **kwargs):
        return {
            "content": [{"type": "text", "text": '{"tool":"done"}'}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 1},
        }

    monkeypatch.setattr(anthropic_module, "post_json", huge_usage_response)
    provider = AnthropicProvider(
        "claude-haiku-4-5-20251001",
        spend_path=tmp_path / "spend.json",
    )
    out = tmp_path / "spend_cap.json"
    manifest = run_agent_task("toy_taskB", provider, out=out)

    assert manifest.budget_exceeded == "spend_cap"
    assert manifest.objective_pass is False
    assert manifest.task_score == 0.0
    assert manifest.tool_calls == 0
    assert manifest.tokens_in == 1_000_000
    assert manifest.cost_usd > 1.0
    assert out.exists()
