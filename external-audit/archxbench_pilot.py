"""Read-only ArchXBench adapter for GateTruth's existing mutation auditor.

No reference RTL is bundled by ArchXBench for the tasks this pilot targets: the evaluator
must supply and review it. The adapter is an experimental pilot, not a validated
external benchmark result.

Outcome policy (see ``ArchXBenchRunner.run``):

* A testbench PASS requires compilation, exactly one well-formed JSON summary line for
  the expected module, ``failed == 0``, ``passed > 0``, the same total check count as the
  baseline, and a zero process exit code. An exit code of zero alone proves nothing.
* A compile failure is ``NOT_RUNNABLE`` / ``compile`` -- never a testbench kill.
* ``failed > 0`` in a well-formed summary is the only ``FAIL`` (a behavioral kill).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from auditor.audit import audit_design
from auditor.protocol import TbResult, Verdict

IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SAFE_ENV_KEYS = ("PATH", "IVERILOG_ROOT", "HOME")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def under(root: Path, relative: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError(f"missing or escaping path: {relative}")
    return candidate


def sim_env() -> dict[str, str]:
    """Minimal deterministic environment for simulator subprocesses."""
    env = {k: os.environ[k] for k in SAFE_ENV_KEYS if k in os.environ}
    env.update({"LC_ALL": "C", "LANG": "C", "TZ": "UTC"})
    return env


def declares_module(source: str, module: str) -> bool:
    stripped = re.sub(r"//[^\n]*|/\*.*?\*/", " ", source, flags=re.S)
    return re.search(rf"\bmodule\s+{re.escape(module)}\b", stripped) is not None


class ArchXBenchRunner:
    suite = "archxbench"

    def __init__(self, testbench: Path, module: str, tb_top: str,
                 iverilog: str = "iverilog", vvp: str = "vvp",
                 log_dir: Path | None = None, summary_module: str | None = None):
        # summary_module: the name the testbench prints in its JSON summary, when it differs from
        # the DUT module (e.g. ArchXBench decoder-3to8 prints "decoder_3to8" for DUT "decoder3to8").
        if not all(IDENT.fullmatch(x) for x in (module, tb_top, summary_module or module)):
            raise ValueError("invalid Verilog module/top identifier")
        self.testbench = testbench
        self.module = module
        self.summary_module = summary_module or module
        self.tb_top = tb_top
        self.iverilog = iverilog
        self.vvp = vvp
        self.log_dir = log_dir
        self.expected_total: int | None = None
        self.records: dict[str, dict] = {}

    def _record(self, work_dir: Path, outcome: str, result: TbResult, **extra) -> TbResult:
        self.records[work_dir.name] = {"outcome": outcome, "verdict": result.verdict.value,
                                       "killed_by": result.killed_by, **extra}
        return result

    def _save_log(self, work_dir: Path, name: str, text: str) -> None:
        if self.log_dir is not None:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            (self.log_dir / f"{work_dir.name}.{name}.log").write_text(text, encoding="utf-8")

    def run(self, design_id: str, rtl_source: str, work_dir: Path, *, timeout_s: float) -> TbResult:
        del design_id
        started = time.monotonic()
        work_dir.mkdir(parents=True, exist_ok=False)
        base = {"rtl_sha256": sha256(rtl_source.encode("utf-8"))}
        tb_bytes = self.testbench.read_bytes()
        base["testbench_sha256"] = sha256(tb_bytes)
        if not declares_module(rtl_source, self.module):
            return self._record(work_dir, "SETUP_ERROR_MODULE_MISSING",
                                TbResult(Verdict.NOT_RUNNABLE, "setup"), **base)
        candidate = work_dir / "code.v"
        candidate.write_text(rtl_source, encoding="utf-8", newline="")
        local_tb = work_dir / "tb.v"
        local_tb.write_bytes(tb_bytes)  # byte-for-byte copy; the original is never opened for write
        executable = work_dir / "simulation.out"
        phase = "compile"
        try:
            compiled = subprocess.run(
                # Relative paths keep vvp's "$finish called" lines independent of the temp dir name.
                [self.iverilog, "-g2012", "-s", self.tb_top, "-o", executable.name,
                 candidate.name, local_tb.name], cwd=work_dir, env=sim_env(),
                text=True, errors="replace", capture_output=True, timeout=timeout_s, check=False,
            )
            self._save_log(work_dir, "compile", compiled.stdout + compiled.stderr)
            if compiled.returncode != 0:
                # Uncompilable RTL is invalid-mutant evidence, never behavioral evidence.
                return self._record(work_dir, "COMPILE_FAILURE",
                                    TbResult(Verdict.NOT_RUNNABLE, "compile"),
                                    compile_rc=compiled.returncode,
                                    compile_stderr_head=compiled.stderr[:300], **base)
            phase = "simulate"
            ran = subprocess.run([self.vvp, executable.name], cwd=work_dir, env=sim_env(),
                                 text=True, errors="replace", capture_output=True,
                                 timeout=timeout_s, check=False)
            self._save_log(work_dir, "simulation", ran.stdout + ran.stderr)
        except subprocess.TimeoutExpired:
            return self._record(work_dir, "TIMEOUT", TbResult(Verdict.TIMEOUT, None),
                                timeout_phase=phase, timeout_s=timeout_s, **base)
        except OSError as exc:
            return self._record(work_dir, "SETUP_ERROR_SIMULATOR_UNAVAILABLE",
                                TbResult(Verdict.NOT_RUNNABLE, None), error=str(exc), **base)
        base.update(sim_rc=ran.returncode, wall_s=round(time.monotonic() - started, 3),
                    sim_stdout_sha256=sha256(ran.stdout.encode("utf-8")))
        return self._classify(work_dir, ran, base)

    def _classify(self, work_dir: Path, ran: subprocess.CompletedProcess, base: dict) -> TbResult:
        # ArchXBench includes an explicit JSON summary line. A zero exit code or casual
        # PASS text alone is NEVER a successful baseline.
        summaries = []
        for line in ran.stdout.splitlines():
            if line.strip().startswith('{"module":'):
                try:
                    summaries.append(json.loads(line))
                except json.JSONDecodeError:
                    return self._record(work_dir, "MALFORMED_SUMMARY",
                                        TbResult(Verdict.NOT_RUNNABLE, None), **base)
        if len(summaries) != 1 or not isinstance(summaries[0], dict):
            return self._record(work_dir, "MALFORMED_SUMMARY",
                                TbResult(Verdict.NOT_RUNNABLE, None),
                                summary_lines=len(summaries), **base)
        summary = summaries[0]
        if (summary.get("module") != self.summary_module
                or type(summary.get("passed")) is not int
                or type(summary.get("failed")) is not int
                or summary["passed"] < 0 or summary["failed"] < 0):
            return self._record(work_dir, "MALFORMED_SUMMARY",
                                TbResult(Verdict.NOT_RUNNABLE, None), summary=summary, **base)
        total = summary["passed"] + summary["failed"]
        base.update(summary={"passed": summary["passed"], "failed": summary["failed"]},
                    fail_lines=[x for x in ran.stdout.splitlines() if x.startswith("[FAIL]")][:5])
        if self.expected_total is not None and total != self.expected_total:
            return self._record(work_dir, "CHECK_COUNT_MISMATCH",
                                TbResult(Verdict.NOT_RUNNABLE, None),
                                expected_total=self.expected_total, **base)
        if summary["failed"] > 0:
            return self._record(work_dir, "TB_FAIL", TbResult(Verdict.FAIL, "tb"), **base)
        if ran.returncode == 0 and summary["passed"] > 0:
            if self.expected_total is None:
                self.expected_total = total
            return self._record(work_dir, "PASS", TbResult(Verdict.PASS, None), **base)
        return self._record(work_dir, "NONZERO_EXIT_WITHOUT_FAILURES",
                            TbResult(Verdict.NOT_RUNNABLE, None), **base)


def tool_version(cmd: str, flag: str) -> str:
    out = subprocess.run([cmd, flag], capture_output=True, text=True, check=True, env=sim_env())
    return (out.stdout or out.stderr).splitlines()[0]


def verify_vendor(vendor_root: Path, expected_sha: str, task_path: str) -> tuple[str, Path]:
    """Return (commit, testbench path) after proving the testbench is pristine upstream."""
    # safe.directory: the read-only bind mount is owned by a different uid than the container user.
    git = ["git", "-c", f"safe.directory={vendor_root}", "-C", str(vendor_root)]
    probe = subprocess.run(git + ["rev-parse", "HEAD"], text=True, capture_output=True)
    if probe.returncode != 0:
        raise SystemExit(f"cannot read vendor git state: {probe.stderr.strip()}")
    actual = probe.stdout.strip()
    if actual != expected_sha:
        raise SystemExit(f"vendor SHA mismatch: {actual} != {expected_sha}")
    tb = under(vendor_root, f"{task_path}/tb.v")
    rel = tb.relative_to(vendor_root.resolve()).as_posix()
    dirty = subprocess.run(git + ["status", "--porcelain", "--", rel], text=True,
                           capture_output=True, check=True).stdout.strip()
    committed = subprocess.run(git + ["cat-file", "blob", f"HEAD:{rel}"], capture_output=True,
                               check=True).stdout
    if dirty or committed != tb.read_bytes():
        raise SystemExit(f"testbench differs from pinned upstream blob (CRLF conversion or edit?): {rel}")
    return actual, tb


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
    parser.add_argument("--analysis-out", type=Path,
                        help="separate per-mutant analysis with explicit outcome categories")
    parser.add_argument("--log-dir", type=Path)
    parser.add_argument("--seed", type=int, default=20260729)
    parser.add_argument("--iverilog", default="iverilog")
    parser.add_argument("--vvp", default="vvp")
    parser.add_argument("--yosys", default="yosys")
    parser.add_argument("--sby", default="sby")
    parser.add_argument("--summary-module", help="module name printed in the testbench JSON summary "
                                                 "(default: --module)")
    parser.add_argument("--operators", choices=["v1", "v2"], default="v1",
                        help="v1 = GateTruth harness operators unchanged; v2 = + pilot operator set "
                             "(external-audit/archxbench_ops_v2.py)")
    a = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", a.design_id):
        parser.error("design-id must be a safe single token")
    if not re.fullmatch(r"[0-9a-f]{40}", a.expected_vendor_sha):
        parser.error("expected-vendor-sha must be the full 40-character commit")
    for exe in (a.iverilog, a.vvp):
        if shutil.which(exe) is None:
            print(f"SETUP_ERROR: simulator executable not found: {exe}", file=sys.stderr)
            return 3
    vendor_commit, tb = verify_vendor(a.vendor_root.resolve(), a.expected_vendor_sha, a.task_path)
    source = a.reference.read_text(encoding="utf-8")
    if not source.strip():
        parser.error("empty reference RTL")
    versions = {"python": platform.python_version(),
                "iverilog": tool_version(a.iverilog, "-V"), "vvp": tool_version(a.vvp, "-V")}
    runner = ArchXBenchRunner(tb, a.module, a.tb_top, a.iverilog, a.vvp, a.log_dir, a.summary_module)
    catalog = {
        "_golden_source": source,
        "_vendor_commit": vendor_commit,
        "_tool_versions": versions,
        "reference_sha256": sha256(source.encode()),
        "testbench_sha256": sha256(tb.read_bytes()),
        "notes": "Pilot; evaluator-supplied reference, not ArchXBench-issued golden RTL",
    }
    started = time.monotonic()
    generator = None
    if a.operators == "v2":
        from archxbench_ops_v2 import generate_mutants_v2 as generator
    report = audit_design(a.design_id, runner, a.seed, catalog, generation_flag="-g2012",
                          mutant_generator=generator)
    wall = round(time.monotonic() - started, 3)
    compile_failed = [m["id"] for m in report["per_mutant"]
                      if runner.records.get(m["id"], {}).get("outcome") == "COMPILE_FAILURE"]
    report["adoption_pilot"] = {
        "target_commit": vendor_commit,
        "reference_origin": a.reference.name,
        "evaluator_reference_not_upstream_golden": True,
        "compile_failed_mutants_not_behavioral_evidence": compile_failed,
        "behavioral_kills": sum(m["verdict"] == "killed" and m["killed_by"] == "tb"
                                for m in report["per_mutant"]),
        "mutant_equivalence_checked": a.analysis_out is not None,
        "requires_independent_validation": True,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if a.analysis_out is not None:
        import archxbench_analysis
        analysis = archxbench_analysis.analyze_design(
            report=report, records=runner.records, reference_path=a.reference,
            source=source, module=a.module, design_id=a.design_id, iverilog=a.iverilog,
            vvp=a.vvp, yosys=a.yosys, wall_s=wall, sby=a.sby, mutant_generator=generator,
            operators_label=a.operators)
        a.analysis_out.parent.mkdir(parents=True, exist_ok=True)
        a.analysis_out.write_text(json.dumps(analysis, indent=2, sort_keys=True) + "\n")
        print(f"design={a.design_id} category_counts={analysis['summary']['category_counts']}")
    print(f"status={report['status']} mutants={report['mutants_total']} "
          f"behavioral_kills={report['adoption_pilot']['behavioral_kills']} "
          f"compile_failures={len(compile_failed)}")
    return 0 if report["status"] == "audited" else 2


if __name__ == "__main__":
    raise SystemExit(main())
