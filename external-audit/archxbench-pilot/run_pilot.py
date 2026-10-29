"""In-container orchestrator: run every frozen pilot task twice and compare.

Writes per-design reports/analyses, an aggregate, a determinism check and an explicit
verdict into --out. Never writes to the vendor tree or the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent
sys.path[:0] = [str(AUDIT), str(AUDIT.parent)]

import archxbench_analysis as analysis  # noqa: E402


def run_design(task: dict, vendor: Path, out: Path, tag: str, sha: str, seed: int, operators: str = "v1") -> int:
    stem = f"{task['design_id']}.{tag}"
    cmd = [sys.executable, str(AUDIT / "archxbench_pilot.py"),
           "--vendor-root", str(vendor), "--expected-vendor-sha", sha,
           "--task-path", task["task_path"], "--design-id", task["design_id"],
           "--reference", str(HERE / task["reference"]), "--module", task["module"],
           "--tb-top", task["tb_top"], "--seed", str(seed),
           "--out", str(out / "results" / f"{stem}.report.json"),
           "--analysis-out", str(out / "results" / f"{stem}.analysis.json"),
           "--log-dir", str(out / "logs" / stem), "--operators", operators]
    if task.get("summary_module"):
        cmd += ["--summary-module", task["summary_module"]]
    env = {**os.environ, "PYTHONPATH": f"{AUDIT}:{AUDIT.parent}"}
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    (out / "logs" / f"{stem}.driver.log").write_text(proc.stdout + proc.stderr)
    return proc.returncode


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor-root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--committed-results", type=Path)
    ap.add_argument("--tasks", type=Path, default=HERE / "tasks.json",
                    help="task list (default: v1 pilot; v2/tasks.json for the extended experiment)")
    a = ap.parse_args()
    tasks = load(a.tasks)
    operators = tasks.get("operators", "v1")
    sha, seed = tasks["vendor"]["commit"], tasks["seed"]
    (a.out / "results").mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    problems: list[str] = []
    all_tasks = tasks["primary"] + tasks["supplementary"]
    exit_codes: dict[str, dict[str, int]] = {}
    for task in all_tasks:
        for tag in ("run1", "run2"):
            rc = run_design(task, a.vendor_root, a.out, tag, sha, seed, operators)
            exit_codes.setdefault(task["design_id"], {})[tag] = rc
            # rc 0 = audited, 2 = unsupported (baseline failed); anything else is a setup error.
            if rc not in (0, 2):
                problems.append(f"{task['design_id']} {tag}: driver exit {rc}")
    determinism, analyses = {}, []
    for task in all_tasks:
        d = task["design_id"]
        try:
            one, two = (load(a.out / "results" / f"{d}.{t}.analysis.json") for t in ("run1", "run2"))
        except FileNotFoundError:
            problems.append(f"{d}: analysis missing")
            continue
        same = analysis.deterministic_view(one) == analysis.deterministic_view(two)
        determinism[d] = same
        if not same:
            problems.append(f"{d}: run1 != run2 (nondeterminism)")
        analyses.append(a.out / "results" / f"{d}.run1.analysis.json")
        if one["design_state"] != "BASELINE_PASS":
            problems.append(f"{d}: baseline did not pass ({one['design_state']})")
        if not one["reference_vs_oracle"]["matches_oracle_exhaustively"]:
            problems.append(f"{d}: reference disagrees with independent oracle")
    supplementary = {t["design_id"] for t in tasks["supplementary"]}
    aggregate = analysis.aggregate(analyses, supplementary) if analyses else {}
    (a.out / "results" / "aggregate.json").write_text(json.dumps(aggregate, indent=2, sort_keys=True) + "\n")
    matches = None
    if a.committed_results and a.committed_results.is_dir() and analyses:
        matches = {}
        for path in analyses:
            committed = a.committed_results / path.name.replace(".run1", "")
            matches[path.name] = (committed.is_file() and analysis.deterministic_view(load(path))
                                  == analysis.deterministic_view(load(committed)))
        if not all(matches.values()):
            problems.append("results differ from committed results: "
                            + ", ".join(k for k, v in matches.items() if not v))
    verdict = {
        "verdict": "PILOT_REPRODUCED" if not problems else "PILOT_NOT_REPRODUCED",
        "problems": problems,
        "run_to_run_deterministic": determinism,
        "matches_committed_results": matches,
        "driver_exit_codes": exit_codes,
        "wall_s": round(time.monotonic() - started, 1),
        "caveat": "Reproduction proves the experiment re-executes identically; it does not validate the "
                  "evaluator-authored references against ArchXBench maintainers' intent.",
    }
    (a.out / "results" / "verdict.json").write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n")
    sums = []
    for path in sorted((a.out).rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            sums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(a.out).as_posix()}")
    (a.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    print(json.dumps(verdict, indent=2, sort_keys=True))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
