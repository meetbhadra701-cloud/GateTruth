"""Deterministic stage 3-5 sky130hd flow helpers."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FLOWS_ROOT = REPO_ROOT / "flows"
DEFAULT_LIBERTY = Path("/pdk/sky130hd/sky130_fd_sc_hd__tt_025C_1v80.lib")
YOSYS_BIN = "/opt/oss-cad-suite/bin/yosys"
OPENSTA_BIN = "/usr/bin/sta"
SYNTH_TIMEOUT_S = 120.0
STA_TIMEOUT_S = 120.0
POWER_TIMEOUT_S = 120.0
_CHILD_ENV_ALLOWLIST = (
    "HOME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "PATH",
    "SYSTEMROOT",
    "TEMP",
    "TMP",
    "TMPDIR",
)


@dataclass(frozen=True)
class SynthResult:
    netlist: Path
    area_um2: float
    cell_count: int
    log: str


@dataclass(frozen=True)
class StaResult:
    wns_ns: float
    tns_ns: float
    fmax_mhz: float
    log: str


@dataclass(frozen=True)
class PowerResult:
    power_mw: float
    log: str


def run_synth(
    *,
    submission: Path,
    top_module: str,
    clock_target_ns: float,
    work_root: Path,
    liberty: Path = DEFAULT_LIBERTY,
    timeout_s: float = SYNTH_TIMEOUT_S,
) -> SynthResult:
    netlist = work_root / "synth_netlist.v"
    report = work_root / "synth_stat.rpt"
    script = work_root / "synth_sky130.ys"
    clock_ps = int(round(clock_target_ns * 1000.0))
    template = (FLOWS_ROOT / "synth_sky130.ys").read_text(encoding="utf-8")
    script.write_text(
        template.replace("{{SUBMISSION}}", _yosys_path(submission))
        .replace("{{TOP}}", top_module)
        .replace("{{LIBERTY}}", _yosys_path(liberty))
        .replace("{{CLOCK_PS}}", str(clock_ps))
        .replace("{{REPORT}}", _yosys_path(report))
        .replace("{{NETLIST}}", _yosys_path(netlist)),
        encoding="utf-8",
    )
    result = _run([YOSYS_BIN, "-s", str(script)], timeout_s=timeout_s)
    if result.returncode != 0:
        raise FlowError(_failure_message("synth", result, timeout_s))
    report_text = report.read_text(encoding="utf-8")
    return SynthResult(
        netlist=netlist,
        area_um2=_parse_area(report_text, top_module),
        cell_count=_parse_cell_count(report_text),
        log=result.stdout + "\n" + report_text,
    )


def run_sta(
    *,
    netlist: Path,
    top_module: str,
    constraints: Path,
    clock_target_ns: float,
    liberty: Path = DEFAULT_LIBERTY,
    timeout_s: float = STA_TIMEOUT_S,
) -> StaResult:
    env = _sta_env(netlist=netlist, top_module=top_module, constraints=constraints, liberty=liberty)
    result = _run(
        [OPENSTA_BIN, "-no_init", "-exit", str(FLOWS_ROOT / "sta.tcl")],
        env=env,
        timeout_s=timeout_s,
    )
    if result.returncode != 0:
        raise FlowError(_failure_message("sta", result, timeout_s))
    wns = _parse_named_float(result.stdout, "SB_WNS_NS")
    tns = _parse_named_float(result.stdout, "SB_TNS_NS")
    delay_ns = clock_target_ns - wns
    fmax_mhz = 1000.0 / delay_ns if delay_ns > 0 else 0.0
    return StaResult(wns_ns=wns, tns_ns=tns, fmax_mhz=fmax_mhz, log=result.stdout)


def run_power(
    *,
    netlist: Path,
    top_module: str,
    constraints: Path,
    liberty: Path = DEFAULT_LIBERTY,
    timeout_s: float = POWER_TIMEOUT_S,
) -> PowerResult:
    env = _sta_env(netlist=netlist, top_module=top_module, constraints=constraints, liberty=liberty)
    result = _run(
        [OPENSTA_BIN, "-no_init", "-exit", str(FLOWS_ROOT / "power.tcl")],
        env=env,
        timeout_s=timeout_s,
    )
    if result.returncode != 0:
        raise FlowError(_failure_message("power", result, timeout_s))
    return PowerResult(power_mw=_parse_power_watts(result.stdout) * 1000.0, log=result.stdout)


class FlowError(RuntimeError):
    """Raised when a deterministic flow command fails or emits unparsable output."""


def _run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    timeout_s: float,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            env=env,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(
            args,
            124,
            output + f"\nTIMEOUT after {timeout_s:g} seconds\n",
        )


def _sta_env(*, netlist: Path, top_module: str, constraints: Path, liberty: Path) -> dict[str, str]:
    env = {
        name: os.environ[name]
        for name in _CHILD_ENV_ALLOWLIST
        if name in os.environ
    }
    env.update(
        {
            "SB_LIBERTY": str(liberty),
            "SB_NETLIST": str(netlist),
            "SB_TOP": top_module,
            "SB_CONSTRAINTS": str(constraints),
        }
    )
    return env


def _failure_message(
    stage: str,
    result: subprocess.CompletedProcess[str],
    timeout_s: float,
) -> str:
    if result.returncode == 124:
        return f"{stage} timed out after {timeout_s:g} seconds\n{result.stdout}"
    return result.stdout


def _yosys_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _parse_area(report: str, top_module: str) -> float:
    escaped = re.escape("\\" + top_module)
    match = re.search(rf"Chip area for module [`']{escaped}[':]?\s*:?\s*([0-9.]+)", report)
    if not match:
        match = re.search(r"Chip area for module .*?:\s*([0-9.]+)", report)
    if not match:
        raise FlowError("could not parse chip area from yosys stat report")
    return float(match.group(1))


def _parse_cell_count(report: str) -> int:
    matches = re.findall(r"Number of cells:\s+([0-9]+)", report)
    if matches:
        return int(matches[-1])
    # Compact summary line "<count> <area> cells"; area may be scientific notation (e.g. "2.96E+03")
    # for larger designs, which the plain [0-9.]+ pattern rejected.
    compact = re.search(r"^\s*([0-9]+)\s+[0-9.eE+-]+\s+cells\s*$", report, re.MULTILINE)
    if compact:
        return int(compact.group(1))
    raise FlowError("could not parse cell count from yosys stat report")


def _parse_named_float(text: str, name: str) -> float:
    match = re.search(rf"^{name}\s+([-+0-9.eE]+)$", text, re.MULTILINE)
    if not match:
        raise FlowError(f"could not parse {name} from OpenSTA output")
    return float(match.group(1))


def _parse_power_watts(text: str) -> float:
    match = re.search(
        r"^Total\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
        text,
        re.MULTILINE,
    )
    if match:
        return float(match.group(4))
    raise FlowError("could not parse Total power from OpenSTA report_power output")
