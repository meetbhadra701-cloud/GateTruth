"""Inventory and baseline-check the pinned RTLLM v2.0 suite under Icarus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from fetch_vendor import AUDIT_ROOT, LOCK_PATH, tree_hash

IVERILOG = "/opt/iverilog/bin/iverilog"
VVP = "/opt/iverilog/bin/vvp"
EXPECTED_DESIGNS = 50
PASS_RE = re.compile(r"Your\s+Design\s+Passed", re.IGNORECASE)
MODULE_RE = re.compile(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)")
SUPPORT_FILE_RE = re.compile(r'"([^"\n]+\.(?:dat|hex|mem|txt))"', re.IGNORECASE)
MISSING_MODULE_RE = re.compile(r"Unknown module type:\s*([A-Za-z_][A-Za-z0-9_$]*)")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_vendor_record() -> dict[str, Any]:
    raw = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    return dict(raw["vendors"]["rtllm"])


def _normalize_output(output: str, vendor: Path) -> str:
    return output.replace(str(vendor), "<vendor>").replace(vendor.as_posix(), "<vendor>")


def _module_names(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return MODULE_RE.findall(text)


def _reference_top_module(modules: list[str], design_id: str) -> str | None:
    for candidate in (design_id, f"verified_{design_id}"):
        if candidate in modules:
            return candidate
    verified = [module for module in modules if module.startswith("verified_")]
    if len(verified) == 1:
        return verified[0]
    return modules[0] if modules else None


def _support_files(testbench: Path) -> list[str]:
    text = testbench.read_text(encoding="utf-8", errors="replace")
    return sorted(
        {
            name
            for name in SUPPORT_FILE_RE.findall(text)
            if (testbench.parent / name).is_file()
        }
    )


def _failure_note(prefix: str, output: str, vendor: Path) -> str:
    normalized = _normalize_output(output, vendor)
    lines = [line.strip() for line in normalized.splitlines() if line.strip()]
    detail = " | ".join(lines[-3:])
    return f"{prefix}: {detail}" if detail else prefix


def discover_designs(vendor: Path) -> list[dict[str, Any]]:
    designs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for testbench in sorted(vendor.rglob("testbench.v")):
        design_id = testbench.parent.name
        if design_id in seen:
            raise ValueError(f"duplicate RTLLM design id: {design_id}")
        seen.add(design_id)
        sources = sorted(
            path
            for path in testbench.parent.glob("*.v")
            if path.name != testbench.name
        )
        designs.append(
            {
                "design_id": design_id,
                "directory": testbench.parent,
                "sources": sources,
                "testbench": testbench,
            }
        )
    if len(designs) != EXPECTED_DESIGNS:
        raise ValueError(
            f"expected {EXPECTED_DESIGNS} RTLLM designs, found {len(designs)}"
        )
    return sorted(designs, key=lambda item: item["design_id"])


def sweep_design(
    design: dict[str, Any],
    *,
    vendor: Path,
    iverilog: str,
    vvp: str,
    timeout_s: float,
) -> dict[str, Any]:
    design_id = str(design["design_id"])
    directory = Path(design["directory"])
    sources = [Path(path) for path in design["sources"]]
    testbench = Path(design["testbench"])
    relative_sources = [path.relative_to(vendor).as_posix() for path in sources]
    relative_tb = testbench.relative_to(vendor).as_posix()
    reference_modules = [
        module
        for source in sources
        for module in _module_names(source)
    ]
    testbench_modules = _module_names(testbench)
    base = {
        "compatibility": "unsupported",
        "design_id": design_id,
        "expected_design_modules": [],
        "extra_sources_needed": _support_files(testbench),
        "notes": "",
        "pass_string": None,
        "reference_sha256": (
            _sha256(sources[0]) if len(sources) == 1 else None
        ),
        "reference_modules": reference_modules,
        "reference_sources": relative_sources,
        "runnable": False,
        "testbench": relative_tb,
        "testbench_sha256": _sha256(testbench),
        "testbench_top_module": testbench_modules[0] if testbench_modules else None,
        "top_module": _reference_top_module(reference_modules, design_id),
    }
    if not sources:
        return {
            **base,
            "compatibility": "missing-reference-source",
            "notes": "no reference Verilog source found",
        }

    with tempfile.TemporaryDirectory(prefix=f"gatetruth-rtllm-{design_id}-") as temp:
        executable = Path(temp) / "sim.out"
        compile_args = [
            iverilog,
            "-g2001",
            "-o",
            str(executable),
            *(str(path) for path in sources),
            str(testbench),
        ]
        try:
            compiled = subprocess.run(
                compile_args,
                cwd=directory,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                **base,
                "compatibility": "compile-timeout",
                "notes": f"compile timeout after {timeout_s:g}s",
            }
        if compiled.returncode != 0:
            missing_modules = sorted(set(MISSING_MODULE_RE.findall(compiled.stdout)))
            compatibility = (
                "module-name-mismatch"
                if missing_modules
                else "iverilog-incompatible"
            )
            return {
                **base,
                "compatibility": compatibility,
                "expected_design_modules": missing_modules,
                "notes": _failure_note(
                    f"Icarus compile failed (exit {compiled.returncode})",
                    compiled.stdout,
                    vendor,
                ),
            }
        try:
            ran = subprocess.run(
                [vvp, str(executable)],
                cwd=directory,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return {
                **base,
                "compatibility": "simulation-timeout",
                "notes": f"simulation timeout after {timeout_s:g}s",
            }
        lines = [line.strip() for line in ran.stdout.splitlines() if line.strip()]
        pass_line = next((line for line in lines if PASS_RE.search(line)), None)
        if ran.returncode != 0:
            return {
                **base,
                "compatibility": "simulation-failed",
                "notes": _failure_note(
                    f"vvp failed (exit {ran.returncode})",
                    ran.stdout,
                    vendor,
                ),
            }
        if pass_line is None:
            return {
                **base,
                "compatibility": "no-pass-banner",
                "notes": _failure_note(
                    "simulation emitted no recognized pass banner",
                    ran.stdout,
                    vendor,
                ),
            }
        return {
            **base,
            "compatibility": "unmodified-icarus-pass",
            "notes": "baseline passed under Icarus Verilog-2001",
            "pass_string": pass_line,
            "runnable": True,
        }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vendor", type=Path, default=AUDIT_ROOT / "vendor" / "RTLLM")
    parser.add_argument("--out", type=Path, default=AUDIT_ROOT / "results" / "rtllm")
    parser.add_argument("--iverilog", default=IVERILOG)
    parser.add_argument("--vvp", default=VVP)
    parser.add_argument("--timeout-s", type=float, default=30.0)
    args = parser.parse_args(argv)

    vendor = args.vendor.resolve()
    record = _load_vendor_record()
    expected_hash = str(record["content_sha256"])
    before_hash = tree_hash(vendor)
    if before_hash != expected_hash:
        raise ValueError(
            f"RTLLM vendor hash mismatch: expected {expected_hash}, found {before_hash}"
        )

    designs = [
        sweep_design(
            design,
            vendor=vendor,
            iverilog=args.iverilog,
            vvp=args.vvp,
            timeout_s=args.timeout_s,
        )
        for design in discover_designs(vendor)
    ]
    after_hash = tree_hash(vendor)
    if after_hash != before_hash:
        raise RuntimeError(
            f"RTLLM vendor tree changed during sweep: {before_hash} -> {after_hash}"
        )
    report = {
        "benchmark": "rtllm",
        "compatibility_counts": {
            name: sum(item["compatibility"] == name for item in designs)
            for name in sorted({str(item["compatibility"]) for item in designs})
        },
        "designs": designs,
        "runnable_designs": sum(bool(item["runnable"]) for item in designs),
        "schema_version": "1.0",
        "unsupported_designs": sum(not bool(item["runnable"]) for item in designs),
        "vendor_commit": record["revision"],
        "vendor_content_sha256": before_hash,
    }
    write_json(args.out / "sweep_report.json", report)
    print(
        f"RTLLM compatibility: {report['runnable_designs']}/{len(designs)} runnable; "
        f"{report['unsupported_designs']} unsupported"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
