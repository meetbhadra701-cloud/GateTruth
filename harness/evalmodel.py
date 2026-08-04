"""Track A model-generation and evaluation orchestration."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from harness.atomic_write import atomic_write_text
from harness.git_provenance import harness_git
from harness.providers import GenParams, ProviderAdapter
from harness.providers.pricing import worst_case_cost
from harness.runner import SUITE_VERSION, TaskPackage, resolve_task, run_task, runtime_docker_digest
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import ResultManifest, TemperatureSetting
from harness.schemas.task_yaml import load_task_yaml
from harness.spend import DEFAULT_SPEND_PATH, SpendCapExceeded, load_spend, spend_cap_from_env
from harness.sv_mask import mask_code

PROMPT_VERSION = "track-a-rtl-v1"
DEFAULT_MAX_TOKENS = 4096
SYSTEM_PROMPT = (
    "You are generating a GateTruth Track A RTL submission. Emit exactly one complete "
    "SystemVerilog module implementing the locked interface. Do not emit a testbench, prose, "
    "analysis, or more than one module. Output only SystemVerilog source code."
)
MODULE_DECL_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)\b")
FENCE_RE = re.compile(
    r"```[ \t]*(?:systemverilog|verilog|sv)?[ \t]*\r?\n?(.*?)```",
    flags=re.IGNORECASE | re.DOTALL,
)
STAGE_NAMES = ("lint", "sim", "formal", "synth", "sta", "power", "route")


@dataclass(frozen=True)
class EvalPlan:
    task: TaskPackage
    skip_reason: str | None = None


def build_generation_prompt(task: TaskPackage) -> tuple[str, str]:
    """Build the versioned user/system prompt while preserving task inputs verbatim."""

    spec = (task.root / "spec.md").read_text(encoding="utf-8")
    interface = (task.root / "interface.sv").read_text(encoding="utf-8")
    prompt = (
        f"PROMPT_VERSION: {PROMPT_VERSION}\n"
        "<SPEC_MD>\n"
        f"{spec}"
        "\n</SPEC_MD>\n"
        "<INTERFACE_SV>\n"
        f"{interface}"
        "\n</INTERFACE_SV>\n"
    )
    return prompt, SYSTEM_PROMPT


def extract_module_source(response: str, *, expected_module: str | None = None) -> str:
    """Return fenced or raw module source, refusing non-code responses.

    Module declarations are matched against comment/string-masked text, so a
    `module` keyword inside a `//` comment or a string literal is never
    mistaken for a real declaration, and exactly one declaration is required
    -- a second, trailing module is rejected rather than silently passed
    through to the synthesis flow. When expected_module is given (the task's
    locked top-level module name), the one declaration found must match it.
    """

    if not isinstance(response, str):
        raise ValueError("provider response must be text")
    fence_count = response.count("```")
    if fence_count % 2:
        raise ValueError("generation contained an unterminated code fence")
    fenced = FENCE_RE.findall(response)
    if fenced:
        for candidate in fenced:
            source = candidate.strip()
            if _module_shape_error(source, expected_module) is None:
                return source + "\n"
        raise ValueError("generation contained no SystemVerilog module declaration")
    if fence_count:
        raise ValueError("generation contained a malformed code fence")
    source = response.strip()
    error = _module_shape_error(source, expected_module)
    if error is not None:
        raise ValueError(error)
    return source + "\n"


def _module_shape_error(source: str, expected_module: str | None) -> str | None:
    """Return why `source` is not a valid single-module submission, or None."""

    names = MODULE_DECL_RE.findall(mask_code(source))
    if not names:
        return "generation contained no SystemVerilog module declaration"
    if len(names) > 1:
        return f"generation contained multiple module declarations: {', '.join(names)}"
    if expected_module is not None and names[0] != expected_module:
        return (
            f"generation's module {names[0]!r} does not match the locked "
            f"interface module {expected_module!r}"
        )
    return None


def task_ids_for_tier(tier: str) -> list[str]:
    """Return the deterministic Track A task list for a tier or the full suite."""

    normalized = tier.upper()
    if normalized not in {"T1", "T2", "T3", "ALL"}:
        raise ValueError(f"unknown tier: {tier}")
    tasks_root = Path(__file__).resolve().parents[1] / "tasks"
    selected: list[str] = []
    for path in sorted(tasks_root.glob("*/task.yaml")):
        task = load_task_yaml(path)
        if normalized == "ALL" or task.tier == normalized:
            selected.append(task.id)
    return selected


def estimate_model_cost(
    task_ids: list[str],
    provider_name: str,
    model: str,
    *,
    samples: int = 1,
    official: bool = False,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> float:
    """Estimate a Track A matrix without constructing or calling a provider."""

    if not task_ids:
        raise ValueError("at least one task is required")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be unique")
    if samples < 1:
        raise ValueError("samples must be at least 1")
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")
    if not provider_name or not model:
        raise ValueError("provider and model names must be nonempty")
    plans = [_plan_task(task_id, official=official) for task_id in task_ids]
    return _estimate_plans_cost(plans, provider_name, model, samples, max_tokens)


def eval_model(
    task_ids: list[str],
    provider: ProviderAdapter,
    *,
    out_dir: str | Path,
    samples: int = 1,
    official: bool = False,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    """Generate and score one or more Track A samples, then emit a signed summary."""

    if not task_ids:
        raise ValueError("at least one task is required")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("task ids must be unique")
    if samples < 1:
        raise ValueError("samples must be at least 1")
    if max_tokens < 1:
        raise ValueError("max_tokens must be at least 1")
    model = str(getattr(provider, "model", "unknown-model"))
    provider_name = str(getattr(provider, "name", provider.__class__.__name__.lower()))
    temperature = _recorded_temperature(provider)
    if not model or not provider_name:
        raise ValueError("provider and model names must be nonempty")

    plans = [_plan_task(task_id, official=official) for task_id in task_ids]
    estimate, remaining = _preflight_cost(plans, provider, samples, max_tokens)
    print(f"pre_run_estimate_usd={estimate:.6f}")
    print(f"remaining_spend_cap_usd={remaining:.6f}")
    if estimate > remaining + 1e-12:
        raise SpendCapExceeded(
            f"pre-run estimate {estimate:.6f} exceeds remaining cap {remaining:.6f}"
        )

    model_root = Path(out_dir) / _safe_component(model)
    model_root.mkdir(parents=True, exist_ok=True)
    summary_tasks: dict[str, Any] = {}
    all_scores: list[float] = []
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost_usd = 0.0

    for plan in plans:
        task_dir = model_root / plan.task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        sample_records: list[dict[str, Any]] = []
        scores: list[float] = []
        for sample_number in range(1, samples + 1):
            manifest_path = task_dir / f"sample_{sample_number}.json"
            started = time.perf_counter()
            if plan.skip_reason is not None:
                manifest = _zero_manifest(
                    plan.task,
                    provider_name=provider_name,
                    model=model,
                    temperature=temperature,
                    usage=_empty_usage(),
                    wall_clock_s=time.perf_counter() - started,
                    max_output_tokens=max_tokens,
                    official_skip_reason=plan.skip_reason,
                )
                _write_manifest(manifest, manifest_path)
            else:
                source_path = task_dir / f"sample_{sample_number}.sv"
                prompt, system = build_generation_prompt(plan.task)
                response, call_error, usage, finish_reason = _call_once(
                    provider,
                    prompt,
                    system,
                    max_tokens=max_tokens,
                )
                if call_error is not None:
                    # A prior run into this same (gitignored, reused-across-campaigns) directory
                    # may have left a real .sv sidecar; a genuine transport failure this run must
                    # not leave that stale artifact looking like this attempt's output.
                    source_path.unlink(missing_ok=True)
                    manifest = _zero_manifest(
                        plan.task,
                        provider_name=provider_name,
                        model=model,
                        temperature=temperature,
                        usage=usage,
                        wall_clock_s=time.perf_counter() - started,
                        max_output_tokens=max_tokens,
                        provider_finish_reason=finish_reason,
                        generation_error=call_error,
                    )
                    _write_manifest(manifest, manifest_path)
                else:
                    source = None
                    try:
                        source = extract_module_source(
                            response or "", expected_module=plan.task.top_module
                        )
                        source_path.write_text(source, encoding="utf-8")
                        if official:
                            scored = run_task(
                                plan.task.task_id,
                                source_path,
                                manifest_path,
                                official=True,
                            )
                        else:
                            scored = run_task(
                                plan.task.task_id,
                                source_path,
                                manifest_path,
                            )
                        manifest = _merge_generation_fields(
                            scored,
                            provider_name=provider_name,
                            model=model,
                            temperature=temperature,
                            usage=usage,
                            max_output_tokens=max_tokens,
                            provider_finish_reason=finish_reason,
                        )
                        _write_manifest(manifest, manifest_path)
                    except Exception as exc:
                        # extract_module_source() can throw before source is ever assigned this
                        # run (e.g. no matching module in the response at all); in that case a
                        # stale sidecar from a prior campaign into this same directory must not
                        # be left looking like this attempt's output. If run_task() threw instead,
                        # source is not None -- this run's real (if unscored) extraction is
                        # already on disk, and we deliberately leave it rather than delete it.
                        if source is None:
                            source_path.unlink(missing_ok=True)
                            submission_sha256 = None
                        else:
                            submission_sha256 = hashlib.sha256(source.encode("utf-8")).hexdigest()
                        manifest = _zero_manifest(
                            plan.task,
                            provider_name=provider_name,
                            model=model,
                            temperature=temperature,
                            usage=usage,
                            wall_clock_s=time.perf_counter() - started,
                            max_output_tokens=max_tokens,
                            provider_finish_reason=finish_reason,
                            submission_sha256=submission_sha256,
                            generation_error=f"{type(exc).__name__}: {exc}",
                        )
                        _write_manifest(manifest, manifest_path)

            total_tokens_in += manifest.tokens_in
            total_tokens_out += manifest.tokens_out
            total_cost_usd += manifest.cost_usd
            scores.append(manifest.task_score)
            if plan.skip_reason is None:
                all_scores.append(manifest.task_score)
            sample_records.append(
                {
                    "sample": sample_number,
                    "score": manifest.task_score,
                    "manifest": f"{plan.task.task_id}/sample_{sample_number}.json",
                    "manifest_signature": manifest.signature,
                }
            )

        task_entry: dict[str, Any] = {
            "scores": scores,
            "mean_score": float(fmean(scores)),
            "samples": sample_records,
            "skipped": plan.skip_reason is not None,
        }
        if plan.skip_reason is not None:
            task_entry["skip_reason"] = plan.skip_reason
        summary_tasks[plan.task.task_id] = task_entry

    summary: dict[str, Any] = {
        "suite_version": SUITE_VERSION,
        "prompt_version": PROMPT_VERSION,
        "provider": provider_name,
        "model": model,
        "temperature": temperature,
        "official": official,
        "samples_per_task": samples,
        "task_ids": task_ids,
        "tasks": summary_tasks,
        "aggregate_mean": float(fmean(all_scores)) if all_scores else 0.0,
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "cost_usd": round(total_cost_usd, 12),
        "pre_run_estimate_usd": round(estimate, 12),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    atomic_write_text(model_root / "summary.json", json.dumps(summary, indent=2) + "\n")
    return summary


def _plan_task(task_id: str, *, official: bool) -> EvalPlan:
    task = resolve_task(task_id)
    if not official:
        return EvalPlan(task)
    try:
        task.task_yaml.require_official_reviews()
    except ValueError as exc:
        return EvalPlan(task, f"official review gate: {exc}")
    return EvalPlan(task)


def _preflight_cost(
    plans: list[EvalPlan],
    provider: ProviderAdapter,
    samples: int,
    max_tokens: int,
) -> tuple[float, float]:
    provider_name = str(getattr(provider, "name", provider.__class__.__name__.lower()))
    model = str(getattr(provider, "model", "unknown-model"))
    estimate = _estimate_plans_cost(plans, provider_name, model, samples, max_tokens)
    spend_path = Path(getattr(provider, "spend_path", DEFAULT_SPEND_PATH))
    spent = float(load_spend(spend_path).get("total_usd", 0.0))
    return estimate, max(0.0, spend_cap_from_env() - spent)


def _estimate_plans_cost(
    plans: list[EvalPlan],
    provider_name: str,
    model: str,
    samples: int,
    max_tokens: int,
) -> float:
    if provider_name == "mock":
        return 0.0
    estimate = 0.0
    for plan in plans:
        if plan.skip_reason is None:
            prompt, system = build_generation_prompt(plan.task)
            estimate += samples * worst_case_cost(
                provider_name,
                model,
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
            )
    return estimate


def _call_once(
    provider: ProviderAdapter,
    prompt: str,
    system: str,
    *,
    max_tokens: int,
) -> tuple[str | None, str | None, dict[str, int | float], str | None]:
    try:
        before = _provider_usage(provider)
    except Exception as exc:
        return None, f"provider usage error: {type(exc).__name__}: {exc}", _empty_usage(), None
    params = GenParams(
        model=str(getattr(provider, "model", "unknown-model")),
        temperature=float(getattr(provider, "temperature", 0.0)),
        max_tokens=max_tokens,
        seed=0,
    )
    try:
        response = provider.generate(prompt, system, params)
    except SpendCapExceeded:
        # A campaign-level event, not a per-sample failure: let it propagate to
        # eval_model()'s caller (harness/cli.py already handles it cleanly at the
        # top level) instead of being folded into a generic "provider error" that
        # scores this sample 0.0 indistinguishably from an incorrect submission.
        raise
    except Exception as exc:
        after = _provider_usage_or(provider, before)
        error = f"provider error: {type(exc).__name__}: {exc}"
        try:
            usage = _usage_delta(before, after)
        except Exception as usage_exc:
            error += f"; usage error: {type(usage_exc).__name__}: {usage_exc}"
            usage = _empty_usage()
        return None, error, usage, _provider_finish_reason(provider)
    try:
        after = _provider_usage(provider)
        usage = _usage_delta(before, after)
    except Exception as exc:
        return None, f"provider usage error: {type(exc).__name__}: {exc}", _empty_usage(), None
    return response, None, usage, _provider_finish_reason(provider)


def _recorded_temperature(provider: ProviderAdapter) -> TemperatureSetting:
    requested = float(getattr(provider, "temperature", 0.0))
    if requested < 0:
        raise ValueError("provider temperature must be nonnegative")
    recorded = getattr(provider, "manifest_temperature", requested)
    if recorded == "provider_default":
        return "provider_default"
    value = float(recorded)
    if value < 0:
        raise ValueError("manifest temperature must be nonnegative")
    return value


def _provider_usage(provider: ProviderAdapter) -> dict[str, int | float]:
    raw = getattr(provider, "usage", None)
    if not isinstance(raw, dict):
        raise ValueError("provider usage must be a mapping")
    values: dict[str, int | float] = {}
    for name in ("tokens_in", "tokens_out", "cost_usd"):
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ValueError(f"provider usage {name} must be nonnegative")
        values[name] = value
    return values


def _provider_finish_reason(provider: ProviderAdapter) -> str | None:
    """Best-effort read of the provider's most recent finish/stop reason. Unlike
    _provider_usage() this is not load-bearing for spend accounting, so a provider
    that doesn't expose it (or an unexpected type) degrades to None rather than
    raising."""

    value = getattr(provider, "last_finish_reason", None)
    return value if isinstance(value, str) else None


def _provider_usage_or(
    provider: ProviderAdapter,
    fallback: dict[str, int | float],
) -> dict[str, int | float]:
    try:
        return _provider_usage(provider)
    except Exception:
        return fallback


def _usage_delta(
    before: dict[str, int | float],
    after: dict[str, int | float],
) -> dict[str, int | float]:
    tokens_in = int(after["tokens_in"]) - int(before["tokens_in"])
    tokens_out = int(after["tokens_out"]) - int(before["tokens_out"])
    cost_usd = float(after["cost_usd"]) - float(before["cost_usd"])
    if tokens_in < 0 or tokens_out < 0 or cost_usd < -1e-12:
        raise ValueError("provider usage counters moved backwards")
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": max(0.0, cost_usd),
    }


def _empty_usage() -> dict[str, int | float]:
    return {"tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}


def _merge_generation_fields(
    scored: ResultManifest,
    *,
    provider_name: str,
    model: str,
    temperature: TemperatureSetting,
    usage: dict[str, int | float],
    max_output_tokens: int,
    provider_finish_reason: str | None = None,
) -> ResultManifest:
    data = scored.model_dump(mode="json", exclude_none=True)
    data.update(
        {
            "provider": provider_name,
            "model": model,
            "temperature": temperature,
            "tokens_in": int(usage["tokens_in"]),
            "tokens_out": int(usage["tokens_out"]),
            "cost_usd": float(usage["cost_usd"]),
            "prompt_version": PROMPT_VERSION,
            "max_output_tokens": max_output_tokens,
            "signature": "0" * 64,
        }
    )
    if provider_finish_reason is not None:
        data["provider_finish_reason"] = provider_finish_reason
    data["signature"] = compute_manifest_signature(data)
    return ResultManifest.model_validate(data)


def _zero_manifest(
    task: TaskPackage,
    *,
    provider_name: str,
    model: str,
    temperature: TemperatureSetting,
    usage: dict[str, int | float],
    wall_clock_s: float,
    max_output_tokens: int,
    generation_error: str | None = None,
    official_skip_reason: str | None = None,
    provider_finish_reason: str | None = None,
    submission_sha256: str | None = None,
) -> ResultManifest:
    skipped = official_skip_reason is not None
    stages = [
        {
            "stage": index,
            "name": name,
            "status": "skip" if skipped or index == 6 else "fail",
        }
        for index, name in enumerate(STAGE_NAMES)
    ]
    data: dict[str, Any] = {
        "task_id": task.task_id,
        "suite_version": SUITE_VERSION,
        "docker_digest": runtime_docker_digest(),
        "platform": "linux/amd64",
        "stages": stages,
        "sec": 0.0,
        "ppa": 0.0,
        "task_score": 0.0,
        "wall_clock_s": round(max(0.0, wall_clock_s), 6),
        "provider": provider_name,
        "model": model,
        "temperature": temperature,
        "tokens_in": int(usage["tokens_in"]),
        "tokens_out": int(usage["tokens_out"]),
        "cost_usd": float(usage["cost_usd"]),
        "prompt_version": PROMPT_VERSION,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "harness_git": harness_git(),
        "max_output_tokens": max_output_tokens,
        "signature": "0" * 64,
    }
    if generation_error is not None:
        data["generation_error"] = generation_error
    if official_skip_reason is not None:
        data["official_skip_reason"] = official_skip_reason
    if provider_finish_reason is not None:
        data["provider_finish_reason"] = provider_finish_reason
    if submission_sha256 is not None:
        data["submission_sha256"] = submission_sha256
    data["signature"] = compute_manifest_signature(data)
    return ResultManifest.model_validate(data)


def _write_manifest(manifest: ResultManifest, path: Path) -> None:
    atomic_write_text(
        path,
        json.dumps(manifest.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
    )


def _safe_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return component or "model"
