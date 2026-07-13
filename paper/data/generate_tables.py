"""Generate deterministic SiliconBench paper data tables from live repository data."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.schemas.canonical_json import compute_manifest_signature  # noqa: E402
from harness.schemas.manifest import load_manifest  # noqa: E402
from harness.schemas.task_yaml import load_task_yaml  # noqa: E402


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


def generate_tables(
    *,
    out_dir: str | Path,
    tasks_root: str | Path = REPO_ROOT / "tasks",
    refs_dir: str | Path = REPO_ROOT / "results" / "refs",
    mutation_dir: str | Path = REPO_ROOT / "results" / "mutation",
    eval_dir: str | Path = REPO_ROOT / "results" / "eval",
    generated_date: date | None = None,
    git_sha: str | None = None,
) -> dict[str, Path]:
    """Load live data and write all six Markdown/LaTeX table artifacts."""

    run_date = generated_date or datetime.now(UTC).date()
    sha = git_sha or _git_sha(REPO_ROOT)
    tasks = load_tasks(Path(tasks_root), Path(refs_dir))
    mutations = load_mutations(Path(mutation_dir))
    evaluations = load_evaluations(Path(eval_dir))
    metadata = f"generated-on: {run_date.isoformat()} git-sha: {sha}"
    artifacts = {
        "eval_table.md": _eval_markdown(evaluations, metadata),
        "eval_table.tex": _eval_latex(evaluations, metadata),
        "mutation_table.md": _mutation_markdown(mutations, metadata),
        "mutation_table.tex": _mutation_latex(mutations, metadata),
        "tasks_table.md": _tasks_markdown(tasks, metadata),
        "tasks_table.tex": _tasks_latex(tasks, metadata),
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
        area = _stage_metric(manifest, 3, "area_um2") if manifest else None
        wns = _stage_metric(manifest, 4, "wns_ns") if manifest else None
        power = _stage_metric(manifest, 5, "power_mw") if manifest else None
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


def load_mutations(directory: Path) -> list[MutationRecord]:
    """Load the lexically latest valid sequential report for each task."""

    latest: dict[str, MutationRecord] = {}
    if not directory.is_dir():
        return []
    for path in sorted(directory.rglob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TableDataError(f"invalid mutation JSON {path}: {exc}") from exc
        if not isinstance(raw, dict) or "kill_rate" not in raw:
            continue
        task_id = _text(raw, "task", path)
        total = _integer(raw, "total", path)
        killed = _integer(raw, "killed", path)
        kill_rate = _number(raw, "kill_rate", path)
        if killed > total or kill_rate < 0 or kill_rate > 100:
            raise TableDataError(f"invalid mutation counts in {path}")
        expected = 100.0 if total == 0 else 100.0 * killed / total
        if not math.isclose(kill_rate, expected, abs_tol=0.01):
            raise TableDataError(f"mutation kill rate mismatch in {path}")
        latest[task_id] = MutationRecord(task_id, total, killed, kill_rate)
    return [latest[task_id] for task_id in sorted(latest)]


def load_evaluations(directory: Path) -> list[EvalRecord]:
    """Load canonical-signature-validated Track A summaries."""

    if not directory.is_dir():
        return []
    records: list[EvalRecord] = []
    for path in sorted(directory.glob("**/summary.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise TableDataError(f"invalid eval summary {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise TableDataError(f"eval summary must be an object: {path}")
        signature = raw.get("signature")
        if not isinstance(signature, str) or signature != compute_manifest_signature(raw):
            raise TableDataError(f"unsigned or tampered eval summary: {path}")
        tasks = raw.get("tasks")
        if not isinstance(tasks, dict):
            raise TableDataError(f"eval summary tasks must be an object: {path}")
        attempted = sum(
            isinstance(entry, dict) and entry.get("skipped") is False
            for entry in tasks.values()
        )
        records.append(
            EvalRecord(
                provider=_text(raw, "provider", path),
                model=_text(raw, "model", path),
                tasks=attempted,
                aggregate_score=_number(raw, "aggregate_mean", path),
                tokens=_integer(raw, "tokens_in", path) + _integer(raw, "tokens_out", path),
                cost_usd=_number(raw, "cost_usd", path),
            )
        )
    return sorted(records, key=lambda row: (-row.aggregate_score, row.model, row.provider))


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
        f"<!-- Missing ref PPA for {row.task_id}: ./siliconbench run --task {row.task_id} "
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
        f"% Missing ref PPA for {row.task_id}: ./siliconbench run --task {row.task_id} "
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


def _git_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="paper/data/build")
    parser.add_argument("--from-dir", default="results/mutation", dest="mutation_dir")
    parser.add_argument("--tasks-root", default="tasks")
    parser.add_argument("--refs-dir", default="results/refs")
    parser.add_argument("--eval-dir", default="results/eval")
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
            generated_date=run_date,
        )
    except (OSError, TableDataError, ValueError) as exc:
        parser.exit(2, f"table generation refused: {exc}\n")
    for path in paths.values():
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
