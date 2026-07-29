"""Generate the fully static GateTruth leaderboard site."""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import fmean
from typing import Any

from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import ResultManifest, load_manifest
from harness.schemas.manifest_b import load_agent_manifest_b

CANARY_RE = re.compile(
    r"SILICONBENCH-CANARY-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-"
    r"[0-9A-F]{4}-[0-9A-F]{12}",
    re.IGNORECASE,
)
SIGNED_REVIEW_RE = re.compile(r"SIGNED-OFF-BY-MEET-\d{4}-\d{2}-\d{2}")


class SiteGenerationError(ValueError):
    """Raised when signed evaluation input is invalid or unsafe to publish."""


@dataclass(frozen=True)
class TaskRow:
    task_id: str
    score: float
    skipped: bool
    skip_reason: str | None
    stages: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class LeaderboardRow:
    run_id: str
    provider: str
    model: str
    prompt_version: str
    aggregate_score: float
    pass_at_1: float
    mean_ppa: float | None
    tasks_attempted: int
    tasks_passed: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    run_date: str
    official: bool
    signature: str
    detail_page: str
    tasks: tuple[TaskRow, ...]


@dataclass(frozen=True)
class AgentRow:
    run_id: str
    provider: str
    model: str
    task_id: str
    objective_type: str
    objective_pass: bool
    disqualified: bool
    budget_exceeded: str | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    run_date: str
    official: bool
    signature: str
    detail_page: str
    sec_status: str
    area_ratio: float | None
    power_ratio: float | None
    wns_delta_ns: float | None
    stages: tuple[tuple[str, str], ...]


def generate_site(
    results_root: str | Path = "results/eval",
    build_root: str | Path = "site/build",
    *,
    agent_results_root: str | Path | None = None,
    tasks_b_root: str | Path | None = None,
) -> dict[str, Path]:
    """Validate signed Track A/B results and atomically render static files."""

    results_path = Path(results_root).resolve()
    output_path = Path(build_root).resolve()
    agent_path = (
        Path(agent_results_root).resolve()
        if agent_results_root is not None
        else results_path.parent / "agent"
    )
    task_path = (
        Path(tasks_b_root).resolve()
        if tasks_b_root is not None
        else Path(__file__).resolve().parents[1] / "tasksB"
    )

    summaries = sorted(results_path.glob("**/summary.json")) if results_path.is_dir() else []
    agent_json = sorted(agent_path.glob("**/*.json")) if agent_path.is_dir() else []
    agent_summaries = [path for path in agent_json if path.name == "summary.json"]
    agent_files = [
        path
        for path in agent_json
        if path.name != "summary.json" and not path.name.endswith(".transcript.json")
    ]
    if not summaries and not agent_files and not agent_summaries:
        raise SiteGenerationError(
            f"no signed Track A or Track B results found under {results_path} and {agent_path}"
        )

    rows = [_load_summary(path, results_path) for path in summaries]
    rows.sort(key=lambda row: (-row.aggregate_score, row.model.lower(), row.run_id))
    for path in agent_summaries:
        _validate_agent_summary(path, agent_path)
    agent_rows = [_load_agent(path, agent_path, task_path) for path in agent_files]
    agent_rows.sort(
        key=lambda row: (
            not row.objective_pass,
            row.model.lower(),
            row.task_id,
            row.run_id,
        )
    )

    artifacts: dict[str, str] = {
        "index.html": _render_index(rows, agent_rows),
        "leaderboard.json": json.dumps(
            {
                "runs": [_public_row(row) for row in rows],
                "schema_version": 2,
                "track_b_runs": [_public_agent_row(row) for row in agent_rows],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    for row in rows:
        artifacts[row.detail_page] = _render_detail(row)
    agent_groups: dict[str, list[AgentRow]] = {}
    for row in agent_rows:
        agent_groups.setdefault(row.detail_page, []).append(row)
    for detail_page, group in sorted(agent_groups.items()):
        artifacts[detail_page] = _render_agent_detail(group)

    for name, content in artifacts.items():
        if CANARY_RE.search(content):
            raise SiteGenerationError(f"canary leak detected in generated {name}")

    staging = output_path.with_name(f".{output_path.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for relative, content in artifacts.items():
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")
    if output_path.exists():
        shutil.rmtree(output_path)
    staging.replace(output_path)
    return {name: output_path / name for name in sorted(artifacts)}


def _load_summary(path: Path, results_root: Path) -> LeaderboardRow:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteGenerationError(f"invalid summary {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SiteGenerationError(f"summary must be a JSON object: {path}")
    signature = raw.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise SiteGenerationError(f"unsigned summary refused: {path}")
    if signature != compute_manifest_signature(raw):
        raise SiteGenerationError(f"tampered summary refused: {path}")

    provider = _text(raw, "provider", path)
    model = _text(raw, "model", path)
    prompt_version = _text(raw, "prompt_version", path)
    aggregate = _number(raw, "aggregate_mean", path)
    tokens_in = _integer(raw, "tokens_in", path)
    tokens_out = _integer(raw, "tokens_out", path)
    cost = _number(raw, "cost_usd", path)
    timestamp = _text(raw, "timestamp", path)
    _validate_timestamp(timestamp, path)
    official_requested = raw.get("official", False)
    if not isinstance(official_requested, bool):
        raise SiteGenerationError(f"official must be boolean: {path}")

    task_ids = raw.get("task_ids")
    tasks = raw.get("tasks")
    if (
        not isinstance(task_ids, list)
        or not task_ids
        or any(not isinstance(item, str) or not item for item in task_ids)
        or len(task_ids) != len(set(task_ids))
    ):
        raise SiteGenerationError(f"task_ids must be a nonempty unique string list: {path}")
    if not isinstance(tasks, dict) or set(tasks) != set(task_ids):
        raise SiteGenerationError(f"tasks must match task_ids exactly: {path}")

    sample_count = _integer(raw, "samples_per_task", path)
    if sample_count < 1:
        raise SiteGenerationError(f"samples_per_task must be positive: {path}")

    model_root = path.parent.resolve()
    task_rows: list[TaskRow] = []
    included_scores: list[float] = []
    passed_ppa: list[float] = []
    attempted_samples = 0
    passed_samples = 0
    total_tokens_in = 0
    total_tokens_out = 0
    total_cost = 0.0
    all_official = official_requested

    for task_id in task_ids:
        entry = tasks[task_id]
        if not isinstance(entry, dict):
            raise SiteGenerationError(f"task entry must be an object: {task_id}")
        skipped = entry.get("skipped")
        if not isinstance(skipped, bool):
            raise SiteGenerationError(f"task skipped must be boolean: {task_id}")
        skip_reason = entry.get("skip_reason")
        if skipped and (not isinstance(skip_reason, str) or not skip_reason):
            raise SiteGenerationError(f"skipped task needs skip_reason: {task_id}")
        if not skipped and skip_reason is not None:
            raise SiteGenerationError(f"non-skipped task has skip_reason: {task_id}")
        samples = entry.get("samples")
        scores = entry.get("scores")
        if not isinstance(samples, list) or len(samples) != sample_count:
            raise SiteGenerationError(f"wrong sample count for {task_id}")
        if not isinstance(scores, list) or len(scores) != sample_count:
            raise SiteGenerationError(f"wrong score count for {task_id}")

        manifests: list[ResultManifest] = []
        validated_scores: list[float] = []
        for index, (sample, raw_score) in enumerate(zip(samples, scores, strict=True), 1):
            if not isinstance(sample, dict) or sample.get("sample") != index:
                raise SiteGenerationError(f"invalid sample record for {task_id} sample {index}")
            score = _finite_number(raw_score, f"score for {task_id}")
            if score < 0:
                raise SiteGenerationError(f"negative score for {task_id}")
            if not math.isclose(score, _finite_number(sample.get("score"), "sample score")):
                raise SiteGenerationError(f"sample score mismatch for {task_id}")
            relative = sample.get("manifest")
            if not isinstance(relative, str) or not relative:
                raise SiteGenerationError(f"missing manifest path for {task_id}")
            manifest_path = (model_root / relative).resolve()
            if not manifest_path.is_relative_to(model_root):
                raise SiteGenerationError(f"manifest escapes its result directory: {relative}")
            try:
                manifest = load_manifest(manifest_path)
            except Exception as exc:
                raise SiteGenerationError(f"invalid manifest {manifest_path}: {exc}") from exc
            if manifest.task_id != task_id:
                raise SiteGenerationError(f"manifest task mismatch for {task_id}")
            if manifest.provider != provider or manifest.model != model:
                raise SiteGenerationError(f"manifest model metadata mismatch for {task_id}")
            if manifest.signature != sample.get("manifest_signature"):
                raise SiteGenerationError(f"manifest signature mismatch for {task_id}")
            if not math.isclose(manifest.task_score, score, abs_tol=1e-9):
                raise SiteGenerationError(f"manifest score mismatch for {task_id}")
            if manifest.official_skip_reason is not None:
                all_official = False
            manifests.append(manifest)
            validated_scores.append(score)
            total_tokens_in += manifest.tokens_in
            total_tokens_out += manifest.tokens_out
            total_cost += manifest.cost_usd

        mean_score = _finite_number(entry.get("mean_score"), "mean_score")
        if not math.isclose(mean_score, fmean(validated_scores), abs_tol=1e-9):
            raise SiteGenerationError(f"mean score mismatch for {task_id}")
        if skipped:
            all_official = False
        else:
            included_scores.extend(validated_scores)
            attempted_samples += len(manifests)
            for manifest in manifests:
                if manifest.task_score > 0:
                    passed_samples += 1
                    passed_ppa.append(manifest.ppa)
        representative = manifests[0]
        task_rows.append(
            TaskRow(
                task_id=task_id,
                score=mean_score,
                skipped=skipped,
                skip_reason=skip_reason if isinstance(skip_reason, str) else None,
                stages=tuple((stage.name, stage.status) for stage in representative.stages),
            )
        )

    recomputed = fmean(included_scores) if included_scores else 0.0
    if not math.isclose(aggregate, recomputed, abs_tol=1e-9):
        raise SiteGenerationError(f"aggregate score mismatch: {path}")
    if tokens_in != total_tokens_in or tokens_out != total_tokens_out:
        raise SiteGenerationError(f"token totals mismatch: {path}")
    if not math.isclose(cost, total_cost, abs_tol=1e-9):
        raise SiteGenerationError(f"cost total mismatch: {path}")

    attempted = sum(not task.skipped for task in task_rows)
    passed = sum(not task.skipped and task.score > 0 for task in task_rows)
    run_parts = path.parent.relative_to(results_root).parts
    run_id = "/".join(run_parts[:-1]) or "default"
    detail_page = f"models/{_slug(model)}--{_slug(run_id)}.html"
    return LeaderboardRow(
        run_id=run_id,
        provider=provider,
        model=model,
        prompt_version=prompt_version,
        aggregate_score=aggregate,
        pass_at_1=(100.0 * passed_samples / attempted_samples) if attempted_samples else 0.0,
        mean_ppa=fmean(passed_ppa) if passed_ppa else None,
        tasks_attempted=attempted,
        tasks_passed=passed,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        run_date=timestamp,
        official=all_official,
        signature=signature,
        detail_page=detail_page,
        tasks=tuple(task_rows),
    )


def _load_agent(path: Path, agent_root: Path, tasks_root: Path) -> AgentRow:
    relative = path.resolve().relative_to(agent_root)
    if len(relative.parts) != 3:
        raise SiteGenerationError(
            f"agent manifest must use <run>/<model>/<task>.json layout: {path}"
        )
    run_id, model_component, filename = relative.parts
    if _safe_component(run_id) != run_id:
        raise SiteGenerationError(f"unsafe Track B run name: {run_id}")
    try:
        manifest = load_agent_manifest_b(path)
    except Exception as exc:
        raise SiteGenerationError(f"invalid agent manifest {path}: {exc}") from exc
    if filename != f"{_safe_component(manifest.task_id)}.json":
        raise SiteGenerationError(f"agent manifest filename does not match task_id: {path}")
    if model_component != _safe_component(manifest.model):
        raise SiteGenerationError(f"agent manifest directory does not match model: {path}")
    _validate_timestamp(manifest.timestamp, path)
    official = _track_b_official(manifest.task_id, tasks_root)
    detail_page = f"agents/{_slug(manifest.model)}--{_slug(run_id)}.html"
    return AgentRow(
        run_id=run_id,
        provider=manifest.provider,
        model=manifest.model,
        task_id=manifest.task_id,
        objective_type=manifest.objective_type,
        objective_pass=manifest.objective_pass,
        disqualified=manifest.disqualified,
        budget_exceeded=manifest.budget_exceeded,
        tokens_in=manifest.tokens_in,
        tokens_out=manifest.tokens_out,
        cost_usd=manifest.cost_usd,
        run_date=manifest.timestamp,
        official=official,
        signature=manifest.signature,
        detail_page=detail_page,
        sec_status=manifest.sec.status,
        area_ratio=manifest.ppa_delta.area_ratio,
        power_ratio=manifest.ppa_delta.power_ratio,
        wns_delta_ns=manifest.ppa_delta.wns_delta_ns,
        stages=tuple((stage.name, stage.status) for stage in manifest.stages),
    )


def _validate_agent_summary(path: Path, agent_root: Path) -> None:
    relative = path.resolve().relative_to(agent_root)
    if len(relative.parts) != 3 or relative.name != "summary.json":
        raise SiteGenerationError(
            f"agent summary must use <run>/<model>/summary.json layout: {path}"
        )
    run_id, model_component, _ = relative.parts
    if _safe_component(run_id) != run_id:
        raise SiteGenerationError(f"unsafe Track B run name: {run_id}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SiteGenerationError(f"invalid agent summary {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SiteGenerationError(f"agent summary must be a JSON object: {path}")
    signature = raw.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        raise SiteGenerationError(f"unsigned agent summary refused: {path}")
    if signature != compute_manifest_signature(raw):
        raise SiteGenerationError(f"tampered agent summary refused: {path}")
    if raw.get("track") != "B":
        raise SiteGenerationError(f"agent summary track must be B: {path}")
    model = _text(raw, "model", path)
    if model_component != _safe_component(model):
        raise SiteGenerationError(f"agent summary directory does not match model: {path}")
    task_ids = raw.get("task_ids")
    tasks = raw.get("tasks")
    if (
        not isinstance(task_ids, list)
        or not task_ids
        or any(not isinstance(task_id, str) or not task_id for task_id in task_ids)
        or len(task_ids) != len(set(task_ids))
    ):
        raise SiteGenerationError(f"agent summary task_ids must be unique strings: {path}")
    if not isinstance(tasks, dict) or set(tasks) != set(task_ids):
        raise SiteGenerationError(f"agent summary tasks must match task_ids: {path}")
    for task_id in task_ids:
        entry = tasks[task_id]
        if not isinstance(entry, dict) or not isinstance(entry.get("skipped"), bool):
            raise SiteGenerationError(f"invalid agent summary task entry: {task_id}")
        if entry["skipped"]:
            if not isinstance(entry.get("skip_reason"), str) or not entry["skip_reason"]:
                raise SiteGenerationError(f"skipped agent task needs a reason: {task_id}")
            continue
        expected = f"{_safe_component(task_id)}.json"
        if entry.get("manifest") != expected or not (path.parent / expected).is_file():
            raise SiteGenerationError(f"agent summary manifest missing for {task_id}: {path}")


def _track_b_official(task_id: str, tasks_root: Path) -> bool:
    task_yaml = tasks_root / task_id / "task.yaml"
    if not task_yaml.is_file() and task_id == "toy_taskB":
        task_yaml = (
            Path(__file__).resolve().parents[1]
            / "harness"
            / "tests"
            / "fixtures"
            / "toy_taskB"
            / "task.yaml"
        )
    if not task_yaml.is_file():
        raise SiteGenerationError(f"missing Track B task metadata: {task_yaml}")
    values: dict[str, str] = {}
    for raw_line in task_yaml.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = (part.strip().strip('"\'') for part in line.split(":", 1))
        if key in {"baseline_review", "tb_review"}:
            if key in values:
                raise SiteGenerationError(f"duplicate {key} in {task_yaml}")
            values[key] = value
    if set(values) != {"baseline_review", "tb_review"}:
        raise SiteGenerationError(f"missing Track B review fields in {task_yaml}")
    return all(SIGNED_REVIEW_RE.fullmatch(value) is not None for value in values.values())


def _safe_component(value: str) -> str:
    component = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return component or "run"


def _public_row(row: LeaderboardRow) -> dict[str, Any]:
    return {
        "aggregate_score": row.aggregate_score,
        "badge": "OFFICIAL" if row.official else "DEV",
        "cost_usd": row.cost_usd,
        "detail_page": row.detail_page,
        "model": row.model,
        "mean_ppa": row.mean_ppa,
        "official": row.official,
        "pass_at_1": row.pass_at_1,
        "prompt_version": row.prompt_version,
        "provider": row.provider,
        "run_date": row.run_date,
        "run_id": row.run_id,
        "signature": row.signature,
        "tasks_attempted": row.tasks_attempted,
        "tasks_passed": row.tasks_passed,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
    }


def _public_agent_row(row: AgentRow) -> dict[str, Any]:
    return {
        "badge": "OFFICIAL" if row.official else "DEV",
        "budget_exceeded": row.budget_exceeded,
        "cost_usd": row.cost_usd,
        "detail_page": row.detail_page,
        "disqualified": row.disqualified,
        "model": row.model,
        "objective_pass": row.objective_pass,
        "official": row.official,
        "provider": row.provider,
        "run_date": row.run_date,
        "run_id": row.run_id,
        "signature": row.signature,
        "task_id": row.task_id,
        "tokens_in": row.tokens_in,
        "tokens_out": row.tokens_out,
    }


def _render_index(rows: list[LeaderboardRow], agent_rows: list[AgentRow]) -> str:
    body = []
    for rank, row in enumerate(rows, 1):
        badge = "official" if row.official else "dev"
        body.append(
            "<tr>"
            f"<td>{rank}</td>"
            f'<td><a href="{html.escape(row.detail_page)}">{html.escape(row.model)}</a>'
            f'<span class="sub">{html.escape(row.provider)} / {html.escape(row.run_id)}</span></td>'
            f'<td class="score">{row.aggregate_score:.2f}</td>'
            f"<td>{row.pass_at_1:.1f}%</td>"
            f"<td>{'--' if row.mean_ppa is None else f'{row.mean_ppa:.4f}x'}</td>"
            f"<td>{row.tasks_passed}/{row.tasks_attempted}</td>"
            f"<td>${row.cost_usd:.6f}</td>"
            f"<td>{row.tokens_in + row.tokens_out:,}</td>"
            f"<td>{html.escape(_date(row.run_date))}</td>"
            f'<td><span class="badge {badge}">{"OFFICIAL" if row.official else "DEV"}</span></td>'
            "</tr>"
        )
    track_a_table = "".join(body) or '<tr><td colspan="10">No Track A results.</td></tr>'
    agent_body = []
    for row in agent_rows:
        badge = "official" if row.official else "dev"
        result = "PASS" if row.objective_pass else "FAIL"
        result_class = "pass" if row.objective_pass else "fail"
        budget = row.budget_exceeded or "none"
        agent_body.append(
            "<tr>"
            f'<td><a href="{html.escape(row.detail_page)}">{html.escape(row.model)}</a>'
            f'<span class="sub">{html.escape(row.provider)} / {html.escape(row.run_id)}</span></td>'
            f"<td>{html.escape(row.task_id)}</td>"
            f'<td><span class="chip {result_class}">{result}</span></td>'
            f"<td>{'yes' if row.disqualified else 'no'}</td>"
            f"<td>{html.escape(budget)}</td>"
            f"<td>${row.cost_usd:.6f}</td>"
            f"<td>{row.tokens_in + row.tokens_out:,}</td>"
            f'<td><span class="badge {badge}">{"OFFICIAL" if row.official else "DEV"}</span></td>'
            "</tr>"
        )
    track_b_table = "".join(agent_body) or '<tr><td colspan="8">No Track B results.</td></tr>'
    content = (
        '<header><p class="kicker">GateTruth</p><h1>RTL model leaderboard</h1>'
        '<p class="lede">Signed PPA-aware evaluation results.</p>'
        '<nav class="resource-nav" aria-label="Leaderboard resources">'
        '<a data-tour="submit-model" href="https://github.com/meetbhadra701-cloud/GateTruth/compare">'
        'Submit your model</a>'
        '<a data-tour="methodology" href="https://github.com/meetbhadra701-cloud/GateTruth/blob/main/paper/main.tex">'
        'Methodology</a></nav></header>'
        '<main><aside class="score-guide" aria-label="Score guide">'
        '<div data-tour="silicon-score"><strong>SiliconScore</strong>'
        '<span>Pass@1 multiplied by normalized mean PPA.</span></div>'
        '<div data-tour="score-columns"><strong>Pass@1 vs Mean PPA</strong>'
        '<span>Correctness rate and physical quality over passing designs.</span></div>'
        '<button class="tier-toggle" data-tour="tier-toggle" type="button" '
        'aria-expanded="false" aria-controls="tier-breakdown">Tier breakdown</button>'
        '<div id="tier-breakdown" class="tier-breakdown" hidden>'
        '<span><strong>T1</strong> primitives</span><span><strong>T2</strong> IP blocks</span>'
        '<span><strong>T3</strong> systems and datapaths</span></div></aside>'
        '<div class="track-tabs" data-tour="track-tabs" role="tablist" '
        'aria-label="Leaderboard tracks">'
        '<button type="button" role="tab" aria-selected="true" aria-controls="track-a">Track A</button>'
        '<button type="button" role="tab" aria-selected="false" aria-controls="track-b">Track B</button>'
        '</div><section id="track-a" role="tabpanel"><h2>Track A (generation)</h2>'
        '<div class="table-wrap"><table>'
        '<thead><tr><th>#</th><th>Model</th>'
        '<th>SiliconScore</th><th>Pass@1</th><th>Mean PPA</th><th>Passed</th>'
        '<th>Cost</th><th>Tokens</th><th>Date</th>'
        f"<th>Run</th></tr></thead><tbody>{track_a_table}</tbody></table></div></section>"
        '<section id="track-b" role="tabpanel" hidden><h2>Track B (agentic)</h2>'
        '<div class="table-wrap"><table><thead><tr>'
        '<th>Model</th><th>Task</th><th>Objective</th><th>Disqualified</th>'
        '<th>Budget limit</th><th>Cost</th><th>Tokens</th><th>Run</th></tr></thead>'
        f"<tbody>{track_b_table}</tbody></table></div></section></main>"
    )
    return _page("GateTruth leaderboard", content)


def _render_detail(row: LeaderboardRow) -> str:
    task_rows = []
    for task in row.tasks:
        chips = "".join(
            f'<span class="chip {html.escape(status)}">{html.escape(name)}: {html.escape(status)}</span>'
            for name, status in task.stages
        )
        note = f'<span class="sub">{html.escape(task.skip_reason)}</span>' if task.skip_reason else ""
        task_rows.append(
            "<tr>"
            f"<td>{html.escape(task.task_id)}{note}</td>"
            f'<td class="score">{task.score:.2f}</td><td class="chips">{chips}</td>'
            "</tr>"
        )
    badge = "official" if row.official else "dev"
    content = (
        '<nav><a href="../../index.html">&larr; Leaderboard</a></nav>'
        f'<header><span class="badge {badge}">{"OFFICIAL" if row.official else "DEV"}</span>'
        f"<h1>{html.escape(row.model)}</h1>"
        f'<p class="lede">{html.escape(row.provider)} / {html.escape(row.run_id)}</p></header>'
        '<main><section class="metrics">'
        f'<div><span>Aggregate</span><strong>{row.aggregate_score:.2f}</strong></div>'
        f'<div><span>Passed</span><strong>{row.tasks_passed}/{row.tasks_attempted}</strong></div>'
        f'<div><span>Cost</span><strong>${row.cost_usd:.6f}</strong></div>'
        f'<div><span>Tokens</span><strong>{row.tokens_in + row.tokens_out:,}</strong></div>'
        '</section><div class="table-wrap"><table><thead><tr><th>Task</th><th>Score</th>'
        f"<th>Stages</th></tr></thead><tbody>{''.join(task_rows)}</tbody></table></div></main>"
    )
    return _page(f"{row.model} - GateTruth", content)


def _render_agent_detail(rows: list[AgentRow]) -> str:
    first = rows[0]
    task_rows = []
    for row in rows:
        chips = "".join(
            f'<span class="chip {html.escape(status)}">{html.escape(name)}: {html.escape(status)}</span>'
            for name, status in row.stages
        )
        task_rows.append(
            "<tr>"
            f"<td>{html.escape(row.task_id)}</td>"
            f"<td>{html.escape(row.objective_type)}</td>"
            f'<td><span class="chip {html.escape(row.sec_status)}">{html.escape(row.sec_status)}</span></td>'
            f"<td>{_ratio(row.area_ratio)}</td>"
            f"<td>{_ratio(row.power_ratio)}</td>"
            f"<td>{_delta(row.wns_delta_ns)}</td>"
            f'<td class="chips">{chips}</td>'
            "</tr>"
        )
    badge = "official" if all(row.official for row in rows) else "dev"
    badge_text = "OFFICIAL" if badge == "official" else "DEV"
    content = (
        '<nav><a href="../../index.html">&larr; Leaderboard</a></nav>'
        f'<header><span class="badge {badge}">{badge_text}</span>'
        f"<h1>{html.escape(first.model)}</h1>"
        f'<p class="lede">Track B / {html.escape(first.provider)} / {html.escape(first.run_id)}</p>'
        '</header><main><div class="table-wrap"><table><thead><tr><th>Task</th>'
        '<th>Objective type</th><th>SEC</th><th>Area ratio</th><th>Power ratio</th>'
        f"<th>WNS delta</th><th>Stages</th></tr></thead><tbody>{''.join(task_rows)}"
        "</tbody></table></div></main>"
    )
    return _page(f"{first.model} Track B - GateTruth", content)


def _ratio(value: float | None) -> str:
    return "--" if value is None else f"{value:.4f}x"


def _delta(value: float | None) -> str:
    return "--" if value is None else f"{value:+.4f} ns"


def _page(title: str, content: str) -> str:
    css = """
:root{color-scheme:light dark;--bg:#f6f7f9;--panel:#fff;--text:#17202a;--muted:#66717e;--line:#d9dee5;--link:#185abd;--good:#08783e;--warn:#9a5b00;--bad:#b42318}
@media(prefers-color-scheme:dark){:root{--bg:#111419;--panel:#191e25;--text:#edf1f5;--muted:#a4afbb;--line:#343c47;--link:#7eb4ff;--good:#5fd492;--warn:#f2bd68;--bad:#ff8a82}}
*{box-sizing:border-box}[hidden]{display:none!important}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}header,main,nav{width:min(1180px,calc(100% - 32px));margin:0 auto}header{padding:36px 0 22px}nav{padding-top:24px}section+section{margin-top:30px}h1{font-size:30px;letter-spacing:0;margin:4px 0}h2{font-size:18px;letter-spacing:0;margin:0 0 10px}.kicker{color:var(--link);font-weight:700;margin:0}.lede,.sub{color:var(--muted)}.sub{display:block;font-size:12px;margin-top:2px}a{color:var(--link);font-weight:600;text-decoration:none}a:hover{text-decoration:underline}.resource-nav{display:flex;gap:18px;margin:14px 0 0;padding:0;width:auto}.score-guide{display:grid;grid-template-columns:1fr 1fr auto;gap:10px;margin-bottom:18px}.score-guide>div,.tier-toggle{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:12px;text-align:left}.score-guide strong,.score-guide span{display:block}.score-guide span{color:var(--muted);font-size:12px;margin-top:2px}.tier-toggle{color:var(--link);cursor:pointer;font:inherit;font-weight:700}.tier-breakdown{grid-column:1/-1;display:flex!important;gap:18px}.tier-breakdown[hidden]{display:none!important}.tier-breakdown span{margin:0}.track-tabs{display:flex;gap:4px;margin-bottom:12px}.track-tabs button{background:transparent;border:1px solid var(--line);border-radius:4px;color:var(--muted);cursor:pointer;font:inherit;font-weight:700;padding:7px 12px}.track-tabs button[aria-selected=true]{background:var(--panel);border-color:var(--link);color:var(--link)}.table-wrap{background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:auto}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:12px 14px;text-align:left;vertical-align:top;white-space:nowrap}th{color:var(--muted);font-size:12px;text-transform:uppercase}tbody tr:last-child td{border-bottom:0}.score{font-variant-numeric:tabular-nums;font-weight:700}.badge,.chip{border:1px solid var(--line);border-radius:4px;display:inline-block;font-size:11px;font-weight:700;padding:2px 6px}.official,.pass{border-color:var(--good);color:var(--good)}.dev,.skip{border-color:var(--warn);color:var(--warn)}.fail{border-color:var(--bad);color:var(--bad)}.chips{white-space:normal}.chip{margin:0 4px 4px 0}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}.metrics div{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px}.metrics span{color:var(--muted);display:block;font-size:12px}.metrics strong{font-size:20px}.sb-tour-shade{background:rgba(5,10,18,.72);position:fixed;z-index:9990}.sb-tour-highlight{border:2px solid #61d095;box-shadow:0 0 0 2px rgba(5,10,18,.45);pointer-events:none;position:fixed;z-index:9991}.sb-tour-tooltip{background:var(--panel);border:1px solid var(--line);border-radius:6px;box-shadow:0 12px 36px rgba(0,0,0,.35);color:var(--text);max-height:calc(100vh - 24px);overflow:auto;padding:16px;position:fixed;width:min(320px,calc(100vw - 24px));z-index:9992}.sb-tour-close{background:transparent;border:0;color:var(--muted);cursor:pointer;font-size:22px;height:30px;line-height:1;padding:0;position:absolute;right:8px;top:8px;width:30px}.sb-tour-step{color:var(--muted);font-size:12px;margin:0 34px 4px 0}.sb-tour-title{font-size:17px;margin:0 34px 6px 0}.sb-tour-copy{color:var(--muted);margin:0 0 14px}.sb-tour-footer{align-items:center;display:flex;gap:8px;justify-content:space-between}.sb-tour-actions{display:flex;gap:6px}.sb-tour-actions button{background:var(--panel);border:1px solid var(--line);border-radius:4px;color:var(--text);cursor:pointer;font:inherit;padding:6px 10px}.sb-tour-actions .sb-tour-next{background:var(--link);border-color:var(--link);color:#fff}.sb-tour-actions button:disabled{cursor:default;opacity:.45}.sb-tour-dots{display:flex;gap:5px}.sb-tour-dot{background:var(--line);border-radius:50%;height:6px;width:6px}.sb-tour-dot.active{background:var(--link)}@media(max-width:700px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.score-guide{grid-template-columns:1fr}.tier-breakdown{grid-column:1;flex-direction:column;gap:4px}h1{font-size:24px}.sb-tour-tooltip{padding:14px}.sb-tour-footer{align-items:flex-start;flex-direction:column}.sb-tour-actions{width:100%}.sb-tour-actions button{flex:1}}
""".strip()
    tour = """
<div class="sb-tour" hidden>
<div class="sb-tour-shade" data-shade="top"></div><div class="sb-tour-shade" data-shade="right"></div>
<div class="sb-tour-shade" data-shade="bottom"></div><div class="sb-tour-shade" data-shade="left"></div>
<div class="sb-tour-highlight"></div>
<section class="sb-tour-tooltip" role="dialog" aria-modal="true" aria-labelledby="sb-tour-title">
<button class="sb-tour-close" type="button" aria-label="Close tour">&times;</button>
<p class="sb-tour-step"></p><h2 class="sb-tour-title" id="sb-tour-title"></h2>
<p class="sb-tour-copy"></p><div class="sb-tour-footer"><div class="sb-tour-dots" aria-hidden="true"></div>
<div class="sb-tour-actions"><button class="sb-tour-skip" type="button">Skip</button>
<button class="sb-tour-back" type="button">Back</button>
<button class="sb-tour-next" type="button">Next</button></div></div></section></div>
""".strip()
    js = """
(()=>{"use strict";
const seenKey="has_seen_tour";
const steps=[
{selector:'[data-tour="silicon-score"]',title:"SiliconScore",copy:"The headline score combines functional success with normalized physical quality."},
{selector:'[data-tour="score-columns"]',title:"Pass@1 and Mean PPA",copy:"Pass@1 measures correctness. Mean PPA compares area, timing, and power only for passing designs."},
{selector:'[data-tour="tier-toggle"]',title:"Tier breakdown",copy:"Open the tier guide to distinguish primitives, IP blocks, and system-level datapaths."},
{selector:'[data-tour="track-tabs"]',title:"Two benchmark tracks",copy:"Track A measures generation. Track B measures agentic optimization and repair."},
{selector:'[data-tour="submit-model"]',title:"Submit your model",copy:"Open a pull request to add a reproducible model run to the benchmark."},
{selector:'[data-tour="methodology"]',title:"Read the methodology",copy:"Review the scoring, gates, task tiers, and reproducibility protocol behind every result."}
];
const storeSeen=()=>{try{localStorage.setItem(seenKey,"true")}catch(_error){}};
const hasSeen=()=>{try{return localStorage.getItem(seenKey)==="true"}catch(_error){return false}};
function initControls(){
 const tier=document.querySelector(".tier-toggle");
 if(tier)tier.addEventListener("click",()=>{const panel=document.getElementById(tier.getAttribute("aria-controls"));const open=tier.getAttribute("aria-expanded")==="true";tier.setAttribute("aria-expanded",String(!open));if(panel)panel.hidden=open});
 const tabs=[...document.querySelectorAll('[role="tab"]')];
 tabs.forEach(tab=>tab.addEventListener("click",()=>{tabs.forEach(item=>{const selected=item===tab;item.setAttribute("aria-selected",String(selected));const panel=document.getElementById(item.getAttribute("aria-controls"));if(panel)panel.hidden=!selected})}));
}
function initTour(){
 if(hasSeen())return;
 const root=document.querySelector(".sb-tour");
 if(!root)return;
 const available=steps.map(step=>({...step,target:document.querySelector(step.selector)})).filter(step=>step.target);
 if(!available.length){storeSeen();return}
 const tooltip=root.querySelector(".sb-tour-tooltip");
 const highlight=root.querySelector(".sb-tour-highlight");
 const title=root.querySelector(".sb-tour-title");
 const copy=root.querySelector(".sb-tour-copy");
 const label=root.querySelector(".sb-tour-step");
 const dots=root.querySelector(".sb-tour-dots");
 const back=root.querySelector(".sb-tour-back");
 const next=root.querySelector(".sb-tour-next");
 const skip=root.querySelector(".sb-tour-skip");
 const close=root.querySelector(".sb-tour-close");
 const shades=Object.fromEntries([...root.querySelectorAll("[data-shade]")].map(node=>[node.dataset.shade,node]));
 let index=0;
 let frame=0;
 const previousFocus=document.activeElement;
 const finish=()=>{storeSeen();root.hidden=true;document.removeEventListener("keydown",onKey);window.removeEventListener("resize",queuePosition);window.removeEventListener("scroll",queuePosition,true);if(previousFocus&&previousFocus.focus)previousFocus.focus()};
 const setBox=(node,left,top,width,height)=>{Object.assign(node.style,{left:`${left}px`,top:`${top}px`,width:`${Math.max(0,width)}px`,height:`${Math.max(0,height)}px`})};
 const position=()=>{
  if(root.hidden)return;
  const margin=12,gap=12,pad=6,vw=document.documentElement.clientWidth,vh=document.documentElement.clientHeight;
  const rect=available[index].target.getBoundingClientRect();
  const left=Math.max(0,rect.left-pad),top=Math.max(0,rect.top-pad),right=Math.min(vw,rect.right+pad),bottom=Math.min(vh,rect.bottom+pad);
  setBox(shades.top,0,0,vw,top);setBox(shades.bottom,0,bottom,vw,vh-bottom);setBox(shades.left,0,top,left,bottom-top);setBox(shades.right,right,top,vw-right,bottom-top);
  setBox(highlight,left,top,right-left,bottom-top);
  tooltip.style.left="0px";tooltip.style.top="0px";
  const tw=tooltip.offsetWidth,th=tooltip.offsetHeight,cx=(left+right)/2,cy=(top+bottom)/2;
  const candidates=[
   {name:"bottom",x:cx-tw/2,y:bottom+gap},{name:"top",x:cx-tw/2,y:top-th-gap},
   {name:"right",x:right+gap,y:cy-th/2},{name:"left",x:left-tw-gap,y:cy-th/2}
  ];
  const chosen=candidates.find(item=>item.x>=margin&&item.y>=margin&&item.x+tw<=vw-margin&&item.y+th<=vh-margin)||candidates[0];
  const x=Math.min(Math.max(margin,chosen.x),Math.max(margin,vw-tw-margin));
  const y=Math.min(Math.max(margin,chosen.y),Math.max(margin,vh-th-margin));
  tooltip.style.left=`${x}px`;tooltip.style.top=`${y}px`;tooltip.dataset.placement=chosen.name;
 };
 const queuePosition=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(position)};
 const show=nextIndex=>{
  index=nextIndex;const step=available[index];
  label.textContent=`Step ${index+1} of ${available.length}`;title.textContent=step.title;copy.textContent=step.copy;
  back.disabled=index===0;next.textContent=index===available.length-1?"Done":"Next";
  dots.replaceChildren(...available.map((_item,dotIndex)=>{const dot=document.createElement("span");dot.className=`sb-tour-dot${dotIndex===index?" active":""}`;return dot}));
  root.hidden=false;
  const rect=step.target.getBoundingClientRect();
  if(rect.top<16||rect.bottom>window.innerHeight-16)step.target.scrollIntoView({block:"center",behavior:"instant"});
  requestAnimationFrame(()=>{position();next.focus()});
 };
 const onKey=event=>{
  if(event.key==="Escape"){event.preventDefault();finish();return}
  if(event.key!=="Tab"||root.hidden)return;
  const focusable=[...tooltip.querySelectorAll("button:not([disabled])")];
  if(!focusable.length)return;
  const first=focusable[0],last=focusable[focusable.length-1];
  if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
  else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
 };
 next.addEventListener("click",()=>index===available.length-1?finish():show(index+1));
 back.addEventListener("click",()=>{if(index>0)show(index-1)});
 skip.addEventListener("click",finish);close.addEventListener("click",finish);
 document.addEventListener("keydown",onKey);window.addEventListener("resize",queuePosition);window.addEventListener("scroll",queuePosition,true);
 show(0);
}
document.addEventListener("DOMContentLoaded",()=>{initControls();initTour()});
})();
""".strip()
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{css}</style></head>"
        f"<body>{content}{tour}<script>{js}</script></body></html>\n"
    )


def _text(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise SiteGenerationError(f"{key} must be nonempty text: {path}")
    return value


def _number(raw: dict[str, Any], key: str, path: Path) -> float:
    value = _finite_number(raw.get(key), key)
    if value < 0:
        raise SiteGenerationError(f"{key} must be nonnegative: {path}")
    return value


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SiteGenerationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise SiteGenerationError(f"{label} must be finite")
    return result


def _integer(raw: dict[str, Any], key: str, path: Path) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SiteGenerationError(f"{key} must be a nonnegative integer: {path}")
    return value


def _validate_timestamp(value: str, path: Path) -> None:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SiteGenerationError(f"invalid timestamp in {path}") from exc


def _date(timestamp: str) -> str:
    return timestamp[:10]


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-").lower()
    return slug or "run"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default="results/eval")
    parser.add_argument("--agent-results", default="results/agent")
    parser.add_argument("--out", default="site/build")
    args = parser.parse_args(argv)
    try:
        built = generate_site(
            args.results,
            args.out,
            agent_results_root=args.agent_results,
        )
    except SiteGenerationError as exc:
        parser.exit(2, f"site generation refused: {exc}\n")
    for path in built.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
