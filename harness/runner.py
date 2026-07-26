"""Stage 0-2 runner spine for SiliconBench."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from xml.etree import ElementTree

from harness.flows import FlowError, run_power, run_sta, run_synth
from harness.hidden import (
    HIDDEN_REPORT_ENV,
    HIDDEN_ROOT_ENV,
    HiddenTestError,
    resolve_hidden_module,
)
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest import ResultManifest
from harness.schemas.task_yaml import TaskYaml, load_task_yaml
from harness.scoring import (
    PpaMetrics,
    delay_from_wns,
    load_reference_metrics,
    ppa_from_metrics,
    task_score_from_ppa,
)

SUITE_VERSION = "v0.2"
DEFAULT_DOCKER_DIGEST = "sha256:20a665db641ebf3c4dc260a30c22817611081b48a749842d38cdc38b10ad8f62"
DEFAULT_DOCKER_DIGEST_FILE = Path("/etc/siliconbench-image-digest")
REPO_ROOT = Path(__file__).resolve().parents[1]
TOY_FIXTURE_ROOT = REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_task"
HIDDEN_FAILURE_PREFIX = "official hidden-test error: "


@dataclass(frozen=True)
class TaskPackage:
    task_id: str
    root: Path
    task_yaml: TaskYaml
    top_module: str


def resolve_task(task_id: str) -> TaskPackage:
    candidates = [TOY_FIXTURE_ROOT] if task_id == "toy_task" else []
    candidates.append(REPO_ROOT / "tasks" / task_id)
    for root in candidates:
        task_yaml = root / "task.yaml"
        if task_yaml.exists():
            task = load_task_yaml(task_yaml)
            top = _find_top_module(root / "interface.sv", fallback=task.id.split("_", 1)[-1])
            return TaskPackage(task_id=task.id, root=root, task_yaml=task, top_module=top)
    raise FileNotFoundError(f"unknown task: {task_id}")


def runtime_docker_digest() -> str:
    explicit = os.environ.get("SILICONBENCH_DOCKER_DIGEST")
    if explicit:
        return explicit
    path = Path(os.environ.get("SILICONBENCH_DOCKER_DIGEST_FILE", DEFAULT_DOCKER_DIGEST_FILE))
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return DEFAULT_DOCKER_DIGEST


def _find_top_module(path: Path, fallback: str) -> str:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        # Strip comments first so prose like "declare a module named `foo`" cannot be mistaken for the
        # module declaration (that would capture "named"). Match the real `module <name>` afterwards.
        text = re.sub(r"//[^\n]*", "", text)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        match = re.search(r"\bmodule\s+([A-Za-z_][A-Za-z0-9_$]*)", text)
        if match:
            return match.group(1)
    return fallback


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout_s: float | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            args,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(args, 124, stdout + f"\nTIMEOUT after {timeout_s} seconds\n")


def run_lint(submission: Path) -> tuple[dict[str, object], str]:
    result = _run(["verilator", "--lint-only", "--sv", str(submission)], timeout_s=30)
    if result.returncode == 0:
        return {"stage": 0, "name": "lint", "status": "pass", "warnings": 0}, result.stdout
    return {"stage": 0, "name": "lint", "status": "fail"}, result.stdout


def run_sim(
    task: TaskPackage,
    submission: Path,
    work_root: Path,
    *,
    timeout_s: float = 20,
    official: bool = False,
) -> tuple[dict[str, object], str]:
    env = os.environ.copy()
    hidden_report = work_root / "hidden-load.json"
    hidden_error = _configure_hidden_run(
        task,
        official=official,
        env=env,
        report_path=hidden_report,
    )
    if hidden_error is not None:
        return {"stage": 1, "name": "sim", "status": "fail"}, hidden_error

    script = work_root / "run_cocotb.py"
    build_dir = work_root / "sim_build"
    results_xml = work_root / "results.xml"
    test_module = _test_module_name(task)
    script.write_text(
        "from cocotb.runner import get_runner\n"
        "runner = get_runner('icarus')\n"
        f"runner.build(sources=[r'{submission.as_posix()}'], hdl_toplevel='{task.top_module}', "
        f"build_args=['-g2012'], build_dir=r'{build_dir.as_posix()}', always=True, "
        "timescale=('1ns','1ps'))\n"
        f"runner.test(hdl_toplevel='{task.top_module}', test_module='{test_module}', "
        f"build_dir=r'{build_dir.as_posix()}', test_dir=r'{(task.root / 'tb').as_posix()}', "
        f"results_xml=r'{results_xml.as_posix()}', timescale=('1ns','1ps'))\n",
        encoding="utf-8",
    )
    env.pop("PYTEST_CURRENT_TEST", None)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), str(task.root / "tb"), env.get("PYTHONPATH", "")])
    result = _run([sys.executable, str(script)], cwd=REPO_ROOT, env=env, timeout_s=timeout_s)
    hidden_error = _validate_hidden_report(
        task,
        official=official,
        report_path=hidden_report,
    )
    output = result.stdout
    if hidden_error is not None:
        output = output.rstrip() + "\n" + hidden_error
    if result.returncode != 0:
        return {"stage": 1, "name": "sim", "status": "fail"}, output
    if hidden_error is not None:
        return {"stage": 1, "name": "sim", "status": "fail"}, output
    tests_run, tests_passed = _parse_cocotb_results(results_xml)
    if tests_passed != tests_run:
        return {"stage": 1, "name": "sim", "status": "fail"}, output
    return {"stage": 1, "name": "sim", "status": "pass", "tests_run": tests_run, "tests_passed": tests_passed}, output


def _hidden_kind(task: TaskPackage) -> str | None:
    kind = task.root.parent.name
    return kind if kind in {"tasks", "tasksB"} else None


def official_hidden_preflight(
    task: TaskPackage,
    *,
    official: bool,
    env: dict[str, str] | None = None,
) -> str | None:
    """Return a fail-closed setup error before an official task starts."""

    kind = _hidden_kind(task)
    if not official or kind is None:
        return None
    environment = os.environ if env is None else env
    root = environment.get(HIDDEN_ROOT_ENV)
    if not root:
        return (
            f"{HIDDEN_FAILURE_PREFIX}{HIDDEN_ROOT_ENV} is required for "
            f"registered task {task.task_id}\n"
        )
    try:
        resolve_hidden_module(root, task.task_id, kind=kind)
    except HiddenTestError as exc:
        return f"{HIDDEN_FAILURE_PREFIX}{exc}\n"
    return None


def _configure_hidden_run(
    task: TaskPackage,
    *,
    official: bool,
    env: dict[str, str],
    report_path: Path,
) -> str | None:
    kind = _hidden_kind(task)
    error = official_hidden_preflight(task, official=official, env=env)
    if error is not None or kind is None:
        return error
    env[HIDDEN_REPORT_ENV] = str(report_path)
    return None


def _validate_hidden_report(
    task: TaskPackage,
    *,
    official: bool,
    report_path: Path,
) -> str | None:
    kind = _hidden_kind(task)
    if not official or kind is None:
        return None
    if not report_path.is_file():
        return (
            f"{HIDDEN_FAILURE_PREFIX}loader did not report hidden tests for "
            f"{task.task_id}\n"
        )
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"{HIDDEN_FAILURE_PREFIX}invalid loader report: {exc}\n"
    count = report.get("count")
    if (
        report.get("task_id") != task.task_id
        or report.get("kind") != kind
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
    ):
        return (
            f"{HIDDEN_FAILURE_PREFIX}invalid loader report for {task.task_id}: "
            f"{report!r}\n"
        )
    return None


def _test_module_name(task: TaskPackage) -> str:
    tests = sorted((task.root / "tb").glob("test_*.py"))
    if not tests:
        raise FileNotFoundError(f"no cocotb test_*.py found in {task.root / 'tb'}")
    return tests[0].stem


def _parse_cocotb_results(path: Path) -> tuple[int, int]:
    tree = ElementTree.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if suites:
        tests = sum(int(suite.attrib.get("tests", "0")) for suite in suites)
        failures = sum(
            int(suite.attrib.get("failures", "0")) + int(suite.attrib.get("errors", "0"))
            for suite in suites
        )
    else:
        tests = int(root.attrib.get("tests", "0"))
        failures = int(root.attrib.get("failures", "0")) + int(root.attrib.get("errors", "0"))
    if tests == 0:
        testcases = list(root.iter("testcase"))
        tests = len(testcases)
        failures = sum(1 for testcase in testcases if testcase.find("failure") is not None or testcase.find("error") is not None)
    return tests, tests - failures


def run_formal(task: TaskPackage, submission: Path, work_root: Path) -> tuple[dict[str, object], str]:
    if not task.task_yaml.formal:
        return {"stage": 2, "name": "formal", "status": "skip"}, "formal skipped by task.yaml\n"
    formal_dir = task.root / "formal"
    props = formal_dir / "props.sby"
    if not props.exists():
        return {"stage": 2, "name": "formal", "status": "fail"}, f"missing {props}\n"
    local_root = work_root / "formal_task"
    local_formal = local_root / "formal"
    local_ref = local_root / "ref"
    shutil.copytree(formal_dir, local_formal)
    local_ref.mkdir(parents=True)
    shutil.copy2(submission, local_ref / "ref.sv")
    result = _run(["sby", "-f", "props.sby"], cwd=local_formal, timeout_s=60)
    if result.returncode == 0:
        return {"stage": 2, "name": "formal", "status": "pass"}, result.stdout
    return {"stage": 2, "name": "formal", "status": "fail"}, result.stdout


def run_ppa_flows(task: TaskPackage, submission: Path, work_root: Path) -> tuple[list[dict[str, object]], str]:
    constraints = task.root / "constraints.sdc"
    try:
        synth = run_synth(
            submission=submission,
            top_module=task.top_module,
            clock_target_ns=task.task_yaml.clock_target_ns,
            work_root=work_root,
        )
        sta = run_sta(
            netlist=synth.netlist,
            top_module=task.top_module,
            constraints=constraints,
            clock_target_ns=task.task_yaml.clock_target_ns,
        )
        power = run_power(netlist=synth.netlist, top_module=task.top_module, constraints=constraints)
    except FlowError as exc:
        return [
            {"stage": 3, "name": "synth", "status": "fail"},
            {"stage": 4, "name": "sta", "status": "fail"},
            {"stage": 5, "name": "power", "status": "fail"},
        ], str(exc)

    synth_pass = (
        math.isfinite(synth.area_um2)
        and synth.area_um2 > 0
        and synth.cell_count >= 0
    )
    try:
        delay_from_wns(task.task_yaml.clock_target_ns, sta.wns_ns)
        sta_metrics_valid = (
            math.isfinite(sta.tns_ns)
            and math.isfinite(sta.fmax_mhz)
            and sta.fmax_mhz > 0
        )
    except ValueError:
        sta_metrics_valid = False
    sta_pass = sta_metrics_valid and sta.wns_ns >= 0.0
    power_pass = math.isfinite(power.power_mw) and power.power_mw > 0

    synth_stage: dict[str, object] = {
        "stage": 3,
        "name": "synth",
        "status": "pass" if synth_pass else "fail",
    }
    if synth_pass:
        synth_stage.update(
            {
                "area_um2": synth.area_um2,
                "cell_count": synth.cell_count,
            }
        )
    sta_stage: dict[str, object] = {
        "stage": 4,
        "name": "sta",
        "status": "pass" if sta_pass else "fail",
    }
    if sta_pass:
        sta_stage.update(
            {
                "wns_ns": sta.wns_ns,
                "tns_ns": sta.tns_ns,
                "fmax_mhz": sta.fmax_mhz,
            }
        )
    power_stage: dict[str, object] = {
        "stage": 5,
        "name": "power",
        "status": "pass" if power_pass else "fail",
    }
    if power_pass:
        power_stage["power_mw"] = power.power_mw

    invalid: list[str] = []
    if not synth_pass:
        invalid.append("synth area/cell count")
    if not sta_metrics_valid:
        invalid.append("STA delay/frequency")
    if not power_pass:
        invalid.append("power")
    logs = [synth.log, sta.log, power.log]
    if invalid:
        logs.append(f"invalid scoring metric: {', '.join(invalid)}\n")

    stages: list[dict[str, object]] = [
        synth_stage,
        sta_stage,
        power_stage,
    ]
    return stages, "\n\n".join(logs)


def run_task(
    task_id: str,
    submission: str | Path,
    out: str | Path,
    *,
    official: bool = False,
) -> ResultManifest:
    task = resolve_task(task_id)
    submission_path = Path(submission).resolve()
    start = time.perf_counter()
    logs: list[str] = []
    with tempfile.TemporaryDirectory(prefix="siliconbench-") as temp:
        work_root = Path(temp)
        stages = []
        stage, log = run_lint(submission_path)
        stages.append(stage)
        logs.append(log)
        if stage["status"] == "pass":
            stage, log = run_sim(
                task,
                submission_path,
                work_root,
                official=official,
            )
            stages.append(stage)
            logs.append(log)
        else:
            stages.append({"stage": 1, "name": "sim", "status": "fail"})
        if stages[-1]["status"] == "pass":
            stage, log = run_formal(task, submission_path, work_root)
            stages.append(stage)
            logs.append(log)
        else:
            stages.append({"stage": 2, "name": "formal", "status": "fail"})
        if all(stage["status"] in {"pass", "skip"} for stage in stages if stage["stage"] in {0, 1, 2}):
            flow_stages, log = run_ppa_flows(task, submission_path, work_root)
            stages.extend(flow_stages)
            logs.append(log)
        else:
            stages.extend([
                {"stage": 3, "name": "synth", "status": "fail"},
                {"stage": 4, "name": "sta", "status": "fail"},
                {"stage": 5, "name": "power", "status": "fail"},
            ])

    correctness_pass = all(stage["status"] in {"pass", "skip"} for stage in stages if stage["stage"] in {0, 1, 2})
    ppa_pass = all(stage["status"] == "pass" for stage in stages if stage["stage"] in {3, 4, 5})
    if correctness_pass and ppa_pass:
        by_stage = {stage["stage"]: stage for stage in stages}
        measured = PpaMetrics(
            area_um2=float(by_stage[3]["area_um2"]),
            delay_ns=delay_from_wns(
                task.task_yaml.clock_target_ns,
                float(by_stage[4]["wns_ns"]),
            ),
            power_mw=float(by_stage[5]["power_mw"]),
            clock_target_ns=task.task_yaml.clock_target_ns,
        )
        reference = load_reference_metrics(task.task_id)
        ppa = ppa_from_metrics(reference, measured)
        task_score = task_score_from_ppa(ppa)
    else:
        ppa = 0.0
        task_score = 0.0
    stages.append({"stage": 6, "name": "route", "status": "skip"})
    data = {
        "task_id": task.task_id,
        "suite_version": SUITE_VERSION,
        "docker_digest": runtime_docker_digest(),
        "platform": "linux/amd64",
        "stages": stages,
        "sec": 1.0,
        "ppa": ppa,
        "task_score": task_score,
        "wall_clock_s": round(time.perf_counter() - start, 6),
        "provider": "local",
        "model": "submission",
        "temperature": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signature": "0" * 64,
    }
    data["signature"] = compute_manifest_signature(data)
    manifest = ResultManifest.model_validate(data)
    output_path = Path(out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(manifest.model_dump(mode="json", exclude_none=True), indent=2) + "\n",
        encoding="utf-8",
    )
    log_path = output_path.with_suffix(".log")
    log_path.write_text("\n\n".join(logs), encoding="utf-8")
    return manifest
