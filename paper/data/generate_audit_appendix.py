"""Generate the per-design RTLLM audit appendix table from raw committed audit JSON.

Deliberately separate from generate_tables.py: this reads only
external-audit/results/rtllm/final-g2012/*.json and emits one LaTeX fragment. Every number in the
appendix is derived here rather than hand-typed, so the table cannot drift from the raw evidence.

Hardening beyond the raw read: every per-design file's schema_version, seed, and vendor_commit
must agree with each other and with summary.json; killed+survived+indeterminate must equal
mutants_total and kill_rate must equal the arithmetic it implies; the design set must be exactly
the 50 designs catalogued in external-audit/results/rtllm/sweep_report.json, with no missing,
extra, or duplicate entries; summary.json's status_counts must match the per-design files it
aggregates; and summary.json's tool_versions.harness_git must be a real commit, not "unavailable"
-- a run whose own provenance is unrecoverable is not evidence this appendix will accept. Notes
claiming an Icarus Verilog-2001 condition are refused outright: this directory's name is the
paper's own record that its condition is -g2012, and that mismatch is exactly the bug this check
exists to catch.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_DIR = REPO_ROOT / "external-audit" / "results" / "rtllm" / "final-g2012"
CATALOG_PATH = REPO_ROOT / "external-audit" / "results" / "rtllm" / "sweep_report.json"
OUT_PATH = REPO_ROOT / "paper" / "data" / "build" / "audit_per_design.tex"
EXPECTED_DESIGN_COUNT = 50
REQUIRED_DESIGN_FIELDS = (
    "task_id",
    "status",
    "schema_version",
    "seed",
    "vendor_commit",
    "mutants_total",
    "killed",
    "survived",
    "indeterminate",
    "kill_rate",
    "notes",
)


class AuditAppendixDataError(RuntimeError):
    """Raised when the committed audit evidence does not support this appendix."""


def _tex(value: str) -> str:
    return value.replace("_", r"\_")


def _canonical_design_ids(catalog_path: Path = CATALOG_PATH) -> frozenset[str]:
    if not catalog_path.is_file():
        raise AuditAppendixDataError(f"missing RTLLM design catalog: {catalog_path}")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    if catalog.get("benchmark") != "rtllm" or not isinstance(catalog.get("designs"), list):
        raise AuditAppendixDataError(f"{catalog_path}: not an RTLLM design catalog")
    ids = [d["design_id"] for d in catalog["designs"]]
    if len(set(ids)) != len(ids):
        raise AuditAppendixDataError(f"{catalog_path}: duplicate design_id entries")
    return frozenset(ids)


def _validate_design(data: dict, path: Path) -> None:
    missing = [field for field in REQUIRED_DESIGN_FIELDS if field not in data]
    if missing:
        raise AuditAppendixDataError(f"{path}: missing required field(s) {missing}")
    if data["status"] not in ("audited", "unsupported"):
        raise AuditAppendixDataError(f"{path}: unknown status {data['status']!r}")
    if data["killed"] + data["survived"] + data["indeterminate"] != data["mutants_total"]:
        raise AuditAppendixDataError(
            f"{path}: killed({data['killed']}) + survived({data['survived']}) + "
            f"indeterminate({data['indeterminate']}) != mutants_total({data['mutants_total']})"
        )
    if data["mutants_total"] > 0:
        expected_rate = 100.0 * data["killed"] / data["mutants_total"]
        if abs(expected_rate - data["kill_rate"]) > 0.01:
            raise AuditAppendixDataError(
                f"{path}: kill_rate {data['kill_rate']} does not match "
                f"100*killed/mutants_total ({expected_rate:.4f})"
            )
    elif data["kill_rate"] != 0.0:
        raise AuditAppendixDataError(f"{path}: mutants_total is 0 but kill_rate != 0")
    notes = data["notes"]
    if "verilog-2001" in notes.lower() or "-g2001" in notes:
        raise AuditAppendixDataError(
            f"{path}: notes describe a Verilog-2001 condition, but {AUDIT_DIR.name!r} is the "
            f"paper's committed -g2012 audit -- the note's generation flag is wrong: {notes!r}"
        )


def _validate_summary(
    summary: dict,
    *,
    audited: list[dict],
    unsupported: list[dict],
    schema_versions: set[str],
    seeds: set[int],
    vendor_commits: set[str],
    expected_count: int,
) -> None:
    if summary.get("designs_requested") != expected_count:
        raise AuditAppendixDataError(
            f"summary.json designs_requested={summary.get('designs_requested')!r}, "
            f"expected {expected_count}"
        )
    if {summary.get("schema_version")} != schema_versions:
        raise AuditAppendixDataError("summary.json schema_version disagrees with per-design files")
    if {summary.get("seed")} != seeds:
        raise AuditAppendixDataError("summary.json seed disagrees with per-design files")
    if {summary.get("vendor_commit")} != vendor_commits:
        raise AuditAppendixDataError("summary.json vendor_commit disagrees with per-design files")
    status_counts = summary.get("status_counts", {})
    if status_counts.get("audited") != len(audited) or status_counts.get("unsupported") != len(
        unsupported
    ):
        raise AuditAppendixDataError(
            f"summary.json status_counts {status_counts} does not match the per-design files "
            f"(audited={len(audited)}, unsupported={len(unsupported)})"
        )
    harness_git = summary.get("tool_versions", {}).get("harness_git")
    if not harness_git or harness_git == "unavailable":
        raise AuditAppendixDataError(
            "summary.json tool_versions.harness_git is unavailable: this run's own harness "
            "commit was not recorded, so its provenance cannot be checked. Re-run with "
            "GATETRUTH_GIT_COMMIT set (see external-audit/README.md)."
        )


def load_designs(
    audit_dir: Path = AUDIT_DIR,
    catalog_path: Path = CATALOG_PATH,
    *,
    expected_count: int = EXPECTED_DESIGN_COUNT,
) -> tuple[list[dict], list[dict]]:
    summary_path = audit_dir / "summary.json"
    if not summary_path.is_file():
        raise AuditAppendixDataError(f"missing {summary_path}")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    canonical_ids = _canonical_design_ids(catalog_path)
    if len(canonical_ids) != expected_count:
        raise AuditAppendixDataError(
            f"expected {expected_count} catalogued RTLLM designs, found {len(canonical_ids)}"
        )

    audited: list[dict] = []
    unsupported: list[dict] = []
    seen_ids: set[str] = set()
    schema_versions: set[str] = set()
    seeds: set[int] = set()
    vendor_commits: set[str] = set()

    for path in sorted(audit_dir.glob("*.json")):
        if path.name == "summary.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        _validate_design(data, path)
        design_id = data["task_id"]
        if design_id in seen_ids:
            raise AuditAppendixDataError(f"duplicate design result for {design_id}: {path}")
        seen_ids.add(design_id)
        schema_versions.add(data["schema_version"])
        seeds.add(data["seed"])
        vendor_commits.add(data["vendor_commit"])
        (audited if data["status"] == "audited" else unsupported).append(data)

    if seen_ids != canonical_ids:
        raise AuditAppendixDataError(
            f"design set mismatch: missing={sorted(canonical_ids - seen_ids)}, "
            f"extra={sorted(seen_ids - canonical_ids)}"
        )
    _validate_summary(
        summary,
        audited=audited,
        unsupported=unsupported,
        schema_versions=schema_versions,
        seeds=seeds,
        vendor_commits=vendor_commits,
        expected_count=expected_count,
    )
    return audited, unsupported


def alias_flag(notes: str) -> str:
    return "alias" if "module alias" in notes else "as shipped"


def render(
    audit_dir: Path = AUDIT_DIR,
    catalog_path: Path = CATALOG_PATH,
    *,
    expected_count: int = EXPECTED_DESIGN_COUNT,
) -> str:
    audited, unsupported = load_designs(audit_dir, catalog_path, expected_count=expected_count)
    audited.sort(key=lambda d: (d["kill_rate"], d["task_id"]))

    lines: list[str] = []
    lines.append("% generated by paper/data/generate_audit_appendix.py -- do not hand-edit")
    lines.append(r"\begin{tabular}{lrrrrrl}")
    lines.append(r"\toprule")
    lines.append(
        r"Design & Mutants & Killed & Surv. & Indet. & Kill rate & Baseline \\"
    )
    lines.append(r"\midrule")
    for d in audited:
        lines.append(
            f"\\texttt{{{_tex(d['task_id'])}}} & {d['mutants_total']} & {d['killed']} & "
            f"{d['survived']} & {d['indeterminate']} & {d['kill_rate']:.1f}\\% & "
            f"{alias_flag(d.get('notes', ''))} \\\\"
        )
    total_m = sum(d["mutants_total"] for d in audited)
    total_k = sum(d["killed"] for d in audited)
    total_s = sum(d["survived"] for d in audited)
    total_i = sum(d["indeterminate"] for d in audited)
    lines.append(r"\midrule")
    lines.append(
        f"\\textbf{{Pooled ({len(audited)} audited)}} & \\textbf{{{total_m}}} & "
        f"\\textbf{{{total_k}}} & \\textbf{{{total_s}}} & \\textbf{{{total_i}}} & "
        f"\\textbf{{{100.0 * total_k / total_m:.1f}\\%}} & \\\\"
    )
    lines.append(r"\midrule")
    lines.append(r"\multicolumn{7}{l}{\emph{Reported \texttt{unsupported}: baseline"
                 r" validation failed, excluded from all aggregates}} \\")
    for d in unsupported:
        lines.append(
            f"\\texttt{{{_tex(d['task_id'])}}} & --- & --- & --- & --- & --- & "
            r"\texttt{unsupported} \\"
        )
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        rendered = render()
        audited, unsupported = load_designs()
    except AuditAppendixDataError as exc:
        print(f"audit appendix generation refused: {exc}")
        return 2
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"audit_per_design.tex: audited={len(audited)} unsupported={len(unsupported)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
