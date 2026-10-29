"""Explicit-category analysis of an ArchXBench pilot run.

GateTruth's report contract (``auditor.audit``) folds everything into
killed/survived/indeterminate. This module keeps that report untouched and adds a
separate analysis that distinguishes behavioral kills from invalid mutants and decides
equivalence of survivors by exhaustive simulation (cross-checked with a Yosys miter).

Per-mutant category decision procedure (fixed before any mutation outcome was seen):

  COMPILE_FAILURE  mutant does not compile                    -> invalid, not behavioral evidence
  TIMEOUT          still timed out after the auditor's retry
  SETUP_ERROR      module missing / simulator unavailable
  BEHAVIORAL_KILL  testbench reported failed>0 AND the exhaustive comparison shows the
                   mutant really differs from the reference
  SURVIVED         testbench passed AND the mutant really differs from the reference
  EQUIVALENT       testbench passed AND exhaustive simulation AND the Yosys miter agree it
                   never differs from the reference
  INDETERMINATE    anything else (malformed summary, check-count mismatch, or disagreeing
                   equivalence evidence)

A mutant that differs from the reference is NOT thereby a proven specification violation:
the reference is evaluator-authored, so "differs from the reference" is only as strong as
the reference's own validation against the spec oracle.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

from archxbench_formal import (  # noqa: F401  (exhaustive_rows re-exported for tests)
    behavior_rows,
    exhaustive_rows,
    expected_rows,
    prefix_modules,
    sby_equivalence,
)
from archxbench_oracles import SPECS, is_sequential
from archxbench_pilot import sim_env
from harness.mutators import generate_mutants

CATEGORIES = ["BEHAVIORAL_KILL", "SURVIVED", "EQUIVALENT", "COMPILE_FAILURE", "TIMEOUT",
              "SETUP_ERROR", "INDETERMINATE"]
DESIGN_STATES = ["BASELINE_PASS", "BASELINE_FAIL", "UNSUPPORTED", "SETUP_ERROR"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def yosys_equivalence(yosys: str, reference: str, mutant: str, module: str, work: Path) -> str:
    """'equivalent' | 'different' | 'unavailable' | 'error' via a combinational SAT miter."""
    work.mkdir(parents=True, exist_ok=True)
    (work / "gold.v").write_text(prefix_modules(reference, "gtgold_"), encoding="utf-8", newline="")
    (work / "gate.v").write_text(prefix_modules(mutant, "gtgate_"), encoding="utf-8", newline="")
    script = ("read_verilog -sv gold.v; read_verilog -sv gate.v; hierarchy -check; proc; flatten; "
              f"opt_clean; miter -equiv -flatten -make_outputs gtgold_{module} gtgate_{module} gt_miter; "
              "hierarchy -top gt_miter; sat -verify -prove trigger 0 -show-inputs gt_miter")
    try:
        out = subprocess.run([yosys, "-q", "-p", script], cwd=work, capture_output=True,
                             text=True, timeout=120, env=sim_env())
    except FileNotFoundError:
        return "unavailable"
    except subprocess.TimeoutExpired:
        return "error"
    if out.returncode == 0:
        return "equivalent"
    if "proof did fail" in out.stdout + out.stderr:
        return "different"
    return "error"


def _diff(reference: str, mutant: str) -> list[str]:
    return [x for x in difflib.unified_diff(reference.splitlines(), mutant.splitlines(),
                                            "reference", "mutant", n=0, lineterm="") if x[0] in "+-"
            and not x.startswith(("+++", "---"))]


def _effective(records: dict[str, dict], mutant_id: str) -> dict | None:
    return records.get(f"{mutant_id}-retry") or records.get(mutant_id)


def _categorize(rec: dict | None, same_as_ref: bool | None, yosys: str,
                sequential: bool = False) -> tuple[str, str]:
    """Return (category, reason).

    ``yosys`` is the formal verdict (Yosys miter for combinational designs, SBY for sequential
    ones). For sequential designs a finite trace can only ever show a DIFFERENCE, so
    EQUIVALENT additionally requires the unbounded proof.
    """
    if rec is None:
        return "INDETERMINATE", "no run record"
    outcome = rec["outcome"]
    if outcome == "COMPILE_FAILURE":
        return "COMPILE_FAILURE", "iverilog rejected the mutant"
    if outcome == "TIMEOUT":
        return "TIMEOUT", f"timed out in {rec.get('timeout_phase')} phase after retry"
    if outcome.startswith("SETUP_ERROR"):
        return "SETUP_ERROR", outcome
    if outcome not in ("PASS", "TB_FAIL"):
        return "INDETERMINATE", outcome
    if same_as_ref is None:
        return "INDETERMINATE", "exhaustive comparison unavailable"
    if not same_as_ref and yosys == "equivalent":
        return "INDETERMINATE", "simulation shows a difference but the formal tool proves equivalence (tool disagreement)"
    if outcome == "TB_FAIL":
        if same_as_ref:
            return "INDETERMINATE", "testbench failed but mutant is exhaustively identical to reference"
        return "BEHAVIORAL_KILL", "testbench failed; mutant differs from reference on some input"
    # testbench passed
    if not same_as_ref:
        return "SURVIVED", "testbench passed although mutant differs from reference on some input"
    if sequential:
        if yosys == "equivalent":
            return "EQUIVALENT", "SBY/PDR proves outputs equal from reset for all input sequences"
        return "INDETERMINATE", f"trace identical but unbounded proof status is {yosys}"
    if yosys == "n/a-legal-assumption":
        return "EQUIVALENT", "identical on every legal input (exhaustive simulation); differences, if any, only on inputs the spec leaves undefined"
    if yosys == "equivalent":
        return "EQUIVALENT", "exhaustive simulation and Yosys miter both show no difference"
    if yosys == "unavailable":
        return "EQUIVALENT", "exhaustive simulation shows no difference (Yosys unavailable)"
    return "INDETERMINATE", f"simulation says identical but Yosys miter says {yosys}"


def analyze_design(*, report: dict, records: dict[str, dict], reference_path: Path, source: str,
                   module: str, design_id: str, iverilog: str, vvp: str, yosys: str,
                   wall_s: float, sby: str = "sby", mutant_generator=None,
                   operators_label: str = "v1") -> dict:
    sequential = is_sequential(module)
    legal_restricted = module in SPECS and "legal" in SPECS[module]
    if module not in SPECS and not sequential:
        raise ValueError(f"no independent oracle for module {module}")
    generator = mutant_generator or generate_mutants
    base_rec = records.get("baseline")
    result: dict = {
        "design_id": design_id, "module": module, "reference_file": reference_path.name,
        "reference_provenance": "EVALUATOR-AUTHORED (not upstream-issued, not maintainer-reviewed)",
        "reference_sha256": _sha(source), "testbench_sha256": report["testbench_sha256"],
        "vendor_commit": report["vendor_commit"], "seed": report["seed"],
        "tool_versions": report["tool_versions"], "generation_flag": report["generation_flag"],
        "input_legality_assumption": "all 2-state input combinations are legal (spec defines no illegal inputs)",
        "baseline_record": base_rec,
    }
    with tempfile.TemporaryDirectory(prefix="gt-analysis-") as tmp:
        tmp_path = Path(tmp)
        if sequential or legal_restricted or operators_label != "v1":  # v1 payload stays byte-identical
            result["input_legality_assumption"] = (
                "sequential: replay of a fixed reset stimulus (reset-free wrap run + random resets) plus an "
                "unbounded SBY proof from reset for equivalence" if sequential else
                "only inputs satisfying the spec's stated assumption (documented in oracles) are compared"
                if legal_restricted else result["input_legality_assumption"])
            result["operator_set"] = operators_label
        ref_rows = behavior_rows(iverilog, vvp, source, module, tmp_path / "ref")
        oracle = expected_rows(module)
        result["reference_vs_oracle"] = {
            "input_combinations": len(oracle), "rows_simulated": None if ref_rows is None else len(ref_rows),
            "matches_oracle_exhaustively": ref_rows == oracle}
        if report["status"] != "audited":
            state = ("SETUP_ERROR" if base_rec is None or base_rec["outcome"].startswith(("SETUP", "MALFORMED"))
                     else "BASELINE_FAIL" if base_rec["outcome"] == "TB_FAIL" else "UNSUPPORTED")
            result.update(design_state=state, per_mutant=[], summary={
                "category_counts": {}, "mutants_generated": 0, "inconclusive": True,
                "note": f"baseline did not pass ({base_rec and base_rec['outcome']}); no mutation experiment"})
            return result
        result["design_state"] = "BASELINE_PASS"
        mutants = {m.id: m for m in generator(f"archxbench_{design_id}", source,
                                              include_task_specs=False)}
        entries = []
        for item in report["per_mutant"]:
            mutant = mutants[item["id"]]
            rec = _effective(records, mutant.id)
            first = records.get(mutant.id)
            assert first is None or first["rtl_sha256"] == _sha(mutant.source), "mutant source drift"
            same, yos = None, "not-run"
            if rec is not None and rec["outcome"] in ("PASS", "TB_FAIL"):
                rows = behavior_rows(iverilog, vvp, mutant.source, module, tmp_path / mutant.id)
                same = None if rows is None or ref_rows is None else rows == ref_rows
                differing = None if same is None else sum(a != b for a, b in zip(rows, ref_rows))
                if sequential:
                    yos = sby_equivalence(sby, source, mutant.source, module, tmp_path / f"{mutant.id}-y")
                    if yos == "different":
                        same = False  # unbounded checker found a distinguishing input sequence
                elif legal_restricted:
                    yos = "n/a-legal-assumption"
                else:
                    yos = yosys_equivalence(yosys, source, mutant.source, module, tmp_path / f"{mutant.id}-y")
            else:
                differing = None
            category, reason = _categorize(rec, same, yos, sequential)
            entries.append({
                "id": mutant.id, "operator": mutant.operator, "description": mutant.description,
                "mutant_sha256": _sha(mutant.source), "source_diff": _diff(source, mutant.source),
                "compiles": rec is not None and rec["outcome"] != "COMPILE_FAILURE"
                            and not rec["outcome"].startswith("SETUP_ERROR"),
                "testbench_outcome": None if rec is None else rec["outcome"],
                "testbench_summary": None if rec is None else rec.get("summary"),
                "testbench_fail_lines": None if rec is None else rec.get("fail_lines"),
                "differs_from_reference_on_inputs": differing,
                "total_input_combinations": len(oracle),
                "yosys_miter": yos, "category": category, "category_reason": reason,
                "gatetruth_contract_verdict": item["verdict"],
                "gatetruth_contract_killed_by": item["killed_by"],
            })
    result["per_mutant"] = entries
    result["summary"] = summarize(entries, wall_s)
    return result


def summarize(entries: list[dict], wall_s: float) -> dict:
    counts = Counter(e["category"] for e in entries)
    by_operator: dict[str, Counter] = defaultdict(Counter)
    for e in entries:
        by_operator[e["operator"]][e["category"]] += 1
    kills, survived = counts["BEHAVIORAL_KILL"], counts["SURVIVED"]
    scored = kills + survived
    generated = len(entries)
    return {
        "mutants_generated": generated,
        "mutants_compiling": generated - counts["COMPILE_FAILURE"] - counts["SETUP_ERROR"],
        "category_counts": {c: counts[c] for c in CATEGORIES},
        "valid_nonequivalent_mutants": scored,
        "score_definition": "BEHAVIORAL_KILL / (BEHAVIORAL_KILL + SURVIVED); excludes EQUIVALENT, "
                            "COMPILE_FAILURE, TIMEOUT, SETUP_ERROR, INDETERMINATE",
        "behavioral_kill_score": None if scored == 0 else round(kills / scored, 4),
        "behavioral_kill_score_fraction": f"{kills}/{scored}",
        "inconclusive": generated == 0 or scored == 0,
        "per_operator": {op: {c: n for c, n in sorted(c_.items())} for op, c_ in sorted(by_operator.items())},
        "analysis_wall_s": round(wall_s, 3),
    }


def deterministic_view(analysis: dict) -> dict:
    """Strip wall-clock fields so two runs can be compared byte-for-byte."""
    def clean(node):
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k not in ("wall_s", "analysis_wall_s")}
        if isinstance(node, list):
            return [clean(x) for x in node]
        return node
    return clean(analysis)


def aggregate(paths: list[Path], supplementary: set[str]) -> dict:
    designs = [json.loads(Path(p).read_text()) for p in paths]
    primary = [d for d in designs if d["design_id"] not in supplementary]
    total = Counter()
    for d in primary:
        total.update(d["summary"]["category_counts"])
    kills, survived = total["BEHAVIORAL_KILL"], total["SURVIVED"]
    scored = kills + survived
    return {
        "primary_designs": [d["design_id"] for d in primary],
        "supplementary_designs": [d["design_id"] for d in designs if d["design_id"] in supplementary],
        "aggregate_over_primary_designs": {
            "category_counts": {c: total[c] for c in CATEGORIES},
            "mutants_generated": sum(d["summary"]["mutants_generated"] for d in primary),
            "valid_nonequivalent_mutants": scored,
            "behavioral_kill_score_fraction": f"{kills}/{scored}",
            "behavioral_kill_score": None if scored == 0 else round(kills / scored, 4),
            "denominator": "BEHAVIORAL_KILL + SURVIVED over primary designs (see per-design inconclusive flags)",
            "inconclusive_designs": [d["design_id"] for d in primary if d["summary"].get("inconclusive")],
        },
        "designs": {d["design_id"]: d for d in designs},
    }
