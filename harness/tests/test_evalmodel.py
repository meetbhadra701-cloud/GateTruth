from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import cli, evalmodel
from harness.evalmodel import (
    PROMPT_VERSION,
    build_generation_prompt,
    eval_model,
    extract_module_source,
    task_ids_for_tier,
)
from harness.providers.mock import MockCompletionProvider
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import load_manifest
from harness.spend import SpendCapExceeded

TOY_REF = Path("harness/tests/fixtures/toy_task/ref/ref.sv")


class RecordingProvider(MockCompletionProvider):
    def __init__(self, responses: list[str], **kwargs):
        super().__init__(responses, **kwargs)
        self.calls: list[tuple[str, str, object]] = []

    def generate(self, spec, interface, params):
        self.calls.append((spec, interface, params))
        return super().generate(spec, interface, params)


def manifest_path(root: Path, model: str = "mock-eval") -> Path:
    return root / model / "toy_task" / "sample_1.json"


class SpendCapExceededProvider(MockCompletionProvider):
    """Simulates reserve_spend() raising mid-campaign, e.g. from a concurrent caller."""

    def generate(self, spec, interface, params):
        raise SpendCapExceeded("spend cap exceeded: 300.0001 > 300.0000")


def test_extract_module_source_rejects_truncated_fence():
    response = """```systemverilog
module truncated_example (
    input logic clk,
    output logic value
);
    always_ff @(posedge clk) begin
        value <=
"""

    with pytest.raises(ValueError, match="unterminated code fence"):
        extract_module_source(response)


def test_extract_module_source_accepts_well_formed_fence():
    source = "module fenced_example(input logic a, output logic y);\nassign y = a;\nendmodule"

    assert extract_module_source(f"```systemverilog\n{source}\n```") == source + "\n"


def test_extract_module_source_accepts_fenceless_raw_code():
    source = "module raw_example(input logic a, output logic y);\nassign y = a;\nendmodule"

    assert extract_module_source(source) == source + "\n"


def test_extract_module_source_ignores_a_module_keyword_inside_a_comment():
    response = (
        "// module fake_thing; -- not a real declaration\n"
        "I cannot implement this task."
    )

    with pytest.raises(ValueError, match="no SystemVerilog module declaration"):
        extract_module_source(response)


def test_extract_module_source_ignores_a_module_keyword_inside_a_string_literal():
    source = (
        'module real_example(input logic a, output logic y);\n'
        '  // synthesis note only, not a declaration\n'
        '  initial $display("module decoy_thing;");\n'
        "  assign y = a;\n"
        "endmodule"
    )

    assert extract_module_source(source) == source + "\n"


def test_extract_module_source_rejects_a_trailing_second_module():
    source = (
        "module real_example(input logic a, output logic y);\n"
        "  assign y = a;\n"
        "endmodule\n"
        "module decoy_helper(input logic a, output logic y);\n"
        "  assign y = a;\n"
        "endmodule\n"
    )

    with pytest.raises(ValueError, match="multiple module declarations"):
        extract_module_source(source)


def test_extract_module_source_enforces_the_locked_interface_module_name():
    source = "module wrong_name(input logic a, output logic y);\nassign y = a;\nendmodule"

    with pytest.raises(ValueError, match="does not match the locked interface"):
        extract_module_source(source, expected_module="real_example")

    assert (
        extract_module_source(source, expected_module="wrong_name")
        == source + "\n"
    )


def test_extract_module_source_picks_the_first_fenced_candidate_with_one_valid_module():
    response = (
        "Here's an example usage, then the real module:\n"
        "```systemverilog\n"
        "module usage_example; initial $display(\"demo\"); endmodule\n"
        "module accidental_second; endmodule\n"
        "```\n"
        "```systemverilog\n"
        "module real_example(input logic a, output logic y);\n"
        "  assign y = a;\n"
        "endmodule\n"
        "```\n"
    )

    result = extract_module_source(response, expected_module="real_example")

    assert "real_example" in result
    assert "usage_example" not in result


def test_tier_selection_covers_frozen_60_task_suite():
    tiers = {tier: task_ids_for_tier(tier) for tier in ("T1", "T2", "T3")}

    assert {tier: len(tasks) for tier, tasks in tiers.items()} == {
        "T1": 20,
        "T2": 25,
        "T3": 15,
    }
    assert task_ids_for_tier("all") == sorted(
        tiers["T1"] + tiers["T2"] + tiers["T3"]
    )


def test_fenced_rtl_scores_end_to_end_and_records_prompt(tmp_path):
    source = TOY_REF.read_text(encoding="utf-8")
    provider = RecordingProvider(
        [f"```systemverilog\n{source}```"],
        model="mock-eval",
        tokens_in_per_call=101,
        tokens_out_per_call=37,
        cost_usd_per_call=0.00125,
    )
    provider.spend_path = tmp_path / "spend.json"

    summary = eval_model(["toy_task"], provider, out_dir=tmp_path, max_tokens=128)
    manifest = load_manifest(manifest_path(tmp_path))

    assert manifest.task_score == pytest.approx(66.6666666667)
    assert manifest.ppa == 1.0
    assert manifest.provider == "mock"
    assert manifest.model == "mock-eval"
    assert manifest.prompt_version == PROMPT_VERSION
    assert (manifest.tokens_in, manifest.tokens_out, manifest.cost_usd) == (101, 37, 0.00125)
    assert manifest.harness_git == evalmodel.harness_git()
    assert manifest.max_output_tokens == 128
    assert (tmp_path / "mock-eval/toy_task/sample_1.sv").read_text(encoding="utf-8") == source
    task = evalmodel.resolve_task("toy_task")
    prompt, system = build_generation_prompt(task)
    assert (task.root / "spec.md").read_text(encoding="utf-8") in prompt
    assert (task.root / "interface.sv").read_text(encoding="utf-8") in prompt
    assert len(provider.calls) == 1
    recorded_prompt, recorded_system, recorded_params = provider.calls[0]
    assert (recorded_prompt, recorded_system) == (prompt, system)
    assert recorded_params.max_tokens == 128
    assert summary["aggregate_mean"] == pytest.approx(66.6666666667)
    assert summary["signature"] == compute_manifest_signature(summary)


def test_non_code_generation_emits_valid_score_zero_manifest(tmp_path):
    provider = RecordingProvider(["I cannot provide an implementation."], model="mock-garbage")
    provider.spend_path = tmp_path / "spend.json"

    summary = eval_model(["toy_task"], provider, out_dir=tmp_path)
    manifest = load_manifest(manifest_path(tmp_path, "mock-garbage"))

    assert manifest.task_score == 0.0
    assert manifest.ppa == 0.0
    assert manifest.generation_error == (
        "ValueError: generation contained no SystemVerilog module declaration"
    )
    assert manifest.harness_git == evalmodel.harness_git()
    assert manifest.max_output_tokens == evalmodel.DEFAULT_MAX_TOKENS
    assert not (tmp_path / "mock-garbage/toy_task/sample_1.sv").exists()
    assert summary["tasks"]["toy_task"]["scores"] == [0.0]


class TransportFailureProvider(MockCompletionProvider):
    """Simulates a provider-side transport error (TLS EOF, HTTP 5xx, etc.), distinct from a
    completion that is present but not valid code."""

    def generate(self, spec, interface, params):
        raise RuntimeError("simulated transport failure")


def test_transport_failure_removes_a_stale_sidecar_from_a_prior_campaign(tmp_path):
    """Regression test: results/eval-16384's Gemini rows found 11 generation-error samples
    whose .sv sidecar was byte-identical to the earlier 4096-token campaign's output into the
    same (gitignored, reused-across-campaigns) directory -- the write path never cleared a
    stale sidecar on a transport failure, so it looked like this run's output. A genuine
    provider-call failure must tombstone any pre-existing sidecar, not leave it in place."""

    stale_dir = tmp_path / "mock-flaky" / "toy_task"
    stale_dir.mkdir(parents=True)
    stale_sidecar = stale_dir / "sample_1.sv"
    stale_sidecar.write_text("module toy_task(); /* leftover from a prior campaign */ endmodule\n")

    provider = TransportFailureProvider(["unused"], model="mock-flaky")
    provider.spend_path = tmp_path / "spend.json"

    eval_model(["toy_task"], provider, out_dir=tmp_path)
    manifest = load_manifest(manifest_path(tmp_path, "mock-flaky"))

    assert manifest.generation_error is not None
    assert manifest.task_score == 0.0
    assert not stale_sidecar.exists()


def test_extraction_failure_removes_a_stale_sidecar(tmp_path):
    stale_dir = tmp_path / "mock-garbage" / "toy_task"
    stale_dir.mkdir(parents=True)
    stale_sidecar = stale_dir / "sample_1.sv"
    stale_sidecar.write_text("module toy_task(); /* leftover from a prior campaign */ endmodule\n")

    provider = RecordingProvider(["I cannot provide an implementation."], model="mock-garbage")
    provider.spend_path = tmp_path / "spend.json"

    eval_model(["toy_task"], provider, out_dir=tmp_path)

    assert not stale_sidecar.exists()


def test_provider_default_temperature_is_recorded_in_signed_outputs(tmp_path):
    provider = RecordingProvider(["not code"], model="claude-opus-4-8")
    provider.name = "anthropic"
    provider.manifest_temperature = "provider_default"
    provider.spend_path = tmp_path / "spend.json"

    summary = eval_model(["toy_task"], provider, out_dir=tmp_path / "out")
    manifest = load_manifest(
        manifest_path(tmp_path / "out", "claude-opus-4-8")
    )

    assert manifest.temperature == "provider_default"
    assert summary["temperature"] == "provider_default"
    raw_manifest = json.loads(
        manifest_path(tmp_path / "out", "claude-opus-4-8").read_text(
            encoding="utf-8"
        )
    )
    assert manifest.signature == compute_manifest_signature(raw_manifest)
    assert summary["signature"] == compute_manifest_signature(summary)


def test_official_gate_skips_unsigned_task_without_provider_call(tmp_path):
    provider = RecordingProvider([TOY_REF.read_text(encoding="utf-8")], model="mock-official")
    provider.spend_path = tmp_path / "spend.json"

    summary = eval_model(["toy_task"], provider, out_dir=tmp_path, official=True)
    manifest = load_manifest(manifest_path(tmp_path, "mock-official"))

    assert provider.calls == []
    assert manifest.task_score == 0.0
    assert manifest.official_skip_reason == (
        "official review gate: ref_review must be signed off for official runs"
    )
    assert all(stage.status == "skip" for stage in manifest.stages)
    assert summary["tasks"]["toy_task"]["skipped"] is True
    assert "ref_review" in summary["tasks"]["toy_task"]["skip_reason"]


def test_summary_signature_is_deterministic(tmp_path):
    first_provider = RecordingProvider(["not code"], model="mock-deterministic")
    first_provider.spend_path = tmp_path / "spend.json"
    second_provider = RecordingProvider(["not code"], model="mock-deterministic")
    second_provider.spend_path = tmp_path / "spend.json"

    first = eval_model(
        ["toy_task"],
        first_provider,
        out_dir=tmp_path / "first",
    )
    second = eval_model(
        ["toy_task"],
        second_provider,
        out_dir=tmp_path / "second",
    )

    assert first["signature"] == second["signature"]
    assert json.loads(
        (tmp_path / "first/mock-deterministic/summary.json").read_text(encoding="utf-8")
    )["signature"] == first["signature"]


def test_preflight_refuses_before_provider_call(tmp_path, monkeypatch):
    provider = RecordingProvider(
        [TOY_REF.read_text(encoding="utf-8")],
        model="claude-haiku-4-5-20251001",
    )
    provider.name = "anthropic"
    provider.spend_path = tmp_path / "spend.json"
    monkeypatch.setenv("SILICONBENCH_SPEND_CAP_USD", "0.001")

    with pytest.raises(SpendCapExceeded, match="pre-run estimate"):
        eval_model(["toy_task"], provider, out_dir=tmp_path / "out")
    assert provider.calls == []
    assert not (tmp_path / "out").exists()


def test_pipeline_exception_emits_score_zero_manifest(tmp_path, monkeypatch):
    provider = RecordingProvider([TOY_REF.read_text(encoding="utf-8")], model="mock-crash")
    provider.spend_path = tmp_path / "spend.json"
    monkeypatch.setattr(
        evalmodel,
        "run_task",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pipeline exploded")),
    )

    eval_model(["toy_task"], provider, out_dir=tmp_path)
    manifest = load_manifest(manifest_path(tmp_path, "mock-crash"))

    assert manifest.task_score == 0.0
    assert manifest.generation_error == "RuntimeError: pipeline exploded"
    assert manifest.signature == json.loads(
        manifest_path(tmp_path, "mock-crash").read_text(encoding="utf-8")
    )["signature"]


def test_estimate_only_prints_cost_without_provider_or_output(
    tmp_path, monkeypatch, capsys
):
    constructed = 0

    def forbidden_provider(*args, **kwargs):
        nonlocal constructed
        constructed += 1
        raise AssertionError("estimate-only must not construct a provider")

    monkeypatch.setattr(cli, "AnthropicProvider", forbidden_provider)
    monkeypatch.chdir(tmp_path)

    result = cli.main(
        [
            "eval-model",
            "--tasks",
            "toy_task",
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


def test_estimate_only_threads_max_tokens_for_single_model_full_suite(
    monkeypatch, capsys
):
    captured: dict[str, object] = {}

    def record_estimate(task_ids, provider_name, model, **kwargs):
        captured.update(
            task_ids=task_ids,
            provider_name=provider_name,
            model=model,
            **kwargs,
        )
        return 1.25

    monkeypatch.setattr(cli, "estimate_model_cost", record_estimate)

    result = cli.main(
        [
            "eval-model",
            "--tier",
            "all",
            "--provider",
            "openrouter",
            "--model",
            "google/gemini-2.5-pro",
            "--official",
            "--estimate-only",
            "--max-tokens",
            "16384",
        ]
    )

    assert result == 0
    assert captured["task_ids"] == task_ids_for_tier("all")
    assert captured["provider_name"] == "openrouter"
    assert captured["model"] == "google/gemini-2.5-pro"
    assert captured["samples"] == 1
    assert captured["official"] is True
    assert captured["max_tokens"] == 16384
    assert "tasks_requested=60" in capsys.readouterr().out


def test_spend_cap_exceeded_mid_call_propagates_instead_of_scoring_zero(tmp_path):
    """A spend-cap hit during provider.generate() is a campaign-level event, not a
    per-sample failure: it must not be folded into a generic "provider error" that
    writes a zeroed manifest indistinguishable from an incorrect submission."""
    provider = SpendCapExceededProvider(["irrelevant"])
    provider.spend_path = tmp_path / "spend.json"

    with pytest.raises(SpendCapExceeded):
        eval_model(["toy_task"], provider, out_dir=tmp_path)

    assert not manifest_path(tmp_path, "mock-completion").exists()
