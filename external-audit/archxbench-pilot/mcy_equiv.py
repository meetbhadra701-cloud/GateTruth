"""Equivalence verdict for one MCY mutation (called from the MCY test script).

Prints exactly one word on stdout: EQUIVALENT, DIFFERENT or UNKNOWN. Uses the same evidence rules as
archxbench_analysis (combinational: exhaustive simulation over legal inputs + Yosys miter;
sequential: trace comparison + unbounded SBY proof).
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(AUDIT), str(AUDIT.parent)]

import archxbench_analysis as analysis  # noqa: E402
import archxbench_formal as formal  # noqa: E402
from archxbench_oracles import SPECS, is_sequential  # noqa: E402


def verdict(reference: str, mutated: str, module: str) -> str:
    sequential = is_sequential(module)
    with tempfile.TemporaryDirectory(prefix="gt-mcyeq-") as tmp:
        work = Path(tmp)
        ref_rows = formal.behavior_rows("iverilog", "vvp", reference, module, work / "ref")
        mut_rows = formal.behavior_rows("iverilog", "vvp", mutated, module, work / "mut")
        if ref_rows is None or mut_rows is None:
            return "UNKNOWN"
        if sequential:
            proof = formal.sby_equivalence("sby", reference, mutated, module, work / "sby")
        elif "legal" in SPECS[module]:
            proof = "n/a-legal-assumption"
        else:
            proof = analysis.yosys_equivalence("yosys", reference, mutated, module, work / "ys")
        if ref_rows != mut_rows or proof == "different":
            # a concrete simulated difference contradicted by a proof means the tools disagree
            return "UNKNOWN" if proof == "equivalent" else "DIFFERENT"
        if proof in ("equivalent", "n/a-legal-assumption"):
            return "EQUIVALENT"
        return "UNKNOWN"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reference", required=True, type=Path)
    ap.add_argument("--mutated", required=True, type=Path)
    ap.add_argument("--module", required=True)
    a = ap.parse_args()
    print(verdict(a.reference.read_text(encoding="utf-8"), a.mutated.read_text(encoding="utf-8"), a.module))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
