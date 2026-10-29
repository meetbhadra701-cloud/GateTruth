"""Validate every evaluator-authored reference BEFORE any mutation is run.

For each task: (1) the pinned upstream testbench passes the unmodified reference; (2) the
reference's simulated behavior equals the independent oracle on every legal input (or on the
fixed reset stimulus, for sequential designs). No mutants are generated or run here.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent
sys.path[:0] = [str(AUDIT), str(AUDIT.parent)]

import archxbench_formal as formal  # noqa: E402
from archxbench_pilot import ArchXBenchRunner, verify_vendor  # noqa: E402
from auditor.protocol import Verdict  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor-root", required=True, type=Path)
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    tasks = json.loads(a.tasks.read_text())
    report, ok = {}, True
    for task in tasks["primary"] + tasks["supplementary"]:
        _, tb = verify_vendor(a.vendor_root.resolve(), tasks["vendor"]["commit"], task["task_path"])
        source = (HERE / task["reference"]).read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="gt-refcheck-") as tmp:
            runner = ArchXBenchRunner(tb, task["module"], task["tb_top"], summary_module=task.get("summary_module"))
            result = runner.run(task["design_id"], source, Path(tmp) / "baseline", timeout_s=30)
            rows = formal.behavior_rows("iverilog", "vvp", source, task["module"], Path(tmp) / "beh")
        expected = formal.expected_rows(task["module"])
        entry = {"baseline_testbench": runner.records["baseline"]["outcome"],
                 "testbench_summary": runner.records["baseline"].get("summary"),
                 "oracle_rows": len(expected), "matches_independent_oracle": rows == expected}
        entry["valid"] = result.verdict == Verdict.PASS and entry["matches_independent_oracle"]
        ok &= entry["valid"]
        report[task["design_id"]] = entry
        print(f"{task['design_id']:<24} tb={entry['baseline_testbench']:<5} oracle_match={entry['matches_independent_oracle']}")
    if a.out:
        a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("ALL_REFERENCES_VALID" if ok else "REFERENCE_VALIDATION_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
