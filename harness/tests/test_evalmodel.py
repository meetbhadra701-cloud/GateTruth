from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import cli, evalmodel
from harness.evalmodel import PROMPT_VERSION, build_generation_prompt, eval_model, task_ids_for_tier
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

    summary = eval_model(["toy_task"], provider, out_dir=tmp_path, max_tokens=128)
    manifest = load_manifest(manifest_path(tmp_path))

    assert manifest.task_score == pytest.approx(66.6666666667)
    assert manifest.ppa == 1.0
    assert manifest.provider == "mock"
    assert manifest.model == "mock-eval"
    assert manifest.prompt_version == PROMPT_VERSION
    assert (manifest.tokens_in, manifest.tokens_out, manifest.cost_usd) == (101, 37, 0.00125)
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

    summary = eval_model(["toy_task"], provider, out_dir=tmp_path)
    manifest = load_manifest(manifest_path(tmp_path, "mock-garbage"))

    assert manifest.task_score == 0.0
    assert manifest.ppa == 0.0
    assert manifest.generation_error == (
        "ValueError: generation contained no SystemVerilog module declaration"
    )
    assert not (tmp_path / "mock-garbage/toy_task/sample_1.sv").exists()
    assert summary["tasks"]["toy_task"]["scores"] == [0.0]


def test_official_gate_skips_unsigned_task_without_provider_call(tmp_path):
    provider = RecordingProvider([TOY_REF.read_text(encoding="utf-8")], model="mock-official")

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
    first = eval_model(
        ["toy_task"],
        RecordingProvider(["not code"], model="mock-deterministic"),
        out_dir=tmp_path / "first",
    )
    second = eval_model(
        ["toy_task"],
        RecordingProvider(["not code"], model="mock-deterministic"),
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
