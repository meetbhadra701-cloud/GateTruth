"""Track B evaluator harness."""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from harness.atomic_write import atomic_write_text
from harness.flows import FlowError, YOSYS_BIN, run_power, run_sta, run_synth
from harness.runner import (
    HIDDEN_FAILURE_PREFIX,
    REPO_ROOT,
    SUITE_VERSION,
    TaskPackage,
    _find_top_module,
    _run,
    official_hidden_preflight,
    run_lint,
    run_sim,
    runtime_docker_digest,
)
from harness.schemas.canonical_json import compute_manifest_signature
from harness.schemas.manifest_b import TrackBManifest
from harness.validation import (
    SubmissionValidationError,
    validate_identifier,
    validate_module_declarations,
    validate_source_file,
    validate_sv_filename,
)

TRACKB_ROOT = REPO_ROOT / "tasksB"
TOY_TRACKB_ROOT = REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_taskB"
IMMUTABLE_ENTRIES = ("tb", "formal", "constraints.sdc", "task.yaml", "objective.yaml", "baseline")


@dataclass(frozen=True)
class Objective:
    task_id: str
    objective_type: str
    behavior_preserving: bool
    params: dict[str, Any]


@dataclass(frozen=True)
class TrackBPackage:
    task_id: str
    root: Path
    objective: Objective
    top_module: str
    clock_target_ns: float


def run_track_b(
    task_id: str,
    submission_dir: str | Path,
    out: str | Path,
    *,
    official: bool = False,
) -> TrackBManifest:
    package = resolve_track_b_task(task_id)
    submission_root = Path(submission_dir).resolve()
    start = time.perf_counter()
    logs: list[str] = []
    stages: list[dict[str, object]] = []
    sec = {"status": "skip", "backend": None, "seconds": None}
    ppa_delta: dict[str, Any] = _empty_ppa_delta()
    disqualified = False
    disqualification_reason = None
    objective_pass = False
    sim_task = TaskPackage(
        task_id=package.task_id,
        root=package.root,
        task_yaml=SimpleNamespace(formal=False),
        top_module=package.top_module,
    )

    reason = official_hidden_preflight(sim_task, official=official)
    if reason is None:
        try:
            reason = diff_guard(package.root, submission_root)
        except (OSError, ValueError) as exc:
            reason = f"malformed submission: {exc}"
    else:
        reason = reason.strip()
    if reason:
        disqualified = True
        disqualification_reason = reason
        stages = [
            {"stage": 0, "name": "lint", "status": "skip"},
            {"stage": 1, "name": "sim", "status": "skip"},
            {"stage": 2, "name": "correctness", "status": "skip"},
            {"stage": 3, "name": "objective", "status": "skip"},
        ]
    else:
        design = single_sv_file(submission_root / "design")
        baseline = single_sv_file(package.root / "baseline")
        import tempfile
        with tempfile.TemporaryDirectory(prefix="gatetruth-trackb-") as temp:
            work_root = Path(temp)
            safe_design = work_root / "submission.sv"
            safe_baseline = work_root / "baseline.sv"
            shutil.copyfile(design, safe_design)
            shutil.copyfile(baseline, safe_baseline)
            design = safe_design
            baseline = safe_baseline
            stage, log = run_lint(design)
            stages.append(stage)
            logs.append(log)
            if stage["status"] == "pass":
                stage, log, _hidden_sha256, _hidden_test_count = run_sim(
                    sim_task,
                    design,
                    work_root,
                    official=official,
                )
                stages.append(stage)
                logs.append(log)
                if official and stage["status"] == "fail" and HIDDEN_FAILURE_PREFIX in log:
                    disqualified = True
                    disqualification_reason = _hidden_disqualification_reason(log)
            else:
                stages.append({"stage": 1, "name": "sim", "status": "fail"})

            correctness_ok = stages[-1]["status"] == "pass"
            if correctness_ok:
                if package.objective.behavior_preserving:
                    sec_stage, sec, log = run_sec(package, baseline, design, work_root)
                    stages.append(sec_stage)
                    logs.append(log)
                    correctness_ok = sec_stage["status"] == "pass"
                else:
                    stages.append({"stage": 2, "name": "correctness", "status": "skip"})
            else:
                stages.append({"stage": 2, "name": "correctness", "status": "fail"})

            if correctness_ok:
                obj_stage, objective_pass, ppa_delta, log = run_objective(package, baseline, design, work_root)
                stages.append(obj_stage)
                logs.append(log)
            else:
                stages.append({"stage": 3, "name": "objective", "status": "fail"})

    task_score = 100.0 if (not disqualified and objective_pass) else 0.0
    stages = [_full_stage(stage) for stage in stages]
    data = {
        "task_id": package.task_id,
        "suite_version": SUITE_VERSION,
        "track": "B",
        "docker_digest": runtime_docker_digest(),
        "platform": "linux/amd64",
        "submission_dir": str(submission_root),
        "disqualified": disqualified,
        "disqualification_reason": disqualification_reason,
        "objective_type": package.objective.objective_type,
        "objective_pass": objective_pass,
        "stages": stages,
        "sec": sec,
        "ppa_delta": ppa_delta,
        "task_score": task_score,
        "wall_clock_s": round(time.perf_counter() - start, 6),
        "provider": "local",
        "model": "track-b-evaluator",
        "temperature": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "tool_calls": 0,
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "signature": "0" * 64,
    }
    data["signature"] = compute_manifest_signature(data)
    manifest = TrackBManifest.model_validate(data)
    out_path = Path(out)
    atomic_write_text(out_path, json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n")
    out_path.with_suffix(".log").write_text("\n\n".join(logs), encoding="utf-8")
    return manifest


def _hidden_disqualification_reason(log: str) -> str:
    for line in reversed(log.splitlines()):
        if line.startswith(HIDDEN_FAILURE_PREFIX):
            return line
    return f"{HIDDEN_FAILURE_PREFIX}hidden tests did not load"


def _full_stage(stage: dict[str, object]) -> dict[str, object]:
    full = {
        "warnings": None,
        "tests_run": None,
        "tests_passed": None,
        "area_um2": None,
        "cell_count": None,
        "wns_ns": None,
        "tns_ns": None,
        "fmax_mhz": None,
        "power_mw": None,
    }
    full.update(stage)
    return full


def resolve_track_b_task(task_id: str) -> TrackBPackage:
    candidates = [TOY_TRACKB_ROOT] if task_id == "toy_taskB" else []
    candidates.append(TRACKB_ROOT / task_id)
    for root in candidates:
        if (root / "objective.yaml").exists():
            objective = load_objective(root / "objective.yaml")
            design = single_sv_file(root / "design")
            top = _find_top_module(design, fallback=task_id)
            validate_identifier(top, label="top module")
            clock = float(objective.params.get("clock_ns") or _read_clock_target(root / "task.yaml"))
            return TrackBPackage(task_id=objective.task_id, root=root, objective=objective, top_module=top, clock_target_ns=clock)
    raise FileNotFoundError(f"unknown Track B task: {task_id}")


def _read_clock_target(path: Path) -> float:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("clock_target_ns:"):
            return float(line.split(":", 1)[1].strip())
    raise ValueError(f"missing clock_target_ns in {path}")


def single_sv_file(directory: Path) -> Path:
    files = sorted(directory.glob("*.sv"))
    if len(files) != 1:
        raise ValueError(f"expected exactly one .sv file in {directory}, found {len(files)}")
    return files[0]


def load_objective(path: Path) -> Objective:
    lines = path.read_text(encoding="utf-8").splitlines()
    data: dict[str, Any] = {}
    params: dict[str, Any] = {}
    in_objective = False
    for raw in lines:
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith("objective:"):
            in_objective = True
            continue
        if line and not line.startswith(" "):
            in_objective = False
        if in_objective:
            key, _, value = line.strip().partition(":")
            params[key.strip()] = _parse_scalar(value.strip())
        else:
            key, _, value = line.strip().partition(":")
            if key in {"id", "behavior_preserving"}:
                data[key] = _parse_scalar(value.strip())
    obj_type = params.pop("type")
    return Objective(task_id=str(data["id"]), objective_type=str(obj_type), behavior_preserving=bool(data["behavior_preserving"]), params=params)


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value.strip('"\'')


def diff_guard(canonical: Path, submission: Path) -> str | None:
    if not submission.exists():
        return f"missing submission dir: {submission}"
    design = submission / "design"
    if not design.is_dir():
        return "malformed submission: missing design directory"
    design_files = sorted(design.glob("*.sv"))
    if len(design_files) != 1:
        return f"malformed submission: expected exactly one .sv file in design, found {len(design_files)}"
    try:
        validate_sv_filename(design_files[0])
        validate_source_file(design_files[0])
        canonical_top = _find_top_module(
            single_sv_file(canonical / "design"),
            fallback=canonical.name,
        )
        validate_module_declarations(design_files[0], expected_top=canonical_top)
    except (OSError, UnicodeError, SubmissionValidationError) as exc:
        return f"malformed submission: {exc}"
    for entry in IMMUTABLE_ENTRIES:
        left = canonical / entry
        right = submission / entry
        if not left.exists():
            continue
        if left.is_dir():
            if not right.is_dir():
                return f"immutable path missing or not directory: {entry}"
            left_files = {p.relative_to(left) for p in left.rglob("*") if p.is_file()}
            right_files = {p.relative_to(right) for p in right.rglob("*") if p.is_file()}
            if left_files != right_files:
                return f"immutable file set differs: {entry}"
            for rel in sorted(left_files):
                if (left / rel).read_bytes() != (right / rel).read_bytes():
                    return f"immutable file differs: {entry}/{rel.as_posix()}"
        elif left.is_file():
            if not right.is_file():
                return f"immutable file missing: {entry}"
            if left.read_bytes() != right.read_bytes():
                return f"immutable file differs: {entry}"
    allowed_top = {"design", "spec.md", *IMMUTABLE_ENTRIES}
    for child in submission.iterdir():
        if child.name not in allowed_top:
            return f"extra file outside design: {child.name}"
    return None


def run_sec(package: TrackBPackage, baseline: Path, design: Path, work_root: Path) -> tuple[dict[str, object], dict[str, object], str]:
    script = work_root / "sec.ys"
    top = package.top_module
    script.write_text(
        "read_slang " + _ypath(baseline) + " --top " + top + "\n"
        "prep -top " + top + "\n"
        "design -stash gold\n"
        "read_slang " + _ypath(design) + " --top " + top + "\n"
        "prep -top " + top + "\n"
        "design -stash gate\n"
        "design -reset\n"
        "design -copy-from gold -as gold " + top + "\n"
        "design -copy-from gate -as gate " + top + "\n"
        "equiv_make gold gate equiv\n"
        "hierarchy -top equiv\n"
        "equiv_simple -seq 20\n"
        "equiv_induct -seq 20\n"
        "equiv_status -assert\n",
        encoding="utf-8",
    )
    result = _run([YOSYS_BIN, "-s", str(script)], timeout_s=60)
    if result.returncode == 124:
        return {"stage": 2, "name": "sec", "status": "fail"}, {"status": "timeout", "backend": "yosys-equiv", "seconds": None}, result.stdout
    status = "pass" if result.returncode == 0 else "fail"
    return {"stage": 2, "name": "sec", "status": status}, {"status": status, "backend": "yosys-equiv", "seconds": None}, result.stdout


def run_objective(package: TrackBPackage, baseline: Path, design: Path, work_root: Path) -> tuple[dict[str, object], bool, dict[str, Any], str]:
    objective = package.objective
    logs: list[str] = []
    try:
        design_ppa, log = measure_ppa(package, design, work_root / "design_ppa")
        logs.append(log)
        baseline_ppa = None
        if objective.objective_type in {"area_reduction", "power_reduction"}:
            baseline_ppa, log = measure_ppa(package, baseline, work_root / "baseline_ppa")
            logs.append(log)
    except FlowError as exc:
        return {"stage": 3, "name": "objective", "status": "fail"}, False, _empty_ppa_delta(), str(exc)

    ppa_delta = _ppa_delta(design_ppa, baseline_ppa)
    if objective.objective_type == "timing_closure":
        threshold = float(objective.params.get("require_wns_ns_ge", 0.0))
        passed = design_ppa["wns_ns"] >= threshold
    elif objective.objective_type == "area_reduction":
        assert baseline_ppa is not None
        min_pct = float(objective.params["min_pct"])
        passed = design_ppa["wns_ns"] >= 0.0 and design_ppa["area_um2"] <= baseline_ppa["area_um2"] * (1.0 - min_pct / 100.0)
    elif objective.objective_type == "power_reduction":
        assert baseline_ppa is not None
        min_pct = float(objective.params["min_pct"])
        passed = design_ppa["wns_ns"] >= 0.0 and design_ppa["power_mw"] <= baseline_ppa["power_mw"] * (1.0 - min_pct / 100.0)
    elif objective.objective_type == "add_property":
        passed = True
    else:
        raise ValueError(f"unsupported Track B objective: {objective.objective_type}")
    return {"stage": 3, "name": "objective", "status": "pass" if passed else "fail"}, passed, ppa_delta, "\n\n".join(logs)


def measure_ppa(package: TrackBPackage, rtl: Path, work_root: Path) -> tuple[dict[str, float], str]:
    work_root.mkdir(parents=True, exist_ok=True)
    synth = run_synth(submission=rtl, top_module=package.top_module, clock_target_ns=package.clock_target_ns, work_root=work_root)
    sta = run_sta(netlist=synth.netlist, top_module=package.top_module, constraints=package.root / "constraints.sdc", clock_target_ns=package.clock_target_ns)
    power = run_power(netlist=synth.netlist, top_module=package.top_module, constraints=package.root / "constraints.sdc")
    return (
        {
            "area_um2": synth.area_um2,
            "wns_ns": sta.wns_ns,
            "tns_ns": sta.tns_ns,
            "fmax_mhz": sta.fmax_mhz,
            "power_mw": power.power_mw,
        },
        "\n\n".join([synth.log, sta.log, power.log]),
    )


def _empty_ppa_delta() -> dict[str, Any]:
    return {"design": None, "baseline": None, "area_ratio": None, "power_ratio": None, "wns_delta_ns": None}


def _ppa_delta(design: dict[str, float], baseline: dict[str, float] | None) -> dict[str, Any]:
    delta: dict[str, Any] = {"design": design, "baseline": baseline, "area_ratio": None, "power_ratio": None, "wns_delta_ns": None}
    if baseline:
        delta["area_ratio"] = design["area_um2"] / baseline["area_um2"] if baseline["area_um2"] else None
        delta["power_ratio"] = design["power_mw"] / baseline["power_mw"] if baseline["power_mw"] else None
        delta["wns_delta_ns"] = design["wns_ns"] - baseline["wns_ns"]
    return delta


def _ypath(path: Path) -> str:
    return str(path).replace("\\", "/")
