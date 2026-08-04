"""Generate deterministic GateTruth paper data tables from live repository data."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import fmean
from statistics import median as statistics_median
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.git_provenance import harness_git  # noqa: E402
from harness.schemas.canonical_json import compute_manifest_signature  # noqa: E402
from harness.schemas.manifest import load_manifest  # noqa: E402
from harness.schemas.manifest_b import load_agent_manifest_b  # noqa: E402
from harness.schemas.task_yaml import load_task_yaml  # noqa: E402
from harness.scoring import load_reference_metrics, score_manifest  # noqa: E402
from harness.trackb import validate_track_b_semantics  # noqa: E402

TRACK_A_SUITE_SIZE = 60
TRACK_B_SUITE_SIZE = 8


class TableDataError(ValueError):
    """Raised when live table input is malformed or untrusted."""


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    tier: str
    formal: bool
    clock_ns: float
    area_um2: float | None
    wns_ns: float | None
    power_mw: float | None


@dataclass(frozen=True)
class MutationRecord:
    task_id: str
    mutants: int
    killed: int
    kill_rate: float


@dataclass(frozen=True)
class EvalRecord:
    provider: str
    model: str
    tasks: int
    aggregate_score: float
    tokens: int
    cost_usd: float
    pass_count: int
    mean_ppa_passed: float | None


@dataclass(frozen=True)
class PPADeltaRecord:
    area_ratio: float | None
    power_ratio: float | None
    wns_delta_ns: float | None


@dataclass(frozen=True)
class AgentEvalRecord:
    provider: str
    model: str
    tasks_attempted: int
    tasks_objective_met: int
    objective_met_rate: float
    median_ppa_delta: PPADeltaRecord
    cost_usd: float
    tokens: int


def generate_tables(
    *,
    out_dir: str | Path,
    tasks_root: str | Path = REPO_ROOT / "tasks",
    refs_dir: str | Path = REPO_ROOT / "results" / "refs",
    mutation_dir: str | Path = REPO_ROOT / "results" / "mutation" / "certification",
    eval_dir: str | Path = REPO_ROOT / "results" / "eval",
    agent_eval_dir: str | Path = REPO_ROOT / "results" / "evalB",
    agent_tasks_root: str | Path = REPO_ROOT / "tasksB",
    generated_date: date | None = None,
    git_sha: str | None = None,
) -> dict[str, Path]:
    """Load live data and write all eight Markdown/LaTeX table artifacts."""

    run_date = generated_date or datetime.now(UTC).date()
    sha = git_sha or harness_git(repo_root=REPO_ROOT)
    tasks = load_tasks(Path(tasks_root), Path(refs_dir))
    track_a_ids = frozenset(row.task_id for row in tasks)
    track_b_ids = _canonical_task_ids(Path(agent_tasks_root), "objective.yaml")
    if Path(tasks_root).resolve() == (REPO_ROOT / "tasks").resolve():
        _require_suite_size("Track A", track_a_ids, TRACK_A_SUITE_SIZE)
    if Path(agent_tasks_root).resolve() == (REPO_ROOT / "tasksB").resolve():
        _require_suite_size("Track B", track_b_ids, TRACK_B_SUITE_SIZE)
    mutations = load_mutations(Path(mutation_dir), track_a_ids)
    evaluations = load_evaluations(Path(eval_dir), track_a_ids)
    agent_evaluations = load_agent_evaluations(Path(agent_eval_dir), track_b_ids)
    metadata = f"generated-on: {run_date.isoformat()} git-sha: {sha}"
    artifacts = {
        "eval_table.md": _eval_markdown(evaluations, metadata),
        "eval_table.tex": _eval_latex(evaluations, metadata),
        "mutation_table.md": _mutation_markdown(mutations, metadata),
        "mutation_table.tex": _mutation_latex(mutations, metadata),
        "tasks_table.md": _tasks_markdown(tasks, metadata),
        "tasks_table.tex": _tasks_latex(tasks, metadata),
        "trackb_table.md": _trackb_markdown(agent_evaluations, metadata),
        "trackb_table.tex": _trackb_latex(agent_evaluations, metadata),
    }
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for name, content in sorted(artifacts.items()):
        path = output / name
        path.write_text(content, encoding="utf-8", newline="\n")
        paths[name] = path
    return paths


def load_tasks(tasks_root: Path, refs_dir: Path) -> list[TaskRecord]:
    """Load task metadata and optional signed reference PPA manifests."""

    records: list[TaskRecord] = []
    for task_path in sorted(tasks_root.glob("*/task.yaml")):
        task = load_task_yaml(task_path)
        manifest = _reference_manifest(task.id, refs_dir)
        if manifest:
            area = _stage_metric(manifest, 3, "area_um2")
            wns = _stage_metric(manifest, 4, "wns_ns")
            power = _stage_metric(manifest, 5, "power_mw")
        elif tasks_root.resolve() == (REPO_ROOT / "tasks").resolve():
            metrics = load_reference_metrics(task.id)
            area = metrics.area_um2
            wns = metrics.clock_target_ns - metrics.delay_ns
            power = metrics.power_mw
        else:
            area = None
            wns = None
            power = None
        records.append(
            TaskRecord(
                task_id=task.id,
                tier=task.tier,
                formal=task.formal,
                clock_ns=task.clock_target_ns,
                area_um2=area,
                wns_ns=wns,
                power_mw=power,
            )
        )
    if not records:
        raise TableDataError(f"no task.yaml files found under {tasks_root}")
    return records


def load_mutations(
    directory: Path,
    expected_task_ids: frozenset[str] | None = None,
) -> list[MutationRecord]:
    """Load every per-task report directly inside the one versioned certification
    directory. Intentionally flat, not recursive: results/mutation/ has held
    stray non-certification artifacts before (ad hoc determinism-check repeats),
    and an unbounded walk would silently let one of those overwrite a real
    task's row instead of only ever reading the certification set itself.

    Requires exactly the canonical task set (missing or extra reports both
    rejected) and refuses a report with zero generated mutants: this loader has
    no signed-provenance record to check yet (that is GTFS-030's still-open
    scope, a much larger schema/re-certification change), so completeness and a
    positive mutant count are the two checks available here that stop a
    partial, unsupported, or fabricated-100%-via-zero-mutants set of reports
    from silently rendering as a full, real 60-task certification (GTFS-035).
    """

    expected = (
        expected_task_ids
        if expected_task_ids is not None
        else _canonical_task_ids(REPO_ROOT / "tasks", "task.yaml")
    )
    if not expected:
        raise TableDataError("mutation expected task set must not be empty")
    if expected_task_ids is None:
        _require_suite_size("mutation", expected, TRACK_A_SUITE_SIZE)

    latest: dict[str, MutationRecord] = {}
    if not directory.is_dir():
        return []
    for path in sorted(directory.glob("*.json")):
        if path.name == "summary.json":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TableDataError(f"invalid mutation JSON {path}: {exc}") from exc
        if not isinstance(raw, dict) or "kill_rate" not in raw:
            continue
        status = raw.get("status")
        if status is not None and status != "ok":
            raise TableDataError(
                f"mutation report {path} has status={status!r}, not ok -- "
                "a broken or unsupported task must not silently render as a "
                "measured kill rate in a paper table"
            )
        task_id = _text(raw, "task", path)
        if task_id in latest:
            raise TableDataError(
                f"duplicate mutation certification for {task_id}: "
                f"{path} conflicts with an earlier file for the same task"
            )
        total = _integer(raw, "total", path)
        if total == 0:
            raise TableDataError(
                f"mutation report {path} generated zero mutants -- a task with "
                "no mutants ever tested is a setup failure, not a certified "
                "100% kill rate"
            )
        killed = _integer(raw, "killed", path)
        kill_rate = _number(raw, "kill_rate", path)
        if killed > total or kill_rate < 0 or kill_rate > 100:
            raise TableDataError(f"invalid mutation counts in {path}")
        expected_rate = 100.0 * killed / total
        if not math.isclose(kill_rate, expected_rate, abs_tol=0.01):
            raise TableDataError(f"mutation kill rate mismatch in {path}")
        latest[task_id] = MutationRecord(task_id, total, killed, kill_rate)

    actual = frozenset(latest)
    if actual != expected:
        raise TableDataError(
            "mutation certification set mismatch: "
            + _task_set_mismatch(expected, actual)
        )
    return [latest[task_id] for task_id in sorted(latest)]


def load_evaluations(
    directory: Path,
    expected_task_ids: frozenset[str] | None = None,
) -> list[EvalRecord]:
    """Load one complete, signed Track A summary per provider/model."""

    if not directory.is_dir():
        return []
    expected = (
        expected_task_ids
        if expected_task_ids is not None
        else _canonical_task_ids(REPO_ROOT / "tasks", "task.yaml")
    )
    if not expected:
        raise TableDataError("Track A expected task set must not be empty")
    if expected_task_ids is None:
        _require_suite_size("Track A", expected, TRACK_A_SUITE_SIZE)
    candidates = _signed_summary_candidates(directory, "eval")
    records: list[EvalRecord] = []
    for key, runs in sorted(candidates.items()):
        complete: list[tuple[Path, dict[str, Any]]] = []
        reasons: list[tuple[Path, str]] = []
        for path, raw in runs:
            reason = _track_a_incomplete_reason(raw, path, expected)
            if reason is None:
                complete.append((path, raw))
            else:
                reasons.append((path, reason))
        if not complete:
            _warn_omitted_run("Track A", key, reasons)
            continue
        if len(complete) > 1:
            _raise_ambiguous_run("Track A", key, complete)
        path, raw = complete[0]
        per_task = _track_a_validated_scores(raw, path, expected)
        pass_count = 0
        ppas: list[float] = []
        total_tokens = 0
        total_cost = 0.0
        task_scores: list[float] = []
        for task_id in expected:
            score, tokens, cost = per_task[task_id]
            task_scores.append(score)
            total_tokens += tokens
            total_cost += cost
            if score > 0:
                pass_count += 1
                ppas.append(score * 1.5 / 100.0)

        real_aggregate = fmean(task_scores)
        claimed_aggregate = _number(raw, "aggregate_mean", path)
        if not math.isclose(claimed_aggregate, real_aggregate, abs_tol=1e-6):
            raise TableDataError(
                f"aggregate_mean {claimed_aggregate} does not match the mean of "
                f"{len(task_scores)} recomputed child task scores "
                f"({real_aggregate}) in {path}"
            )
        claimed_tokens = _integer(raw, "tokens_in", path) + _integer(
            raw, "tokens_out", path
        )
        if claimed_tokens != total_tokens:
            raise TableDataError(
                f"tokens_in+tokens_out ({claimed_tokens}) does not match the sum "
                f"of child manifest tokens ({total_tokens}) in {path}"
            )
        claimed_cost = _number(raw, "cost_usd", path)
        if not math.isclose(claimed_cost, total_cost, abs_tol=1e-6):
            raise TableDataError(
                f"cost_usd {claimed_cost} does not match the sum of child "
                f"manifest costs ({total_cost}) in {path}"
            )

        records.append(
            EvalRecord(
                provider=_text(raw, "provider", path),
                model=_text(raw, "model", path),
                tasks=len(expected),
                aggregate_score=real_aggregate,
                tokens=total_tokens,
                cost_usd=total_cost,
                pass_count=pass_count,
                mean_ppa_passed=(sum(ppas) / len(ppas)) if ppas else None,
            )
        )
    return sorted(records, key=lambda row: (-row.aggregate_score, row.model, row.provider))


def _track_a_validated_scores(
    raw: dict[str, Any],
    summary_path: Path,
    expected: frozenset[str],
) -> dict[str, tuple[float, int, float]]:
    """For every task, independently recompute its real task_score via
    score_manifest() -- which re-derives PPA from the manifest's own recorded
    stage metrics rather than trusting its ppa/task_score fields (GTFS-007) -- on
    every sample manifest that _track_a_incomplete_reason already proved exists
    and matches its signed summary entry. A tampered summary whose child
    manifests are untouched (GTFS-034's exact reproduction) is caught here: the
    summary's own aggregate/tokens/cost claims are never trusted, only these
    recomputed values are. Returns task_id -> (mean_score, tokens, cost_usd).
    """

    result: dict[str, tuple[float, int, float]] = {}
    for task_id in expected:
        samples = raw["tasks"][task_id]["samples"]
        scores: list[float] = []
        tokens = 0
        cost = 0.0
        for sample in samples:
            manifest_path = _referenced_manifest(summary_path, sample.get("manifest"))
            if manifest_path is None:
                raise TableDataError(f"{task_id} has an invalid manifest reference")
            scores.append(score_manifest(manifest_path))
            manifest = load_manifest(manifest_path)
            tokens += manifest.tokens_in + manifest.tokens_out
            cost += manifest.cost_usd
        result[task_id] = (fmean(scores), tokens, cost)
    return result


def load_agent_evaluations(
    directory: Path,
    expected_task_ids: frozenset[str] | None = None,
) -> list[AgentEvalRecord]:
    """Load one complete, signed Track B summary per provider/model."""

    if not directory.is_dir():
        return []
    expected = (
        expected_task_ids
        if expected_task_ids is not None
        else _canonical_task_ids(REPO_ROOT / "tasksB", "objective.yaml")
    )
    if not expected:
        raise TableDataError("Track B expected task set must not be empty")
    if expected_task_ids is None:
        _require_suite_size("Track B", expected, TRACK_B_SUITE_SIZE)
    candidates = _signed_summary_candidates(directory, "agent eval")
    records: list[AgentEvalRecord] = []
    for key, runs in sorted(candidates.items()):
        complete: list[tuple[Path, dict[str, Any]]] = []
        reasons: list[tuple[Path, str]] = []
        for path, raw in runs:
            reason = _track_b_incomplete_reason(raw, path, expected)
            if reason is None:
                complete.append((path, raw))
            else:
                reasons.append((path, reason))
        if not complete:
            _warn_omitted_run("Track B", key, reasons)
            continue
        if len(complete) > 1:
            _raise_ambiguous_run("Track B", key, complete)

        path, raw = complete[0]
        validated = _track_b_validated_results(raw, path, expected)

        objective_met = sum(1 for v in validated.values() if v.objective_pass)
        attempted = len(expected)
        real_rate = objective_met / attempted if attempted else 0.0
        claimed_attempted = _integer(raw, "tasks_attempted", path)
        claimed_objective_met = _integer(raw, "tasks_objective_met", path)
        claimed_rate = _number(raw, "objective_met_rate", path)
        if claimed_attempted != attempted:
            raise TableDataError(
                f"tasks_attempted {claimed_attempted} does not match the "
                f"canonical suite size {attempted} in {path}"
            )
        if claimed_objective_met != objective_met:
            raise TableDataError(
                f"tasks_objective_met {claimed_objective_met} does not match "
                f"{objective_met} recomputed from child manifests in {path}"
            )
        if not math.isclose(claimed_rate, real_rate, abs_tol=1e-12):
            raise TableDataError(
                f"objective_met_rate {claimed_rate} does not match "
                f"{real_rate} recomputed from child manifests in {path}"
            )

        area_ratios = [
            v.area_ratio for v in validated.values() if v.area_ratio is not None
        ]
        power_ratios = [
            v.power_ratio for v in validated.values() if v.power_ratio is not None
        ]
        wns_deltas = [
            v.wns_delta_ns for v in validated.values() if v.wns_delta_ns is not None
        ]
        real_median = PPADeltaRecord(
            area_ratio=statistics_median(area_ratios) if area_ratios else None,
            power_ratio=statistics_median(power_ratios) if power_ratios else None,
            wns_delta_ns=statistics_median(wns_deltas) if wns_deltas else None,
        )
        claimed_median_raw = raw.get("median_ppa_delta")
        if not isinstance(claimed_median_raw, dict):
            raise TableDataError(f"median_ppa_delta must be an object in {path}")
        for field in ("area_ratio", "power_ratio", "wns_delta_ns"):
            claimed_value = _optional_number(
                claimed_median_raw, field, path, nonnegative=field != "wns_delta_ns"
            )
            real_value = getattr(real_median, field)
            if (claimed_value is None) != (real_value is None):
                raise TableDataError(
                    f"median_ppa_delta.{field} presence does not match recomputed "
                    f"child manifests in {path}"
                )
            if (
                claimed_value is not None
                and real_value is not None
                and not math.isclose(claimed_value, real_value, rel_tol=1e-6, abs_tol=1e-9)
            ):
                raise TableDataError(
                    f"median_ppa_delta.{field} {claimed_value} does not match "
                    f"{real_value} recomputed from child manifests in {path}"
                )

        total_tokens = sum(v.tokens for v in validated.values())
        total_cost = sum(v.cost_usd for v in validated.values())
        claimed_tokens = _integer(raw, "tokens_in", path) + _integer(
            raw, "tokens_out", path
        )
        if claimed_tokens != total_tokens:
            raise TableDataError(
                f"tokens_in+tokens_out ({claimed_tokens}) does not match the sum "
                f"of child manifest tokens ({total_tokens}) in {path}"
            )
        claimed_cost = _number(raw, "cost_usd", path)
        if not math.isclose(claimed_cost, total_cost, abs_tol=1e-6):
            raise TableDataError(
                f"cost_usd {claimed_cost} does not match the sum of child "
                f"manifest costs ({total_cost}) in {path}"
            )

        records.append(
            AgentEvalRecord(
                provider=_text(raw, "provider", path),
                model=_text(raw, "model", path),
                tasks_attempted=attempted,
                tasks_objective_met=objective_met,
                objective_met_rate=real_rate,
                median_ppa_delta=real_median,
                cost_usd=total_cost,
                tokens=total_tokens,
            )
        )
    return sorted(
        records,
        key=lambda row: (-row.objective_met_rate, row.model, row.provider),
    )


@dataclass(frozen=True)
class _TrackBTaskResult:
    objective_pass: bool
    area_ratio: float | None
    power_ratio: float | None
    wns_delta_ns: float | None
    tokens: int
    cost_usd: float


def _track_b_validated_results(
    raw: dict[str, Any],
    summary_path: Path,
    expected: frozenset[str],
) -> dict[str, _TrackBTaskResult]:
    """For every task, load its real child manifest and run
    validate_track_b_semantics() -- which re-derives correctness/objective truth
    from the manifest's own stages exactly as run_track_b() computes it (GTFS-014)
    -- rather than trusting the summary's tasks_objective_met/objective_met_rate/
    median_ppa_delta fields directly.
    """

    result: dict[str, _TrackBTaskResult] = {}
    for task_id in expected:
        manifest_path = _referenced_manifest(
            summary_path, raw["tasks"][task_id].get("manifest")
        )
        if manifest_path is None:
            raise TableDataError(f"{task_id} has an invalid manifest reference")
        manifest = load_agent_manifest_b(manifest_path)
        validate_track_b_semantics(manifest)
        delta = manifest.ppa_delta
        result[task_id] = _TrackBTaskResult(
            objective_pass=manifest.objective_pass,
            area_ratio=delta.area_ratio,
            power_ratio=delta.power_ratio,
            wns_delta_ns=delta.wns_delta_ns,
            tokens=manifest.tokens_in + manifest.tokens_out,
            cost_usd=manifest.cost_usd,
        )
    return result


def _signed_summary_candidates(
    directory: Path,
    label: str,
) -> dict[tuple[str, str], list[tuple[Path, dict[str, Any]]]]:
    candidates: dict[tuple[str, str], list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(directory.glob("**/summary.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TableDataError(f"invalid {label} summary {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise TableDataError(f"{label} summary must be an object: {path}")
        signature = raw.get("signature")
        if not isinstance(signature, str) or signature != compute_manifest_signature(raw):
            raise TableDataError(f"unsigned or tampered {label} summary: {path}")
        key = (_text(raw, "provider", path), _text(raw, "model", path))
        candidates.setdefault(key, []).append((path, raw))
    return candidates


def _track_a_incomplete_reason(
    raw: dict[str, Any],
    summary_path: Path,
    expected: frozenset[str],
) -> str | None:
    reason = _summary_shape_reason(raw, expected)
    if reason is not None:
        return reason
    samples_per_task = raw.get("samples_per_task")
    if (
        isinstance(samples_per_task, bool)
        or not isinstance(samples_per_task, int)
        or samples_per_task < 1
    ):
        return "samples_per_task must be a positive integer"

    tasks = raw["tasks"]
    provider = raw["provider"]
    model = raw["model"]
    for task_id in sorted(expected):
        entry = tasks[task_id]
        if not isinstance(entry, dict) or entry.get("skipped") is not False:
            return f"{task_id} is missing or skipped"
        samples = entry.get("samples")
        if not isinstance(samples, list) or len(samples) != samples_per_task:
            return f"{task_id} does not contain every declared sample"
        for sample in samples:
            if not isinstance(sample, dict):
                return f"{task_id} has a malformed sample record"
            relative = sample.get("manifest")
            recorded_signature = sample.get("manifest_signature")
            manifest_path = _referenced_manifest(summary_path, relative)
            if manifest_path is None or not isinstance(recorded_signature, str):
                return f"{task_id} has an invalid manifest reference"
            try:
                manifest = load_manifest(manifest_path)
            except Exception as exc:
                return f"{task_id} manifest is missing or invalid: {type(exc).__name__}"
            if (
                manifest.task_id != task_id
                or manifest.provider != provider
                or manifest.model != model
                or manifest.signature != recorded_signature
            ):
                return f"{task_id} manifest does not match its signed summary"
    return None


def _track_b_incomplete_reason(
    raw: dict[str, Any],
    summary_path: Path,
    expected: frozenset[str],
) -> str | None:
    if raw.get("track") != "B":
        return "track is not B"
    reason = _summary_shape_reason(raw, expected)
    if reason is not None:
        return reason
    if raw.get("tasks_attempted") != len(expected):
        return "tasks_attempted does not equal the canonical suite size"

    tasks = raw["tasks"]
    provider = raw["provider"]
    model = raw["model"]
    for task_id in sorted(expected):
        entry = tasks[task_id]
        if not isinstance(entry, dict) or entry.get("skipped") is not False:
            return f"{task_id} is missing or skipped"
        manifest_path = _referenced_manifest(summary_path, entry.get("manifest"))
        if manifest_path is None:
            return f"{task_id} has an invalid manifest reference"
        try:
            manifest = load_agent_manifest_b(manifest_path)
        except Exception as exc:
            return f"{task_id} manifest is missing or invalid: {type(exc).__name__}"
        if (
            manifest.task_id != task_id
            or manifest.provider != provider
            or manifest.model != model
        ):
            return f"{task_id} manifest does not match its signed summary"
    return None


def _summary_shape_reason(
    raw: dict[str, Any],
    expected: frozenset[str],
) -> str | None:
    if raw.get("official") is not True:
        return "run is not official"
    task_ids = raw.get("task_ids")
    if (
        not isinstance(task_ids, list)
        or any(not isinstance(task_id, str) for task_id in task_ids)
        or len(task_ids) != len(set(task_ids))
    ):
        return "task_ids must be a unique string list"
    actual = frozenset(task_ids)
    if actual != expected:
        return _task_set_mismatch(expected, actual)
    tasks = raw.get("tasks")
    if not isinstance(tasks, dict) or frozenset(tasks) != expected:
        actual_tasks = frozenset(tasks) if isinstance(tasks, dict) else frozenset()
        return f"tasks {_task_set_mismatch(expected, actual_tasks)}"
    return None


def _task_set_mismatch(expected: frozenset[str], actual: frozenset[str]) -> str:
    return (
        "task-id set mismatch "
        f"(expected={len(expected)}, actual={len(actual)}, "
        f"missing={len(expected - actual)}, extra={len(actual - expected)})"
    )


def _referenced_manifest(summary_path: Path, relative: Any) -> Path | None:
    if not isinstance(relative, str) or not relative:
        return None
    candidate = Path(relative)
    if candidate.is_absolute():
        return None
    root = summary_path.parent.resolve()
    target = (root / candidate).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _warn_omitted_run(
    track: str,
    key: tuple[str, str],
    reasons: list[tuple[Path, str]],
) -> None:
    provider, model = key
    details = "; ".join(f"{path}: {reason}" for path, reason in reasons)
    print(
        f"warning: omitted {track} {provider}/{model}; "
        f"no complete official run ({details})",
        file=sys.stderr,
    )


def _raise_ambiguous_run(
    track: str,
    key: tuple[str, str],
    complete: list[tuple[Path, dict[str, Any]]],
) -> None:
    provider, model = key
    paths = ", ".join(path.as_posix() for path, _raw in sorted(complete))
    raise TableDataError(
        f"ambiguous {track} official run for {provider}/{model}: "
        f"{len(complete)} complete, signed candidates found ({paths}). "
        "A duplicate complete official run is always either an archival copy "
        "or a mistake -- move or delete the stale one rather than let this "
        "generator guess which is authoritative."
    )


def _canonical_task_ids(root: Path, marker: str) -> frozenset[str]:
    task_ids = frozenset(path.parent.name for path in root.glob(f"*/{marker}"))
    if not task_ids:
        raise TableDataError(f"no canonical tasks found under {root}")
    return task_ids


def _require_suite_size(
    track: str,
    task_ids: frozenset[str],
    expected_size: int,
) -> None:
    if len(task_ids) != expected_size:
        raise TableDataError(
            f"{track} canonical suite must contain {expected_size} tasks, "
            f"found {len(task_ids)}"
        )


def _reference_manifest(task_id: str, refs_dir: Path):
    if not refs_dir.is_dir():
        return None
    candidates = sorted(refs_dir.glob(f"**/{task_id}.json"))
    if not candidates:
        return None
    try:
        manifest = load_manifest(candidates[-1])
    except Exception as exc:
        raise TableDataError(f"invalid reference manifest {candidates[-1]}: {exc}") from exc
    if manifest.task_id != task_id:
        raise TableDataError(f"reference manifest task mismatch: {candidates[-1]}")
    return manifest


def _stage_metric(manifest, stage_id: int, field: str) -> float | None:
    for stage in manifest.stages:
        if stage.stage == stage_id and stage.status == "pass":
            value = getattr(stage, field)
            return float(value) if value is not None else None
    return None


def _tasks_markdown(rows: list[TaskRecord], metadata: str) -> str:
    lines = [
        f"<!-- {metadata} -->",
        "| Task | Tier | Formal | Clock (ns) | Ref area (um^2) | Ref WNS (ns) | Ref power (mW) |",
        "|---|---:|:---:|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {_md(row.task_id)} | {row.tier} | {'yes' if row.formal else 'no'} | "
        f"{row.clock_ns:.2f} | {_value(row.area_um2, 2)} | {_value(row.wns_ns, 3)} | "
        f"{_value(row.power_mw, 6)} |"
        for row in rows
    )
    lines.extend(
        f"<!-- Missing ref PPA for {row.task_id}: ./gatetruth run --task {row.task_id} "
        f"--submission tasks/{row.task_id}/ref/ref.sv --out results/refs/{row.task_id}.json -->"
        for row in rows
        if row.area_um2 is None or row.wns_ns is None or row.power_mw is None
    )
    return "\n".join(lines) + "\n"


def _tasks_latex(rows: list[TaskRecord], metadata: str) -> str:
    lines = [
        f"% {metadata}",
        r"\begin{tabular}{llcrrrr}",
        r"\toprule",
        r"Task & Tier & Formal & Clock (ns) & Area ($\mu$m$^2$) & WNS (ns) & Power (mW) \\",
        r"\midrule",
    ]
    lines.extend(
        f"{_tex(row.task_id)} & {row.tier} & {'yes' if row.formal else 'no'} & "
        f"{row.clock_ns:.2f} & {_value(row.area_um2, 2)} & {_value(row.wns_ns, 3)} & "
        f"{_value(row.power_mw, 6)} \\\\"
        for row in rows
    )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    lines.extend(
        f"% Missing ref PPA for {row.task_id}: ./gatetruth run --task {row.task_id} "
        f"--submission tasks/{row.task_id}/ref/ref.sv --out results/refs/{row.task_id}.json"
        for row in rows
        if row.area_um2 is None or row.wns_ns is None or row.power_mw is None
    )
    return "\n".join(lines) + "\n"


def _mutation_markdown(rows: list[MutationRecord], metadata: str) -> str:
    lines = [
        f"<!-- {metadata} -->",
        "| Task | Mutants | Killed | Kill rate (%) |",
        "|---|---:|---:|---:|",
    ]
    lines.extend(
        f"| {_md(row.task_id)} | {row.mutants} | {row.killed} | {row.kill_rate:.2f} |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _mutation_latex(rows: list[MutationRecord], metadata: str) -> str:
    lines = [
        f"% {metadata}",
        r"\begin{tabular}{lrrr}",
        r"\toprule",
        r"Task & Mutants & Killed & Kill rate (\%) \\",
        r"\midrule",
    ]
    lines.extend(
        f"{_tex(row.task_id)} & {row.mutants} & {row.killed} & {row.kill_rate:.2f} \\\\"
        for row in rows
    )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _eval_markdown(rows: list[EvalRecord], metadata: str) -> str:
    lines = [
        f"<!-- {metadata} -->",
        "| Provider | Model | Tasks | Aggregate score | Tokens | Cost (USD) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    lines.extend(
        f"| {_md(row.provider)} | {_md(row.model)} | {row.tasks} | "
        f"{row.aggregate_score:.2f} | {row.tokens} | {row.cost_usd:.6f} |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _eval_latex(rows: list[EvalRecord], metadata: str) -> str:
    lines = [
        f"% {metadata}",
        r"\begin{tabular}{llrrrr}",
        r"\toprule",
        r"Provider & Model & Tasks & Score & Tokens & Cost (USD) \\",
        r"\midrule",
    ]
    lines.extend(
        f"{_tex(row.provider)} & {_tex(row.model)} & {row.tasks} & "
        f"{row.aggregate_score:.2f} & {row.tokens} & {row.cost_usd:.6f} \\\\"
        for row in rows
    )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _trackb_markdown(rows: list[AgentEvalRecord], metadata: str) -> str:
    lines = [
        f"<!-- {metadata} -->",
        "| Provider | Model | Objectives met (n/N) | Objective-met rate | "
        "Median PPA delta | Cost (USD) |",
        "|---|---|---:|---:|---|---:|",
    ]
    lines.extend(
        f"| {_md(row.provider)} | {_md(row.model)} | "
        f"{row.tasks_objective_met}/{row.tasks_attempted} | "
        f"{100.0 * row.objective_met_rate:.2f}% | "
        f"{_md(_ppa_delta(row.median_ppa_delta))} | {row.cost_usd:.6f} |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def _trackb_latex(rows: list[AgentEvalRecord], metadata: str) -> str:
    lines = [
        f"% {metadata}",
        r"\begin{tabular}{llrrlr}",
        r"\toprule",
        r"Provider & Model & Objectives met & Objective-met rate & "
        r"Median PPA delta & Cost (USD) \\",
        r"\midrule",
    ]
    lines.extend(
        f"{_tex(row.provider)} & {_tex(row.model)} & "
        f"{row.tasks_objective_met}/{row.tasks_attempted} & "
        f"{100.0 * row.objective_met_rate:.2f}\\% & "
        f"{_tex(_ppa_delta(row.median_ppa_delta))} & {row.cost_usd:.6f} \\\\"
        for row in rows
    )
    lines.extend([r"\bottomrule", r"\end{tabular}"])
    return "\n".join(lines) + "\n"


def _ppa_delta(delta: PPADeltaRecord) -> str:
    area = "N/A" if delta.area_ratio is None else f"{delta.area_ratio:.4f}x"
    power = "N/A" if delta.power_ratio is None else f"{delta.power_ratio:.4f}x"
    wns = "N/A" if delta.wns_delta_ns is None else f"{delta.wns_delta_ns:+.3f} ns"
    return f"area={area}; power={power}; WNS={wns}"


def _value(value: float | None, digits: int) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def _md(value: str) -> str:
    return value.replace("|", "\\|")


def _tex(value: str) -> str:
    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "_": r"\_"}
    return "".join(replacements.get(character, character) for character in value)


def _text(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise TableDataError(f"{key} must be nonempty text in {path}")
    return value


def _integer(raw: dict[str, Any], key: str, path: Path) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TableDataError(f"{key} must be a nonnegative integer in {path}")
    return value


def _number(raw: dict[str, Any], key: str, path: Path) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TableDataError(f"{key} must be numeric in {path}")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise TableDataError(f"{key} must be finite and nonnegative in {path}")
    return result


def _optional_number(
    raw: dict[str, Any],
    key: str,
    path: Path,
    *,
    nonnegative: bool = False,
) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TableDataError(f"{key} must be numeric or null in {path}")
    result = float(value)
    if not math.isfinite(result) or (nonnegative and result < 0):
        qualifier = "nonnegative " if nonnegative else ""
        raise TableDataError(f"{key} must be finite {qualifier}numeric or null in {path}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="paper/data/build")
    parser.add_argument(
        "--from-dir", default="results/mutation/certification", dest="mutation_dir"
    )
    parser.add_argument("--tasks-root", default="tasks")
    parser.add_argument("--refs-dir", default="results/refs")
    parser.add_argument("--eval-dir", default="results/eval")
    parser.add_argument("--agent-eval-dir", default="results/evalB")
    parser.add_argument("--agent-tasks-root", default="tasksB")
    parser.add_argument("--date", help="generated-on date override (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    try:
        run_date = date.fromisoformat(args.date) if args.date else None
        paths = generate_tables(
            out_dir=args.out,
            tasks_root=args.tasks_root,
            refs_dir=args.refs_dir,
            mutation_dir=args.mutation_dir,
            eval_dir=args.eval_dir,
            agent_eval_dir=args.agent_eval_dir,
            agent_tasks_root=args.agent_tasks_root,
            generated_date=run_date,
        )
    except (OSError, TableDataError, ValueError) as exc:
        parser.exit(2, f"table generation refused: {exc}\n")
    for path in paths.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
