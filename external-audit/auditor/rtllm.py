"""RTLLM v2.0 testbench adapter using the pinned Icarus toolchain."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from sweep_rtllm import _rewrite_module_declaration

from .protocol import TbResult, Verdict

IVERILOG = "/opt/iverilog/bin/iverilog"
VVP = "/opt/iverilog/bin/vvp"


class RTLLMIcarusRunner:
    suite = "rtllm"

    def __init__(
        self,
        vendor_root: Path,
        catalog: dict[str, dict[str, Any]],
        *,
        iverilog: str = IVERILOG,
        vvp: str = VVP,
    ) -> None:
        self.vendor_root = vendor_root.resolve()
        self.catalog = catalog
        self.iverilog = iverilog
        self.vvp = vvp

    def _vendor_file(self, relative: str) -> Path:
        candidate = (self.vendor_root / relative).resolve()
        try:
            candidate.relative_to(self.vendor_root)
        except ValueError as exc:
            raise ValueError(f"vendor path escapes root: {relative}") from exc
        if not candidate.is_file():
            raise ValueError(f"vendor file is missing: {relative}")
        return candidate

    def _copy_support_files(
        self,
        entry: dict[str, Any],
        testbench_source: Path,
        work_dir: Path,
    ) -> None:
        for relative in entry.get("extra_sources_needed", []):
            if not isinstance(relative, str):
                raise ValueError("RTLLM support-file path is not a string")
            source = (testbench_source.parent / relative).resolve()
            try:
                source.relative_to(self.vendor_root)
            except ValueError as exc:
                raise ValueError(
                    f"support-file path escapes vendor root: {relative}"
                ) from exc
            if not source.is_file():
                raise ValueError(f"RTLLM support file is missing: {relative}")
            destination = (work_dir / relative).resolve()
            try:
                destination.relative_to(work_dir.resolve())
            except ValueError as exc:
                raise ValueError(
                    f"support-file destination escapes work dir: {relative}"
                ) from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    def _candidate_source(
        self,
        design_id: str,
        rtl_source: str,
        entry: dict[str, Any],
        work_dir: Path,
    ) -> Path:
        candidate = work_dir / f"{design_id}.v"
        candidate.write_text(rtl_source, encoding="utf-8")
        alias = entry.get("module_alias")
        if alias is None:
            return candidate
        if not isinstance(alias, dict):
            raise ValueError(f"{design_id}: invalid module_alias catalog entry")
        actual = alias.get("from")
        expected = alias.get("to")
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise ValueError(f"{design_id}: invalid module_alias names")
        candidate.write_text(
            _rewrite_module_declaration(
                candidate,
                actual_module=actual,
                expected_module=expected,
            ),
            encoding="utf-8",
        )
        return candidate

    def run(
        self,
        design_id: str,
        rtl_source: str,
        work_dir: Path,
        *,
        timeout_s: float,
    ) -> TbResult:
        entry = self.catalog.get(design_id)
        if entry is None or not entry.get("runnable", False):
            return TbResult(Verdict.NOT_RUNNABLE, None)

        work_dir.mkdir(parents=True, exist_ok=False)
        testbench_source = self._vendor_file(str(entry["testbench"]))
        testbench = work_dir / "testbench.v"
        shutil.copy2(testbench_source, testbench)
        self._copy_support_files(entry, testbench_source, work_dir)

        try:
            candidate = self._candidate_source(
                design_id,
                rtl_source,
                entry,
                work_dir,
            )
        except ValueError:
            return TbResult(Verdict.FAIL, "compile")

        compile_sources = [candidate]
        reference_sources = entry.get("reference_sources", [])
        for index, relative in enumerate(reference_sources[1:], start=1):
            source = self._vendor_file(str(relative))
            destination = work_dir / f"extra_{index}_{source.name}"
            shutil.copy2(source, destination)
            compile_sources.append(destination)

        executable = work_dir / "sim.out"
        compile_args = [
            self.iverilog,
            "-g2001",
            "-I",
            str(testbench_source.parent),
            "-o",
            str(executable),
            *(str(source) for source in compile_sources),
            str(testbench),
        ]
        try:
            compiled = subprocess.run(
                compile_args,
                cwd=work_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return TbResult(Verdict.TIMEOUT, None)
        if compiled.returncode != 0:
            return TbResult(Verdict.FAIL, "compile")

        try:
            ran = subprocess.run(
                [self.vvp, str(executable)],
                cwd=work_dir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return TbResult(Verdict.TIMEOUT, None)
        pass_string = entry.get("pass_string")
        passed = (
            ran.returncode == 0
            and isinstance(pass_string, str)
            and pass_string in {line.strip() for line in ran.stdout.splitlines()}
        )
        if passed:
            return TbResult(Verdict.PASS, None)
        return TbResult(Verdict.FAIL, "tb")
