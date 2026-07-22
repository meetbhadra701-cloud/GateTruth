"""Track B batch agent-evaluation orchestration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

from harness.agentb import load_budget, provider_usage, run_agent_task
from harness.providers import GenParams, ProviderAdapter
from harness.providers.pricing import price_for
from harness.runner import SUITE_VERSION
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest_b import AgentTrackBManifest
from harness.spend import DEFAULT_SPEND_PATH, SpendCapExceeded, load_spend, spend_cap_from_env
from harness.trackb import TRACKB_ROOT, TrackBPackage, resolve_track_b_task

SUMMARY_VERSION = "track-b-agent-eval-v1"
SIGNED_REVIEW_RE = re.compile(r"SIGNED-OFF-BY-MEET-\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class EvalAgentPlan:
    package: TrackBPackage
    skip_reason: str | None = None


class _TaskUsageProvider:
    """Delegate generation while exposing usage relative to one task's start."""

    def __init__(self, provider: ProviderAdapter) -> None:
        self._provider = provider
        self._start = provider_usage(provider)
        self.name = str(getattr(provider, "name", provider.__class__.__name__.lower()))
        self.model = str(getattr(provider, "model", "agent"))
        self.temperature = float(getattr(provider, "temperature", 0.0))

    def generate(self, spec: str, interface: str, params: GenParams) -> str:
        return self._provider.generate(spec, interface, params)

    @property
    def usage(self) -> dict[str, int | float]:
        current = provider_usage(self._provider)
        tokens_in = int(current["tokens_in"]) - int(self._start["tokens_in"])
        tokens_out = int(current["tokens_out"]) - int(self._start["tokens_out"])
        cost_usd = float(current["cost_usd"]) - float(self._start["cost_usd"])
        if tokens_in < 0 or tokens_out < 0 or cost_usd < -1e-12:
            raise ValueError("provider usage counters moved backwards")
        return {
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": max(0.0, cost_usd),
        }


def track_b_task_ids() -> list[str]:
    """Return every frozen Track B task id in deterministic order."""

    return sorted(path.parent.name for path in TRACKB_ROOT.glob("*/objective.yaml"))


def estimate_agent_cost(
    task_ids: list[str],
    provider_name: str,
    model: str,
    *,
    official: bool = False,
) -> float:
    """Estimate a Track B matrix from each package's frozen token budget."""

    if not task_ids:
        raise ValueError("at least one Track B task is required")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Track B task ids must be unique")
    if not provider_name or not model:
        raise ValueError("provider and model names must be nonempty")
    plans = [_plan_task(task_id, official=official) for task_id in task_ids]
    return _estimate_plans_cost(plans, provider_name, model)


def eval_agent(
    task_ids: list[str],
    provider: ProviderAdapter,
    *,
    out_dir: str | Path,
    official: bool = False,
) -> dict[str, Any]:
    """Run one Track B agent per task and emit a signed aggregate summary."""

    if not task_ids:
        raise ValueError("at least one Track B task is required")
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("Track B task ids must be unique")
    provider_name = str(getattr(provider, "name", provider.__class__.__name__.lower()))
    model = str(getattr(provider, "model", "agent"))
    if not provider_name or not model:
        raise ValueError("provider and model names must be nonempty")

    plans = [_plan_task(task_id, official=official) for task_id in task_ids]
    estimate, remaining = _preflight_cost(plans, provider)
    print(f"pre_run_estimate_usd={estimate:.6f}")
    print(f"remaining_spend_cap_usd={remaining:.6f}")
    if estimate > remaining + 1e-12:
        raise SpendCapExceeded(
            f"pre-run estimate {estimate:.6f} exceeds remaining cap {remaining:.6f}"
        )

    model_root = Path(out_dir) / _safe_component(model)
    model_root.mkdir(parents=True, exist_ok=True)
    task_rows: dict[str, dict[str, Any]] = {}
    manifests: list[AgentTrackBManifest] = []

    for plan in plans:
        task_id = plan.package.task_id
        if plan.skip_reason is not None:
            task_rows[task_id] = {
                "skipped": True,
                "skip_reason": plan.skip_reason,
                "manifest": None,
                "objective_pass": False,
                "disqualified": False,
                "budget_exceeded": None,
                "tokens_in": 0,
                "tokens_out": 0,
                "cost_usd": 0.0,
                "ppa_delta": _empty_ppa_delta(),
            }
            continue

        output = model_root / f"{_safe_component(task_id)}.json"
        task_provider = _TaskUsageProvider(provider)
        manifest = run_agent_task(task_id, task_provider, out=output)
        manifests.append(manifest)
        task_rows[task_id] = {
            "skipped": False,
            "manifest": output.name,
            "objective_pass": manifest.objective_pass,
            "disqualified": manifest.disqualified,
            "budget_exceeded": manifest.budget_exceeded,
            "tokens_in": manifest.tokens_in,
            "tokens_out": manifest.tokens_out,
            "cost_usd": manifest.cost_usd,
            "ppa_delta": {
                "area_ratio": manifest.ppa_delta.area_ratio,
                "power_ratio": manifest.ppa_delta.power_ratio,
                "wns_delta_ns": manifest.ppa_delta.wns_delta_ns,
            },
        }

    attempted = len(manifests)
    passed = sum(manifest.objective_pass for manifest in manifests)
    summary: dict[str, Any] = {
        "summary_version": SUMMARY_VERSION,
        "suite_version": SUITE_VERSION,
        "track": "B",
        "provider": provider_name,
        "model": model,
        "official": official,
        "task_ids": task_ids,
        "tasks": task_rows,
        "tasks_attempted": attempted,
        "tasks_objective_met": passed,
        "objective_met_rate": passed / attempted if attempted else 0.0,
        "median_ppa_delta": {
            "area_ratio": _median_metric(manifests, "area_ratio"),
            "power_ratio": _median_metric(manifests, "power_ratio"),
            "wns_delta_ns": _median_metric(manifests, "wns_delta_ns"),
        },
        "tokens_in": sum(manifest.tokens_in for manifest in manifests),
        "tokens_out": sum(manifest.tokens_out for manifest in manifests),
        "cost_usd": round(sum(manifest.cost_usd for manifest in manifests), 12),
        "pre_run_estimate_usd": round(estimate, 12),
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signature": "0" * 64,
    }
    summary["signature"] = compute_manifest_signature(summary)
    (model_root / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def _plan_task(task_id: str, *, official: bool) -> EvalAgentPlan:
    package = resolve_track_b_task(task_id)
    if not official:
        return EvalAgentPlan(package)
    reason = _official_skip_reason(package.root / "task.yaml")
    return EvalAgentPlan(package, reason)


def _official_skip_reason(path: Path) -> str | None:
    reviews: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip().strip('"\'') for part in line.split(":", 1))
        if key in {"baseline_review", "tb_review"}:
            if key in reviews:
                raise ValueError(f"duplicate {key} in {path}")
            reviews[key] = value
    pending = [
        f"{field}={reviews.get(field, 'MISSING')}"
        for field in ("baseline_review", "tb_review")
        if SIGNED_REVIEW_RE.fullmatch(reviews.get(field, "")) is None
    ]
    if not pending:
        return None
    return "official review gate: " + "; ".join(pending)


def _preflight_cost(
    plans: list[EvalAgentPlan],
    provider: ProviderAdapter,
) -> tuple[float, float]:
    provider_name = str(getattr(provider, "name", provider.__class__.__name__.lower()))
    model = str(getattr(provider, "model", "agent"))
    estimate = _estimate_plans_cost(plans, provider_name, model)
    spend_path = Path(getattr(provider, "spend_path", DEFAULT_SPEND_PATH))
    spent = float(load_spend(spend_path).get("total_usd", 0.0))
    return estimate, max(0.0, spend_cap_from_env() - spent)


def _estimate_plans_cost(
    plans: list[EvalAgentPlan],
    provider_name: str,
    model: str,
) -> float:
    if provider_name == "mock":
        return 0.0
    price = price_for(provider_name, model)
    estimate = 0.0
    for plan in plans:
        if plan.skip_reason is not None:
            continue
        budget = load_budget(plan.package.root / "objective.yaml")
        # The budget is combined input/output, so reserve it at the higher rate.
        estimate += price.cost(0, budget.tokens)
    return estimate


def _median_metric(manifests: list[AgentTrackBManifest], field: str) -> float | None:
    values = [
        float(value)
        for manifest in manifests
        if (value := getattr(manifest.ppa_delta, field)) is not None
    ]
    return float(median(values)) if values else None


def _empty_ppa_delta() -> dict[str, None]:
    return {"area_ratio": None, "power_ratio": None, "wns_delta_ns": None}


def _safe_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return component or "run"
