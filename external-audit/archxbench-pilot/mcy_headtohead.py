"""Yosys MCY on the same references and unmodified testbenches (exploratory head-to-head).

Per design this builds a throwaway MCY project, lets MCY enumerate netlist-level mutations
(`size` large enough to take them all), runs the upstream testbench against each mutated netlist
and, separately, an equivalence check against the reference. Runs inside the pinned image.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIT = HERE.parent
sys.path[:0] = [str(AUDIT), str(AUDIT.parent)]

from archxbench_pilot import sim_env, verify_vendor  # noqa: E402

CONFIG = """[options]
size {size}

[script]
read_verilog -sv code.v
prep -top {module}

[files]
code.v
tb.v
test_tb.sh
test_equiv.sh

[logic]
tb = result("test_tb")
eq = result("test_equiv")
tag("TB_" + tb)
tag("EQ_" + eq)

[report]
print("TB_PASS", tags("TB_PASS"))
print("TB_FAIL", tags("TB_FAIL"))

[test test_tb]
expect PASS FAIL COMPILE BAD
run bash $PRJDIR/test_tb.sh

[test test_equiv]
expect EQUIVALENT DIFFERENT UNKNOWN
run bash $PRJDIR/test_equiv.sh
"""

TEST_TB = """#!/bin/bash
# exit 0 always; the verdict goes to output.txt as MCY requires
exec 2>&1
bash $SCRIPTS/create_mutated.sh -o mutated.v || {{ echo BAD > output.txt; exit 0; }}
if ! iverilog -g2012 -s {tb_top} -o sim.out $PRJDIR/tb.v mutated.v; then echo COMPILE > output.txt; exit 0; fi
timeout 60 vvp sim.out > sim.log || true
cat sim.log
if [ "$(grep -c '^{{"module"' sim.log)" != "1" ]; then echo BAD > output.txt; exit 0; fi
passed=$(grep '^{{"module"' sim.log | sed -E 's/.*"passed": ([0-9]+).*/\\1/')
failed=$(grep '^{{"module"' sim.log | sed -E 's/.*"failed": ([0-9]+).*/\\1/')
if [ "$failed" = "0" ] && [ "$passed" -gt 0 ]; then echo PASS > output.txt; elif [ "$failed" -gt 0 ]; then echo FAIL > output.txt; else echo BAD > output.txt; fi
exit 0
"""

TEST_EQUIV = """#!/bin/bash
exec 2>&1
bash $SCRIPTS/create_mutated.sh -o mutated.v || {{ echo UNKNOWN > output.txt; exit 0; }}
python3 $GT_AUDIT_DIR/archxbench-pilot/mcy_equiv.py --reference $PRJDIR/code.v --mutated mutated.v --module {module} > output.txt || echo UNKNOWN > output.txt
exit 0
"""


def category(tb: str, eq: str) -> str:
    if tb == "TB_COMPILE":
        return "COMPILE_FAILURE"
    if tb == "TB_FAIL":
        return "BEHAVIORAL_KILL" if eq == "EQ_DIFFERENT" else "INDETERMINATE"
    if tb == "TB_PASS":
        return {"EQ_DIFFERENT": "SURVIVED", "EQ_EQUIVALENT": "EQUIVALENT"}.get(eq, "INDETERMINATE")
    return "INDETERMINATE"


def run_design(task: dict, vendor: Path, sha: str, work: Path, jobs: int, size: int) -> dict:
    _, tb = verify_vendor(vendor, sha, task["task_path"])
    proj = work / task["design_id"]
    shutil.rmtree(proj, ignore_errors=True)
    proj.mkdir(parents=True)
    ref = HERE / task["reference"]
    shutil.copyfile(ref, proj / "code.v")
    shutil.copyfile(tb, proj / "tb.v")  # byte-exact copy of the pinned upstream testbench
    (proj / "config.mcy").write_text(CONFIG.format(size=size, module=task["module"]), newline="\n")
    (proj / "test_tb.sh").write_text(TEST_TB.format(tb_top=task["tb_top"]), newline="\n")
    (proj / "test_equiv.sh").write_text(TEST_EQUIV.format(module=task["module"]), newline="\n")
    env = {**sim_env(), "GT_AUDIT_DIR": str(AUDIT)}
    started = time.monotonic()
    log = []
    for cmd in (["mcy", "init"], ["mcy", "run", "-j", str(jobs)]):
        out = subprocess.run(cmd, cwd=proj, env=env, capture_output=True, text=True)
        log.append(f"$ {' '.join(cmd)} (rc={out.returncode})\n{out.stdout[-3000:]}{out.stderr[-3000:]}")
    wall = round(time.monotonic() - started, 1)
    (proj / "mcy_driver.log").write_text("\n".join(log))
    db = sqlite3.connect(proj / "database" / "db.sqlite3")
    tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    mutations = {}
    for mid, line in db.execute("select mutation_id, mutation from mutations"):
        mutations[mid] = line
    tags: dict[int, set[str]] = {m: set() for m in mutations}
    for mid, tag in db.execute("select mutation_id, tag from tags"):
        tags.setdefault(mid, set()).add(tag)
    rows = []
    control = None
    for mid in sorted(mutations):
        tb_tag = next((t for t in tags[mid] if t.startswith("TB_")), "TB_NONE")
        eq_tag = next((t for t in tags[mid] if t.startswith("EQ_")), "EQ_NONE")
        if "-mode none" in mutations[mid]:
            control = {"tb": tb_tag, "equiv": eq_tag}
            continue
        rows.append({"mutation": mutations[mid], "tb": tb_tag, "equiv": eq_tag,
                     "category": category(tb_tag, eq_tag)})
    # MCY ids are not guaranteed stable; present results in a canonical order
    rows.sort(key=lambda r: r["mutation"])
    counts = Counter(r["category"] for r in rows)
    kills, surv = counts["BEHAVIORAL_KILL"], counts["SURVIVED"]
    return {"design_id": task["design_id"], "tool": "yosys-mcy", "mutations_enumerated": len(rows),
            "control_unmutated": control, "category_counts": dict(sorted(counts.items())),
            "valid_nonequivalent_mutants": kills + surv,
            "kill_fraction": f"{kills}/{kills + surv}", "tables": sorted(tables),
            "mutations": rows, "wall_s": wall}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vendor-root", required=True, type=Path)
    ap.add_argument("--tasks", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--work", type=Path, default=Path("/tmp/gt-mcy"))
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--size", type=int, default=5000)
    a = ap.parse_args()
    tasks = json.loads(a.tasks.read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    results = {}
    for task in tasks["primary"]:
        res = run_design(task, a.vendor_root.resolve(), tasks["vendor"]["commit"], a.work, a.jobs, a.size)
        results[task["design_id"]] = res
        print(f"{task['design_id']:<20} mutations={res['mutations_enumerated']:<4} "
              f"{res['category_counts']} control={res['control_unmutated']}")
    (a.out / "mcy_results.json").write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
