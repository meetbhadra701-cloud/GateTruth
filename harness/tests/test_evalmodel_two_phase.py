"""generate_model_samples()/score_pending_samples() must reproduce eval_model()'s
combined-flow output exactly, since they are the same pipeline split across a process
boundary for the generate/score security separation (P0-6): a network-enabled phase
that never executes untrusted code, and a --network none phase that never touches a
provider."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from harness import cli, evalmodel
from harness.evalmodel import (
    eval_model,
    generate_model_samples,
    score_pending_samples,
)
from harness.providers.mock import MockCompletionProvider
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import load_manifest
from harness.schemas.pending import PendingGeneration, load_pending_generation

TOY_REF = Path("harness/tests/fixtures/toy_task/ref/ref.sv")


class RecordingProvider(MockCompletionProvider):
    def __init__(self, responses: list[str], **kwargs):
        super().__init__(responses, **kwargs)
        self.calls: list[tuple[str, str, object]] = []

    def generate(self, spec, interface, params):
        self.calls.append((spec, interface, params))
        return super().generate(spec, interface, params)


def manifest_path(root: Path, model: str, task_id: str = "toy_task") -> Path:
    return root / model / task_id / "sample_1.json"


def pending_path(root: Path, model: str, task_id: str = "toy_task") -> Path:
    return root / model / task_id / "sample_1.pending.json"


def test_two_phase_split_reproduces_the_combined_flow_byte_for_byte(tmp_path):
    source = TOY_REF.read_text(encoding="utf-8")

    combined_provider = RecordingProvider(
        [f"```systemverilog\n{source}```"],
        model="mock-combined",
        tokens_in_per_call=101,
        tokens_out_per_call=37,
        cost_usd_per_call=0.00125,
        finish_reasons=["stop"],
    )
    combined_provider.spend_path = tmp_path / "spend-combined.json"
    combined_summary = eval_model(
        ["toy_task"], combined_provider, out_dir=tmp_path / "combined", max_tokens=128
    )
    combined_manifest = load_manifest(manifest_path(tmp_path / "combined", "mock-combined"))

    split_provider = RecordingProvider(
        [f"```systemverilog\n{source}```"],
        model="mock-split",
        tokens_in_per_call=101,
        tokens_out_per_call=37,
        cost_usd_per_call=0.00125,
        finish_reasons=["stop"],
    )
    split_provider.spend_path = tmp_path / "spend-split.json"
    generate_result = generate_model_samples(
        ["toy_task"], split_provider, out_dir=tmp_path / "split", max_tokens=128
    )

    # Phase 1 must never touch the pipeline: no manifest, only a pending record + sidecar.
    assert not manifest_path(tmp_path / "split", "mock-split").exists()
    pending = load_pending_generation(pending_path(tmp_path / "split", "mock-split"))
    assert pending.generation_error is None
    assert pending.official_skip_reason is None
    assert pending.submission_sha256 == hashlib.sha256(source.encode("utf-8")).hexdigest()
    assert generate_result["model_root"] == str(tmp_path / "split" / "mock-split")

    split_summary = score_pending_samples(
        ["toy_task"], out_dir=tmp_path / "split", model="mock-split", official=False
    )
    split_manifest = load_manifest(manifest_path(tmp_path / "split", "mock-split"))

    for field in ("task_score", "ppa", "prompt_version", "tokens_in", "tokens_out",
                  "cost_usd", "max_output_tokens", "provider_finish_reason",
                  "submission_sha256", "task_package_sha256", "reference_metrics_sha256"):
        assert getattr(split_manifest, field) == getattr(combined_manifest, field), field
    assert split_manifest.provider == "mock"
    assert combined_manifest.provider == "mock"
    for field in ("aggregate_mean", "tokens_in", "tokens_out", "cost_usd"):
        assert split_summary[field] == combined_summary[field], field
    assert split_summary["signature"] == compute_manifest_signature(split_summary)
    assert split_manifest.signature == compute_manifest_signature(
        json.loads(manifest_path(tmp_path / "split", "mock-split").read_text(encoding="utf-8"))
    )


def test_official_skip_never_calls_the_provider_in_phase_one_and_propagates_to_phase_two(
    tmp_path,
):
    provider = RecordingProvider([TOY_REF.read_text(encoding="utf-8")], model="mock-official")
    provider.spend_path = tmp_path / "spend.json"

    generate_model_samples(
        ["toy_task"], provider, out_dir=tmp_path, official=True
    )

    assert provider.calls == []
    pending = load_pending_generation(pending_path(tmp_path, "mock-official"))
    assert pending.official_skip_reason == (
        "official review gate: ref_review must be signed off for official runs"
    )
    assert pending.submission_sha256 is None
    assert not (tmp_path / "mock-official" / "toy_task" / "sample_1.sv").exists()

    summary = score_pending_samples(
        ["toy_task"], out_dir=tmp_path, model="mock-official", official=True
    )
    manifest = load_manifest(manifest_path(tmp_path, "mock-official"))

    assert manifest.task_score == 0.0
    assert manifest.official_skip_reason == pending.official_skip_reason
    assert all(stage.status == "skip" for stage in manifest.stages)
    assert summary["tasks"]["toy_task"]["skipped"] is True
    assert "ref_review" in summary["tasks"]["toy_task"]["skip_reason"]


def test_generation_error_in_phase_one_never_calls_run_task_in_phase_two(tmp_path, monkeypatch):
    provider = RecordingProvider(["I cannot provide an implementation."], model="mock-garbage")
    provider.spend_path = tmp_path / "spend.json"

    generate_model_samples(["toy_task"], provider, out_dir=tmp_path)

    pending = load_pending_generation(pending_path(tmp_path, "mock-garbage"))
    assert pending.generation_error == (
        "ValueError: generation contained no SystemVerilog module declaration"
    )
    assert not (tmp_path / "mock-garbage" / "toy_task" / "sample_1.sv").exists()

    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("score_pending_samples must not run_task() a failed generation")

    monkeypatch.setattr(evalmodel, "run_task", fail_if_called)

    summary = score_pending_samples(["toy_task"], out_dir=tmp_path, model="mock-garbage")
    manifest = load_manifest(manifest_path(tmp_path, "mock-garbage"))

    assert called is False
    assert manifest.task_score == 0.0
    assert manifest.generation_error == pending.generation_error
    assert summary["tasks"]["toy_task"]["scores"] == [0.0]


def test_tampered_sidecar_between_phases_is_refused_not_silently_scored(tmp_path):
    source = TOY_REF.read_text(encoding="utf-8")
    provider = RecordingProvider(
        [f"```systemverilog\n{source}```"], model="mock-tamper"
    )
    provider.spend_path = tmp_path / "spend.json"

    generate_model_samples(["toy_task"], provider, out_dir=tmp_path)
    sidecar = tmp_path / "mock-tamper" / "toy_task" / "sample_1.sv"
    sidecar.write_text(sidecar.read_text(encoding="utf-8") + "\n// tampered between phases\n")

    with pytest.raises(ValueError, match="does not match the generate phase's recorded"):
        score_pending_samples(["toy_task"], out_dir=tmp_path, model="mock-tamper")


def test_missing_sidecar_between_phases_is_refused(tmp_path):
    source = TOY_REF.read_text(encoding="utf-8")
    provider = RecordingProvider(
        [f"```systemverilog\n{source}```"], model="mock-missing"
    )
    provider.spend_path = tmp_path / "spend.json"

    generate_model_samples(["toy_task"], provider, out_dir=tmp_path)
    (tmp_path / "mock-missing" / "toy_task" / "sample_1.sv").unlink()

    with pytest.raises(ValueError, match="pending generation has no sidecar"):
        score_pending_samples(["toy_task"], out_dir=tmp_path, model="mock-missing")


def test_score_phase_refuses_a_model_root_that_was_never_generated(tmp_path):
    with pytest.raises(ValueError, match="no pending generations found"):
        score_pending_samples(["toy_task"], out_dir=tmp_path, model="mock-absent")


def test_score_phase_refuses_a_task_that_was_never_generated(tmp_path):
    (tmp_path / "mock-partial").mkdir()

    with pytest.raises(ValueError, match="no pending generation found"):
        score_pending_samples(["toy_task"], out_dir=tmp_path, model="mock-partial")


def test_pending_generation_signature_is_tamper_evident(tmp_path):
    provider = RecordingProvider(["not code"], model="mock-pending-sig")
    provider.spend_path = tmp_path / "spend.json"

    generate_model_samples(["toy_task"], provider, out_dir=tmp_path)
    raw = json.loads(pending_path(tmp_path, "mock-pending-sig").read_text(encoding="utf-8"))
    raw["cost_usd"] = 999.0
    tampered = tmp_path / "tampered.pending.json"
    tampered.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="signature"):
        PendingGeneration.model_validate(raw)


def test_cli_generate_then_score_round_trips(tmp_path, monkeypatch):
    source = TOY_REF.read_text(encoding="utf-8")
    script = tmp_path / "script.json"
    script.write_text(json.dumps([f"```systemverilog\n{source}```"]), encoding="utf-8")
    out_dir = tmp_path / "cli-out"
    monkeypatch.chdir(tmp_path)

    generate_rc = cli.main(
        [
            "generate-model",
            "--tasks",
            "toy_task",
            "--provider",
            "mock",
            "--model",
            "cli-mock",
            "--out",
            str(out_dir),
            "--script",
            str(script),
        ]
    )
    assert generate_rc == 0
    assert not manifest_path(out_dir, "cli-mock").exists()

    score_rc = cli.main(
        [
            "score-model",
            "--tasks",
            "toy_task",
            "--model",
            "cli-mock",
            "--out",
            str(out_dir),
        ]
    )
    assert score_rc == 0
    manifest = load_manifest(manifest_path(out_dir, "cli-mock"))
    assert manifest.task_score == pytest.approx(66.6666666667)
