"""Inventory and baseline-check the pinned RTLLM v2.0 suite under Icarus.

RTLLM ships many golden files whose top module is prefixed with ``verified_``,
while each testbench instantiates the candidate contract name. The official
flow replaces that candidate file. For baseline validation, this sweep rewrites
only the top-module declaration in a temporary compile copy; the pinned vendor
tree is never modified.
"""

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


def _without_comments(text: str) -> str:
    text = re.sub(r"//[^\n]*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)


def _module_names(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return MODULE_RE.findall(_without_comments(text))


def _reference_top_module(modules: list[str], design_id: str) -> str | None:
    for candidate in (design_id, f"verified_{design_id}"):
        if candidate in modules:
            return candidate
    verified = [module for module in modules if module.startswith("verified_")]
    if len(verified) == 1:
        return verified[0]
    return modules[0] if modules else None


def _testbench_instantiates(testbench: Path, module_name: str) -> bool:
    text = _without_comments(
        testbench.read_text(encoding="utf-8", errors="replace")
    )
    instance_start = re.compile(
        rf"(?m)^[ \t]*{re.escape(module_name)}[ \t]*"
        rf"(?:#[ \t]*\(|[A-Za-z_][A-Za-z0-9_$]*[ \t]*\()"
    )
    return instance_start.search(text) is not None


def _rewrite_module_declaration(
    source: Path,
    *,
    actual_module: str,
    expected_module: str,
) -> str:
    text = source.read_text(encoding="utf-8")
    declaration = re.compile(
        rf"(?m)^([ \t]*module[ \t]+){re.escape(actual_module)}"
        rf"(?=\s*(?:#|\(|;))"
    )
    # Count matches uncapped first: subn(..., count=1) can only ever report 0 or 1
    # replacements regardless of how many declarations actually exist in the source,
    # so checking `replacements != 1` against a count=1 call can catch a missing
    # declaration but can never catch a duplicate one -- it silently rewrites the
    # first match and reports success either way.
    match_count = len(declaration.findall(text))
    if match_count != 1:
        raise ValueError(
            f"{source}: expected one declaration for module {actual_module}, "
            f"found {match_count}"
        )
    rewritten = declaration.sub(rf"\g<1>{expected_module}", text, count=1)
    return rewritten


def _prepare_compile_sources(
    sources: list[Path],
    *,
    design_id: str,
    testbench: Path,
    temp_root: Path,
) -> tuple[list[Path], dict[str, str] | None]:
    modules_by_source = {source: _module_names(source) for source in sources}
    modules = [
        module
        for source_modules in modules_by_source.values()
        for module in source_modules
    ]
    actual_module = _reference_top_module(modules, design_id)
    if (
        actual_module is None
        or actual_module == design_id
        or not _testbench_instantiates(testbench, design_id)
    ):
        return sources, None

    matching_sources = [
        source
        for source, source_modules in modules_by_source.items()
        if actual_module in source_modules
    ]
    if len(matching_sources) != 1:
        raise ValueError(
            f"{design_id}: expected one source declaring {actual_module}, "
            f"found {len(matching_sources)}"
        )
    target = matching_sources[0]
    aliased_root = temp_root / "aliased"
    aliased_root.mkdir()
    compile_sources: list[Path] = []
    for index, source in enumerate(sources):
        if source != target:
            compile_sources.append(source)
            continue
        temporary_source = aliased_root / f"{index}_{source.name}"
        temporary_source.write_text(
            _rewrite_module_declaration(
                source,
                actual_module=actual_module,
                expected_module=design_id,
            ),
            encoding="utf-8",
        )
        compile_sources.append(temporary_source)
    return compile_sources, {"from": actual_module, "to": design_id}


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
    generation_flag: str = "-g2001",
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
        "module_alias": None,
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
        temp_root = Path(temp)
        executable = temp_root / "sim.out"
        compile_sources, module_alias = _prepare_compile_sources(
            sources,
            design_id=design_id,
            testbench=testbench,
            temp_root=temp_root,
        )
        compile_base = {**base, "module_alias": module_alias}
        compile_args = [
            iverilog,
            generation_flag,
            "-I",
            str(directory),
            "-o",
            str(executable),
            *(str(path) for path in compile_sources),
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
                **compile_base,
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
                **compile_base,
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
                **compile_base,
                "compatibility": "simulation-timeout",
                "notes": f"simulation timeout after {timeout_s:g}s",
            }
        lines = [line.strip() for line in ran.stdout.splitlines() if line.strip()]
        pass_line = next((line for line in lines if PASS_RE.search(line)), None)
        if ran.returncode != 0:
            return {
                **compile_base,
                "compatibility": "simulation-failed",
                "notes": _failure_note(
                    f"vvp failed (exit {ran.returncode})",
                    ran.stdout,
                    vendor,
                ),
            }
        if pass_line is None:
            return {
                **compile_base,
                "compatibility": "no-pass-banner",
                "notes": _failure_note(
                    "simulation emitted no recognized pass banner",
                    ran.stdout,
                    vendor,
                ),
            }
        compatibility = (
            "icarus-pass-with-module-alias"
            if module_alias is not None
            else "unmodified-icarus-pass"
        )
        notes = (
            f"baseline passed under Icarus {generation_flag} after temporary "
            f"module alias {module_alias['from']} -> {module_alias['to']}"
            if module_alias is not None
            else f"baseline passed under Icarus {generation_flag}"
        )
        return {
            **compile_base,
            "compatibility": compatibility,
            "notes": notes,
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
    parser.add_argument(
        "--generation-flag",
        default="-g2001",
        help="iverilog language-generation flag (e.g. -g2001, -g2012); the paper's "
        "reported primary condition is -g2012, see external-audit/results/rtllm/sweep-g2012.json",
    )
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
            generation_flag=args.generation_flag,
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
