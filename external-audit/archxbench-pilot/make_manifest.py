"""Emit a machine-readable reproducibility manifest (runs inside the pinned image)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def run(*cmd: str, cwd: Path | None = None) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    text = (out.stdout or out.stderr).strip()
    return text.splitlines()[0] if text else f"unavailable (exit {out.returncode})"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--vendor-root", required=True, type=Path)
    ap.add_argument("--image-id", default="unknown")
    ap.add_argument("--host", default="unknown")
    a = ap.parse_args()
    tasks = json.loads((HERE / "tasks.json").read_text())
    sources = {}
    for rel in ["external-audit/archxbench_pilot.py", "external-audit/archxbench_analysis.py",
                "external-audit/archxbench_oracles.py", "external-audit/auditor/audit.py",
                "external-audit/auditor/protocol.py", "harness/mutators/rtl.py", "harness/sv_mask.py",
                "external-audit/archxbench-pilot/tasks.json", "flows/Dockerfile", "flows/requirements.txt",
                "external-audit/archxbench-pilot/run_pilot.py",
                "external-audit/archxbench-pilot/reproduce_archxbench_pilot.sh"]:
        sources[rel] = sha(REPO / rel)
    for task in tasks["primary"] + tasks["supplementary"]:
        sources[f"external-audit/archxbench-pilot/{task['reference']}"] = sha(HERE / task["reference"])
        sources[f"ArchXBench/{task['task_path']}/tb.v"] = sha(a.vendor_root / task["task_path"] / "tb.v")
    manifest = {
        "gatetruth_commit": os.environ.get("GT_COMMIT", "unknown"),
        "gatetruth_uncommitted_files": os.environ.get("GT_DIRTY_FILES", "unknown"),
        "archxbench_commit": tasks["vendor"]["commit"], "seed": tasks["seed"],
        "host": a.host, "container_os_arch": f"{platform.system()} {platform.machine()}",
        "docker_image": "gatetruth:v1", "docker_image_id": a.image_id,
        "tools": {"python": platform.python_version(), "iverilog": run("iverilog", "-V"),
                  "vvp": run("vvp", "-V"), "yosys": run("yosys", "-V"),
                  "verilator": run("verilator", "--version")},
        "source_sha256": sources,
        "reproduction_commands": ["git clone https://github.com/meetbhadra701-cloud/GateTruth.git",
                                  "git checkout adoption/archxbench-pilot-2026-10-28",
                                  "./external-audit/archxbench-pilot/reproduce_archxbench_pilot.sh"],
    }
    a.out.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
