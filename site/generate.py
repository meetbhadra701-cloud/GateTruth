"""Generate the fully static SiliconBench leaderboard site."""

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

CANARY_RE = re.compile(
    r"SILICONBENCH-CANARY-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-"
    r"[0-9A-F]{4}-[0-9A-F]{12}",
    re.IGNORECASE,
)


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


def generate_site(
    results_root: str | Path = "results/eval",
    build_root: str | Path = "site/build",
) -> dict[str, Path]:
    """Validate signed summaries and atomically render static leaderboard files."""

    results_path = Path(results_root).resolve()
    output_path = Path(build_root).resolve()
    if not results_path.is_dir():
        raise SiteGenerationError(f"results root does not exist: {results_path}")

    summaries = sorted(results_path.glob("**/summary.json"))
    if not summaries:
        raise SiteGenerationError(f"no summary.json files found under {results_path}")

    rows = [_load_summary(path, results_path) for path in summaries]
    rows.sort(key=lambda row: (-row.aggregate_score, row.model.lower(), row.run_id))

    artifacts: dict[str, str] = {
        "index.html": _render_index(rows),
        "leaderboard.json": json.dumps(
            {"schema_version": 1, "runs": [_public_row(row) for row in rows]},
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    for row in rows:
        artifacts[row.detail_page] = _render_detail(row)

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


def _public_row(row: LeaderboardRow) -> dict[str, Any]:
    return {
        "aggregate_score": row.aggregate_score,
        "badge": "OFFICIAL" if row.official else "DEV",
        "cost_usd": row.cost_usd,
        "detail_page": row.detail_page,
        "model": row.model,
        "official": row.official,
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


def _render_index(rows: list[LeaderboardRow]) -> str:
    body = []
    for rank, row in enumerate(rows, 1):
        badge = "official" if row.official else "dev"
        body.append(
            "<tr>"
            f"<td>{rank}</td>"
            f'<td><a href="{html.escape(row.detail_page)}">{html.escape(row.model)}</a>'
            f'<span class="sub">{html.escape(row.provider)} / {html.escape(row.run_id)}</span></td>'
            f'<td class="score">{row.aggregate_score:.2f}</td>'
            f"<td>{row.tasks_passed}/{row.tasks_attempted}</td>"
            f"<td>${row.cost_usd:.6f}</td>"
            f"<td>{row.tokens_in + row.tokens_out:,}</td>"
            f"<td>{html.escape(_date(row.run_date))}</td>"
            f'<td><span class="badge {badge}">{"OFFICIAL" if row.official else "DEV"}</span></td>'
            "</tr>"
        )
    table = "".join(body)
    content = (
        '<header><p class="kicker">SiliconBench</p><h1>RTL model leaderboard</h1>'
        '<p class="lede">Signed PPA-aware evaluation results.</p></header>'
        '<main><div class="table-wrap"><table><thead><tr><th>#</th><th>Model</th>'
        '<th>Score</th><th>Passed</th><th>Cost</th><th>Tokens</th><th>Date</th>'
        f"<th>Run</th></tr></thead><tbody>{table}</tbody></table></div></main>"
    )
    return _page("SiliconBench leaderboard", content)


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
    return _page(f"{row.model} - SiliconBench", content)


def _page(title: str, content: str) -> str:
    css = """
:root{color-scheme:light dark;--bg:#f6f7f9;--panel:#fff;--text:#17202a;--muted:#66717e;--line:#d9dee5;--link:#185abd;--good:#08783e;--warn:#9a5b00;--bad:#b42318}
@media(prefers-color-scheme:dark){:root{--bg:#111419;--panel:#191e25;--text:#edf1f5;--muted:#a4afbb;--line:#343c47;--link:#7eb4ff;--good:#5fd492;--warn:#f2bd68;--bad:#ff8a82}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,sans-serif}header,main,nav{width:min(1180px,calc(100% - 32px));margin:0 auto}header{padding:36px 0 22px}nav{padding-top:24px}h1{font-size:30px;letter-spacing:0;margin:4px 0}.kicker{color:var(--link);font-weight:700;margin:0}.lede,.sub{color:var(--muted)}.sub{display:block;font-size:12px;margin-top:2px}a{color:var(--link);font-weight:600;text-decoration:none}a:hover{text-decoration:underline}.table-wrap{background:var(--panel);border:1px solid var(--line);border-radius:6px;overflow:auto}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid var(--line);padding:12px 14px;text-align:left;vertical-align:top;white-space:nowrap}th{color:var(--muted);font-size:12px;text-transform:uppercase}tbody tr:last-child td{border-bottom:0}.score{font-variant-numeric:tabular-nums;font-weight:700}.badge,.chip{border:1px solid var(--line);border-radius:4px;display:inline-block;font-size:11px;font-weight:700;padding:2px 6px}.official,.pass{border-color:var(--good);color:var(--good)}.dev,.skip{border-color:var(--warn);color:var(--warn)}.fail{border-color:var(--bad);color:var(--bad)}.chips{white-space:normal}.chip{margin:0 4px 4px 0}.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}.metrics div{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:14px}.metrics span{color:var(--muted);display:block;font-size:12px}.metrics strong{font-size:20px}@media(max-width:700px){.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:24px}}
""".strip()
    return (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{css}</style></head>"
        f"<body>{content}</body></html>\n"
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
    parser.add_argument("--out", default="site/build")
    args = parser.parse_args(argv)
    try:
        built = generate_site(args.results, args.out)
    except SiteGenerationError as exc:
        parser.exit(2, f"site generation refused: {exc}\n")
    for path in built.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
