"""Track B agent driver with a strictly sandboxed JSON action protocol."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from harness.atomic_write import atomic_write_text
from harness.flows import FlowError, run_sta, run_synth
from harness.providers import GenParams, ProviderAdapter
from harness.providers._http import ProviderRetryableError
from harness.runner import TaskPackage, run_lint, run_sim
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import TemperatureSetting
from harness.schemas.manifest_b import AgentTrackBManifest
from harness.spend import SpendCapExceeded
from harness.trackb import resolve_track_b_task, run_track_b, single_sv_file
from harness.validation import SubmissionValidationError, validate_source_text

BudgetLimit = Literal["tokens", "wall_clock_s", "tool_calls", "spend_cap"]
ACTION_TO_KEYS = {
    "read_file": {"tool", "path"},
    "write_design": {"tool", "content"},
    "sb_lint": {"tool"},
    "sb_sim": {"tool"},
    "sb_synth_sta": {"tool"},
    "done": {"tool"},
}
ACTION_PROTOCOL = (
    "Return exactly one JSON object. Supported actions: "
    '{"tool":"read_file","path":"relative/path"}, '
    '{"tool":"write_design","content":"complete SystemVerilog"}, '
    '{"tool":"sb_lint"}, {"tool":"sb_sim"}, {"tool":"sb_synth_sta"}, {"tool":"done"}.'
)
PER_CALL_MAX_OUTPUT_TOKENS = 16_384
TRANSPORT_RETRY_DELAYS_S = (0.25, 0.5)


@dataclass(frozen=True)
class Budget:
    tokens: int
    wall_clock_s: float
    tool_calls: int


class ActionRejected(ValueError):
    """Raised when an agent action violates the sandbox protocol."""


def run_agent_task(
    task_id: str,
    provider: ProviderAdapter,
    *,
    out: str | Path,
    official: bool = False,
) -> AgentTrackBManifest:
    """Run a provider in a temporary Track B package and score the final design."""

    package = resolve_track_b_task(task_id)
    budget = load_budget(package.root / "objective.yaml")
    out_path = Path(out)
    started = time.perf_counter()
    transcript: list[dict[str, Any]] = []
    tool_calls = 0
    budget_exceeded: BudgetLimit | None = None

    with tempfile.TemporaryDirectory(prefix="gatetruth-agentb-") as temp:
        temp_root = Path(temp)
        sandbox = temp_root / "submission"
        shutil.copytree(package.root, sandbox)
        tool_root = temp_root / "tool_runs"
        tool_root.mkdir()

        while True:
            budget_exceeded = _fired_limit(budget, provider, tool_calls, started)
            if budget_exceeded is not None:
                break

            prompt = json.dumps(
                {"task_id": task_id, "transcript": transcript},
                separators=(",", ":"),
            )
            remaining = max(budget.tokens - _token_total(provider), 1)
            params = GenParams(
                model=str(getattr(provider, "model", "agent")),
                temperature=float(getattr(provider, "temperature", 0.0)),
                max_tokens=min(remaining, PER_CALL_MAX_OUTPUT_TOKENS),
                seed=0,
            )
            try:
                raw_action = _generate_with_transport_retry(
                    provider,
                    prompt,
                    params,
                )
            except SpendCapExceeded as exc:
                budget_exceeded = "spend_cap"
                transcript.append(
                    {
                        "action": None,
                        "observation": {
                            "status": "budget_exceeded",
                            "error": str(exc),
                        },
                    }
                )
                break
            except Exception as exc:
                transcript.append(
                    {
                        "action": None,
                        "observation": {
                            "status": "provider_error",
                            "error": f"{type(exc).__name__}: {exc}",
                        },
                    }
                )
                break

            tool_calls += 1
            action: dict[str, Any] | None = None
            done = False
            try:
                action = validate_action(raw_action)
                observation, done = execute_action(
                    action,
                    sandbox=sandbox,
                    task_id=task_id,
                    top_module=package.top_module,
                    clock_target_ns=package.clock_target_ns,
                    work_root=tool_root / f"call_{tool_calls}",
                )
            except (ActionRejected, FlowError, OSError, ValueError) as exc:
                observation = {
                    "status": "rejected",
                    "error": f"{type(exc).__name__}: {exc}",
                }

            transcript.append(
                {
                    "action": action if action is not None else raw_action,
                    "observation": observation,
                }
            )
            if done:
                break

            budget_exceeded = _fired_limit(budget, provider, tool_calls, started)
            if budget_exceeded is not None:
                break

        if official:
            evaluator_manifest = run_track_b(
                task_id,
                sandbox,
                out_path,
                official=True,
            )
        else:
            evaluator_manifest = run_track_b(task_id, sandbox, out_path)
        usage = provider_usage(provider)
        data = evaluator_manifest.model_dump(mode="json")
        data.update(
            {
                "provider": str(getattr(provider, "name", provider.__class__.__name__.lower())),
                "model": str(getattr(provider, "model", "agent")),
                "temperature": _recorded_temperature(provider),
                "tokens_in": int(usage["tokens_in"]),
                "tokens_out": int(usage["tokens_out"]),
                "cost_usd": float(usage["cost_usd"]),
                "tool_calls": tool_calls,
                "wall_clock_s": round(time.perf_counter() - started, 6),
                "budget_exceeded": budget_exceeded,
                "signature": "0" * 64,
            }
        )
        data["signature"] = compute_manifest_signature(data)
        manifest = AgentTrackBManifest.model_validate(data)
        atomic_write_text(
            out_path,
            json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
        )
        atomic_write_text(
            out_path.with_suffix(".transcript.json"),
            json.dumps(transcript, indent=2) + "\n",
        )
        return manifest


def _generate_with_transport_retry(
    provider: ProviderAdapter,
    prompt: str,
    params: GenParams,
) -> str:
    for attempt in range(len(TRANSPORT_RETRY_DELAYS_S) + 1):
        try:
            return provider.generate(prompt, ACTION_PROTOCOL, params)
        except ProviderRetryableError:
            if attempt == len(TRANSPORT_RETRY_DELAYS_S):
                raise
            _retry_sleep(TRANSPORT_RETRY_DELAYS_S[attempt])
    raise AssertionError("transport retry loop did not return or raise")


def _retry_sleep(delay_s: float) -> None:
    time.sleep(delay_s)


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


def load_budget(path: Path) -> Budget:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?m)^\s*budget:\s*\{([^}]*)\}\s*$", text)
    if not match:
        raise ValueError(f"missing inline budget in {path}")
    values: dict[str, float] = {}
    for item in match.group(1).split(","):
        key, separator, raw = item.partition(":")
        if not separator:
            raise ValueError(f"malformed budget item: {item.strip()}")
        values[key.strip()] = float(raw.strip())
    required = {"tokens", "wall_clock_s", "tool_calls"}
    if set(values) != required:
        raise ValueError(f"budget keys must be {sorted(required)}")
    budget = Budget(
        tokens=int(values["tokens"]),
        wall_clock_s=values["wall_clock_s"],
        tool_calls=int(values["tool_calls"]),
    )
    if budget.tokens <= 0 or budget.wall_clock_s <= 0 or budget.tool_calls <= 0:
        raise ValueError("budget limits must be positive")
    return budget


def validate_action(raw_action: str) -> dict[str, Any]:
    if not isinstance(raw_action, str):
        raise ActionRejected("provider action must be a JSON string")
    try:
        action = json.loads(raw_action)
    except json.JSONDecodeError as exc:
        raise ActionRejected(f"invalid JSON action: {exc.msg}") from exc
    if not isinstance(action, dict):
        raise ActionRejected("action must be a JSON object")
    tool = action.get("tool")
    if tool not in ACTION_TO_KEYS:
        raise ActionRejected(f"unsupported tool: {tool!r}")
    expected = ACTION_TO_KEYS[tool]
    if set(action) != expected:
        raise ActionRejected(
            f"{tool} keys must be {sorted(expected)}, got {sorted(action)}"
        )
    if tool == "read_file" and (
        not isinstance(action["path"], str) or not action["path"]
    ):
        raise ActionRejected("read_file path must be a nonempty string")
    if tool == "write_design" and not isinstance(action["content"], str):
        raise ActionRejected("write_design content must be a string")
    return action


def execute_action(
    action: dict[str, Any],
    *,
    sandbox: Path,
    task_id: str,
    top_module: str,
    clock_target_ns: float,
    work_root: Path,
) -> tuple[dict[str, Any], bool]:
    tool = action["tool"]
    if tool == "read_file":
        target = sandbox_path(sandbox, action["path"])
        if not target.is_file():
            raise ActionRejected(f"read target is not a file: {action['path']}")
        return {"status": "ok", "content": target.read_text(encoding="utf-8")}, False

    if tool == "write_design":
        try:
            validate_source_text(action["content"])
        except SubmissionValidationError as exc:
            raise ActionRejected(str(exc)) from exc
        design = single_sv_file(sandbox / "design")
        design.write_text(action["content"], encoding="utf-8")
        return {"status": "ok", "path": design.relative_to(sandbox).as_posix()}, False

    if tool == "done":
        return {"status": "ok", "message": "agent finished"}, True

    design = single_sv_file(sandbox / "design")
    work_root.mkdir(parents=True, exist_ok=True)
    if tool == "sb_lint":
        stage, log = run_lint(design)
        return {"status": stage["status"], "stage": stage, "stdout_tail": tail(log)}, False

    task = TaskPackage(
        task_id=task_id,
        root=sandbox,
        task_yaml=SimpleNamespace(formal=False),
        top_module=top_module,
    )
    if tool == "sb_sim":
        stage, log, _hidden_sha256, _hidden_test_count = run_sim(task, design, work_root)
        return {"status": stage["status"], "stage": stage, "stdout_tail": tail(log)}, False

    if tool == "sb_synth_sta":
        synth = run_synth(
            submission=design,
            top_module=top_module,
            clock_target_ns=clock_target_ns,
            work_root=work_root,
        )
        sta = run_sta(
            netlist=synth.netlist,
            top_module=top_module,
            constraints=sandbox / "constraints.sdc",
            clock_target_ns=clock_target_ns,
        )
        return {
            "status": "pass",
            "area_um2": synth.area_um2,
            "cell_count": synth.cell_count,
            "wns_ns": sta.wns_ns,
            "tns_ns": sta.tns_ns,
            "fmax_mhz": sta.fmax_mhz,
            "stdout_tail": tail(synth.log + "\n" + sta.log),
        }, False

    raise AssertionError(f"validated tool not handled: {tool}")


def sandbox_path(sandbox: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        raise ActionRejected("absolute paths are forbidden")
    root = sandbox.resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise ActionRejected("path escapes the sandbox")
    return target


def provider_usage(provider: ProviderAdapter) -> dict[str, int | float]:
    raw = getattr(provider, "usage", {})
    if callable(raw):
        raw = raw()
    if not isinstance(raw, dict):
        raise ValueError("provider usage must be a mapping")
    usage: dict[str, int | float] = {
        "tokens_in": raw.get("tokens_in", 0),
        "tokens_out": raw.get("tokens_out", 0),
        "cost_usd": raw.get("cost_usd", 0.0),
    }
    if any(not isinstance(value, (int, float)) or value < 0 for value in usage.values()):
        raise ValueError("provider usage values must be nonnegative numbers")
    return usage


def _token_total(provider: ProviderAdapter) -> int:
    usage = provider_usage(provider)
    return int(usage["tokens_in"]) + int(usage["tokens_out"])


def _fired_limit(
    budget: Budget,
    provider: ProviderAdapter,
    tool_calls: int,
    started: float,
) -> BudgetLimit | None:
    if time.perf_counter() - started >= budget.wall_clock_s:
        return "wall_clock_s"
    if _token_total(provider) >= budget.tokens:
        return "tokens"
    if tool_calls >= budget.tool_calls:
        return "tool_calls"
    return None


def tail(text: str, limit: int = 4000) -> str:
    return text[-limit:]
