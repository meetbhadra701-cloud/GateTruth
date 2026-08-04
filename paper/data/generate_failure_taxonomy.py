"""Generate the Track A failure-stage taxonomy from the signed 16,384-token campaign.

Reads only committed evidence: the 420 signed per-sample manifests under
``results/eval-16384/<model>/<task_id>/sample_1.json`` and the committed
``paper/data/lint_diagnostics_ledger.json`` (itself generated once from local Verilator
logs by ``scripts/generate_lint_diagnostics_ledger.py`` -- see that script's docstring).
Every count in Table~\\ref{tab:taxonomy} and the surrounding prose in
``paper/main.tex``'s Limitations section is derived here rather than hand-transcribed.

Classification of a failing (model, task) pair:

- ``generation_error`` starting with ``"ValueError"`` -- the provider returned text but
  no valid single-module SystemVerilog declaration could be extracted from it
  (``no_extraction``).
- ``generation_error`` starting with ``"provider error"`` -- the API call itself failed
  (transport error, non-2xx status, empty response) before any generation was produced
  (``provider_error``). This is infrastructure flakiness, not a model-capability signal.
  The 16,384-token campaign this script reads predates harness/providers/retry.py, which
  now retries transient failures (HTTP 408/429/5xx, dropped connections, truncated
  reads) up to twice with a bounded backoff before giving up -- so this dataset's
  provider_error counts include transient blips a rerun would no longer record as
  failures at all, not just ones a rerun would still classify the same way. See the
  Limitations paragraph this script backs.
- ``generation_error`` is ``None`` -- a module was extracted and scored for real; the
  first stage (in pipeline order) with status ``"fail"`` among lint/sim/formal is the
  failing stage. A ``lint`` failure is further split into ``width_only`` (every
  Verilator diagnostic code in the ledger for that pair is WIDTHTRUNC/WIDTHEXPAND) and
  ``other``.

Any ``generation_error`` value matching neither known prefix is a hard error: this
script is deliberately unable to guess at a failure mode it has not been taught, per the
project's fail-closed convention for paper-data generators.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness.schemas.manifest import load_manifest  # noqa: E402

RESULTS_ROOT = REPO_ROOT / "results" / "eval-16384"
LEDGER_PATH = REPO_ROOT / "paper" / "data" / "lint_diagnostics_ledger.json"
OUT_PATH = REPO_ROOT / "paper" / "data" / "build" / "failure_taxonomy_table.tex"
TASKS_ROOT = REPO_ROOT / "tasks"


def _canonical_task_ids(tasks_root: Path = TASKS_ROOT) -> frozenset[str]:
    """Track A task ids, read directly from task.yaml directory names to avoid
    importing harness.evalmodel (which pulls in harness.runner -> harness.hidden ->
    cocotb, a dependency only present inside the pinned Docker image, not on a bare
    host running this generator)."""

    return frozenset(path.parent.name for path in tasks_root.glob("*/task.yaml"))

EXPECTED_MODELS = frozenset(
    {
        "claude-opus-4-8",
        "claude-sonnet-4-6",
        "claude-haiku-4-5-20251001",
        "gpt-5",
        "gpt-5-mini",
        "google_gemini-2.5-pro",
        "meta-llama_llama-4-maverick",
    }
)
WIDTH_ONLY_CODES = frozenset({"WIDTHTRUNC", "WIDTHEXPAND"})


class TaxonomyDataError(RuntimeError):
    """Raised when the evidence does not support the taxonomy this script claims."""


def _classify(manifest, ledger_pairs: dict[str, list[str]], key: str) -> str:
    err = manifest.generation_error
    if err is not None:
        if err.startswith("ValueError"):
            return "no_extraction"
        if err.startswith("provider error"):
            return "provider_error"
        raise TaxonomyDataError(f"{key}: unrecognized generation_error prefix: {err!r}")

    stages = {stage.name: stage.status for stage in manifest.stages}
    for gate in ("lint", "sim", "formal"):
        if stages.get(gate) == "fail":
            if gate != "lint":
                return gate
            codes = ledger_pairs.get(key)
            if codes is None:
                raise TaxonomyDataError(
                    f"{key}: lint failure has no lint_diagnostics_ledger entry "
                    "(re-run scripts/generate_lint_diagnostics_ledger.py)"
                )
            return "lint_width_only" if codes and set(codes) <= WIDTH_ONLY_CODES else "lint_other"
    raise TaxonomyDataError(f"{key}: task_score is 0 but no correctness gate (lint/sim/formal) failed")


def collect(
    results_root: Path = RESULTS_ROOT,
    ledger_path: Path = LEDGER_PATH,
    *,
    tasks_root: Path = TASKS_ROOT,
) -> dict:
    ledger_raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_pairs: dict[str, list[str]] = ledger_raw["pairs"]

    expected_tasks = _canonical_task_ids(tasks_root)
    if len(expected_tasks) != 60:
        raise TaxonomyDataError(f"expected 60 canonical Track A tasks, found {len(expected_tasks)}")

    manifest_paths = sorted(results_root.glob("*/*/sample_1.json"))
    if len(manifest_paths) != len(EXPECTED_MODELS) * 60:
        raise TaxonomyDataError(
            f"expected {len(EXPECTED_MODELS) * 60} signed samples under {results_root}, "
            f"found {len(manifest_paths)}"
        )

    seen_models: set[str] = set()
    seen_tasks_per_model: dict[str, set[str]] = defaultdict(set)
    rows: list[dict] = []
    used_ledger_keys: set[str] = set()

    for manifest_path in manifest_paths:
        model_dir = manifest_path.parent.parent.name
        task_id = manifest_path.parent.name
        manifest = load_manifest(manifest_path)
        if manifest.task_id != task_id:
            raise TaxonomyDataError(
                f"{manifest_path}: manifest task_id {manifest.task_id!r} != directory {task_id!r}"
            )
        seen_models.add(model_dir)
        seen_tasks_per_model[model_dir].add(task_id)

        key = f"{model_dir}/{task_id}"
        category = "pass" if manifest.task_score > 0 else _classify(manifest, ledger_pairs, key)
        if category in ("lint_width_only", "lint_other"):
            used_ledger_keys.add(key)
        rows.append(
            {
                "model": model_dir,
                "task_id": task_id,
                "tier": task_id.split("_")[0],
                "task_score": manifest.task_score,
                "ppa": manifest.ppa,
                "category": category,
            }
        )

    if seen_models != EXPECTED_MODELS:
        raise TaxonomyDataError(
            f"model set mismatch: missing={sorted(EXPECTED_MODELS - seen_models)}, "
            f"extra={sorted(seen_models - EXPECTED_MODELS)}"
        )
    for model, tasks in seen_tasks_per_model.items():
        if tasks != expected_tasks:
            raise TaxonomyDataError(f"{model}: task set does not match the canonical 60-task suite")
    stale_ledger_keys = set(ledger_pairs) - used_ledger_keys
    if stale_ledger_keys:
        raise TaxonomyDataError(
            f"lint_diagnostics_ledger.json has {len(stale_ledger_keys)} entries not backed by a "
            f"current lint failure (stale ledger -- regenerate it): {sorted(stale_ledger_keys)[:5]}"
        )

    return {"rows": rows}


def summarize(data: dict) -> dict:
    rows = data["rows"]
    total = len(rows)
    by_category = Counter(r["category"] for r in rows)
    failing = total - by_category["pass"]

    real_submission_categories = {"lint_width_only", "lint_other", "sim", "formal"}
    real_submission_failures = sum(by_category[c] for c in real_submission_categories)
    no_code_categories = {"no_extraction", "provider_error"}
    no_code_count = sum(by_category[c] for c in no_code_categories)
    assert no_code_count + real_submission_failures == failing

    lint_total = by_category["lint_width_only"] + by_category["lint_other"]

    by_model_width = Counter(r["model"] for r in rows if r["category"] == "lint_width_only")

    tier_total: Counter[str] = Counter()
    tier_pass: Counter[str] = Counter()
    tier_total_excl: Counter[str] = Counter()
    tier_pass_excl: Counter[str] = Counter()
    for r in rows:
        tier_total[r["tier"]] += 1
        is_pass = r["category"] == "pass"
        if is_pass:
            tier_pass[r["tier"]] += 1
        if r["category"] not in no_code_categories:
            tier_total_excl[r["tier"]] += 1
            if is_pass:
                tier_pass_excl[r["tier"]] += 1

    by_task_scores: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_task_scores[r["task_id"]].append(r["task_score"])
    zero_pass_tasks = sorted(t for t, scores in by_task_scores.items() if all(s == 0 for s in scores))

    passed = [r for r in rows if r["category"] == "pass"]
    ppa_degenerate = sum(1 for r in passed if abs(r["ppa"] - 1.0) < 1e-6)

    return {
        "total_pairs": total,
        "failing_pairs": failing,
        "no_extraction": by_category["no_extraction"],
        "provider_error": by_category["provider_error"],
        "lint_total": lint_total,
        "lint_width_only": by_category["lint_width_only"],
        "lint_other": by_category["lint_other"],
        "sim_fail": by_category["sim"],
        "formal_fail": by_category["formal"],
        "real_submission_failures": real_submission_failures,
        "width_only_by_model": dict(by_model_width),
        "tier_pass_rate": {t: (tier_pass[t], tier_total[t]) for t in ("t1", "t2", "t3")},
        "tier_pass_rate_excl_no_code": {
            t: (tier_pass_excl[t], tier_total_excl[t]) for t in ("t1", "t2", "t3")
        },
        "zero_pass_tasks": zero_pass_tasks,
        "ppa_degenerate": (ppa_degenerate, len(passed)),
    }


def _tex(value: str) -> str:
    return value.replace("_", r"\_")


def render_tex(data: dict, summary: dict) -> str:
    rows = data["rows"]
    by_model: dict[str, Counter[str]] = defaultdict(Counter)
    for r in rows:
        by_model[r["model"]][r["category"]] += 1

    lines = [
        "% generated by paper/data/generate_failure_taxonomy.py -- do not hand-edit",
        r"\begin{tabular}{lrrrrrrr}",
        r"\toprule",
        r"Model & No-extr. & Prov.err & Lint (width) & Lint (other) & Sim & Formal & Pass \\",
        r"\midrule",
    ]
    for model in sorted(by_model):
        c = by_model[model]
        lines.append(
            f"\\texttt{{{_tex(model)}}} & {c['no_extraction']} & {c['provider_error']} & "
            f"{c['lint_width_only']} & {c['lint_other']} & {c['sim']} & {c['formal']} & "
            f"{c['pass']} \\\\"
        )
    lines.append(r"\midrule")
    lines.append(
        f"Total & {summary['no_extraction']} & {summary['provider_error']} & "
        f"{summary['lint_width_only']} & {summary['lint_other']} & {summary['sim_fail']} & "
        f"{summary['formal_fail']} & {summary['total_pairs'] - summary['failing_pairs']} \\\\"
    )
    lines += [r"\bottomrule", r"\end{tabular}"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", type=Path, default=RESULTS_ROOT)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args(argv)

    try:
        data = collect(args.results_root, args.ledger)
    except TaxonomyDataError as exc:
        parser.exit(2, f"failure taxonomy generation refused: {exc}\n")

    summary = summarize(data)
    rendered = render_tex(data, summary)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"wrote {args.out}")
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
