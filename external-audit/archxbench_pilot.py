"""Read-only, one-task ArchXBench adapter for GateTruth's existing mutation auditor.

No reference RTL is included or inferred: the evaluator must supply and review it.
The adapter is an experimental pilot, not a validated external benchmark result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import re
import shutil
import subprocess
from pathlib import Path

from auditor.audit import audit_design
from auditor.protocol import TbResult, Verdict


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def under(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(f"missing or escaping path: {relative}")
    return candidate


class ArchXBenchRunner:
    suite = "archxbench"

    def __init__(self, testbench: Path, module: str, tb_top: str,
                 iverilog: str = "iverilog", vvp: str = "vvp"):
        if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", x) for x in (module, tb_top)):
            raise ValueError("invalid Verilog module/top identifier")
        self.testbench = testbench
        self.module = module
        self.tb_top = tb_top
        self.iverilog = iverilog
        self.vvp = vvp

    def run(self, design_id: str, rtl_source: str, work_dir: Path, *, timeout_s: float) -> TbResult:
        del design_id
        work_dir.mkdir(parents=True, exist_ok=False)
        candidate = work_dir / "code.v"
        candidate.write_text(rtl_source, encoding="utf-8")
        local_tb = work_dir / "tb.v"
        shutil.copy2(self.testbench, local_tb)
        executable = work_dir / "simulation.out"
        try:
            compiled = subprocess.run(
                [self.iverilog, "-g2012", "-s", self.tb_top, "-o", str(executable),
                 str(candidate), str(local_tb)], cwd=work_dir,
                text=True, capture_output=True, timeout=timeout_s, check=False,
            )
            (work_dir / "compile.log").write_text(compiled.stdout + compiled.stderr)
            if compiled.returncode != 0:
                return TbResult(Verdict.FAIL, "compile")
            ran = subprocess.run([self.vvp, str(executable)], cwd=work_dir,
                                 text=True, capture_output=True, timeout=timeout_s,
                                 check=False)
            (work_dir / "simulation.log").write_text(ran.stdout + ran.stderr)
        except subprocess.TimeoutExpired:
            return TbResult(Verdict.TIMEOUT, None)
        except OSError:
            return TbResult(Verdict.NOT_RUNNABLE, None)

        # ArchXBench includes an explicit JSON summary line. A zero exit code
        # or casual PASS text alone is NEVER a successful baseline.
        summaries = []
        for line in ran.stdout.splitlines():
            if line.strip().startswith('{"module":'):
                try:
                    summaries.append(json.loads(line))
                except json.JSONDecodeError:
                    return TbResult(Verdict.NOT_RUNNABLE, None)
        if len(summaries) != 1:
            return TbResult(Verdict.NOT_RUNNABLE, None)
        summary = summaries[0]
        if (summary.get("module") != self.module
                or type(summary.get("passed")) is not int
                or type(summary.get("failed")) is not int
                or summary["passed"] < 0 or summary["failed"] < 0):
            return TbResult(Verdict.NOT_RUNNABLE, None)
        if summary["failed"] > 0:
            return TbResult(Verdict.FAIL, "tb")
        if ran.returncode == 0 and summary["passed"] > 0:
            return TbResult(Verdict.PASS, None)
        return TbResult(Verdict.NOT_RUNNABLE, None)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor-root", required=True, type=Path)
    parser.add_argument("--expected-vendor-sha", required=True)
    parser.add_argument("--task-path", required=True, help="relative to vendor root")
    parser.add_argument("--design-id", required=True)
    parser.add_argument("--reference", required=True, type=Path,
                        help="reviewed reference RTL supplied by evaluator; ArchXBench does not bundle it")
    parser.add_argument("--module", required=True)
    parser.add_argument("--tb-top", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    a = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.design_id):
        parser.error("design-id must be a safe single token")
    if not re.fullmatch(r"[0-9a-f]{40}", a.expected_vendor_sha):
        parser.error("expected-vendor-sha must be the full 40-character commit")
    vendor_root = a.vendor_root.resolve()
    actual_sha = subprocess.run(["git", "-C", str(vendor_root), "rev-parse", "HEAD"],
                                text=True, capture_output=True, check=True).stdout.strip()
    if actual_sha != a.expected_vendor_sha:
        parser.error(f"vendor SHA mismatch: {actual_sha} != {a.expected_vendor_sha}")
    tb = under(vendor_root, f"{a.task_path}/tb.v")
    source = a.reference.read_text(encoding="utf-8")
    if not source.strip():
        parser.error("empty reference RTL")
    tool = subprocess.run([a.iverilog, "-V"], capture_output=True, text=True, check=True)
    runner = ArchXBenchRunner(tb, a.module, a.tb_top, a.iverilog, a.vvp)
    catalog = {
        "_golden_source": source,
        "_vendor_commit": actual_sha,
        "_tool_versions": {"python": platform.python_version(),
                           "iverilog": (tool.stdout or tool.stderr).splitlines()[0]},
        "reference_sha256": sha256(source.encode()),
        "testbench_sha256": sha256(tb.read_bytes()),
        "notes": "Pilot; evaluator-supplied reference, not ArchXBench-issued golden RTL",
    }
    report = audit_design(a.design_id, runner, a.seed, catalog, generation_flag="-g2012")
    compile_failed = [x["id"] for x in report["per_mutant"] if x["killed_by"] == "compile"]
    report["adoption_pilot"] = {
        "target_commit": actual_sha,
        "reference_origin": str(a.reference.resolve()),
        "evaluator_reference_not_upstream_golden": True,
        "compile_failed_mutants_not_behavioral_evidence": compile_failed,
        "behavioral_kills": sum(x["verdict"] == "killed" and x["killed_by"] == "tb"
                               for x in report["per_mutant"]),
        "mutant_equivalence_checked": False,
        "requires_independent_validation": True,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"status={report['status']} mutants={report['mutants_total']} "
          f"behavioral_kills={report['adoption_pilot']['behavioral_kills']} "
          f"compile_failures={len(compile_failed)}")
    return 0 if report["status"] == "audited" else 2


if __name__ == "__main__":
    raise SystemExit(main())
