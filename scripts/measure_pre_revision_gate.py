"""Re-measure the pre-revision mutation-kill rate of every mutation-revised Track A testbench.

Supports the Goodhart disclosure in paper/main.tex (Section "Limitations and Threats to Validity"):
the paper reports that exactly ten of the 60 Track A testbenches were ever modified in response to
a mutation result, and gives their kill rates BEFORE that modification. This script reproduces
those numbers.

Method, and why it is constructed this way:

  * The ten revised testbenches are identified from git history, not asserted -- every commit that
    touched tasks/*/tb/ and was motivated by a mutation result belongs to the SB-023 chain listed in
    REVISION_COMMITS below.
  * Each testbench is restored to its state at BASELINE_COMMIT (the parent of the first such
    commit), while the reference RTL is left at its CURRENT state. Holding the RTL fixed matters:
    mutants are generated from the reference, so an unchanged reference guarantees the pre- and
    post-revision runs see an identical mutant set, and the measured difference is attributable to
    the testbench alone rather than to later mutation-engine improvements.
  * The restored testbenches predate the v1.0 hidden-vector split, so they still carry an inline
    "# --- HIDDEN ---" marker. scripts/freeze_extract_hidden.py is re-run to split them exactly as
    the v1.0 freeze did, producing a pre-revision public/hidden pair.
  * Mutation runs are sequential (jobs=1), matching the certification protocol: mutation verdicts
    are not invariant to execution concurrency, so a parallel sweep could silently inflate them.

Run inside the pinned image:

    python scripts/measure_pre_revision_gate.py --out pre_revision_results.json

This script never writes into the checkout it is invoked from (GTFS-032): every
restore below runs inside a disposable `git worktree` checked out fresh from HEAD,
by re-executing this same script inside that worktree. `--restore-only` leaves the
worktree alive and prints its path so the extraction step and a later re-run can
continue in the same copy (pass `--worktree <path>` to reuse it); a full run always
removes the worktree when it finishes, success or failure.

Requires GATETRUTH_HIDDEN_ROOT to point at the staging tree produced by the extraction step.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Parent of 978cfff, the first mutation-driven testbench revision.
BASELINE_COMMIT = "85cb9e7"

# Every commit that modified a Track A testbench in response to a mutation result.
REVISION_COMMITS = ("978cfff", "b32bccb", "bb03354", "9da091d")

# Union of the tasks those commits touched. Regenerate with:
#   for c in 978cfff b32bccb bb03354 9da091d; do
#     git show --name-only --format= $c -- tasks/; done | grep -oP 'tasks/\K[^/]+' | sort -u
REVISED_TASKS = (
    "t2_axi_lite_regfile",
    "t2_delay_trigger",
    "t2_i2c_slave",
    "t2_spi_master",
    "t2_spi_slave",
    "t2_stream_downsizer",
    "t2_stream_upsizer",
    "t2_uart_rx",
    "t2_uart_tx",
    "t3_sequential_divider",
)

SEED = 1337


def verify_reference_unchanged(task_id: str) -> bool:
    """A changed reference would alter the mutant set and invalidate the comparison."""
    ref = f"tasks/{task_id}/ref/ref.sv"
    result = subprocess.run(
        ["git", "diff", "--quiet", BASELINE_COMMIT, "HEAD", "--", ref],
        cwd=REPO_ROOT,
        check=False,
    )
    return result.returncode == 0


def restore_pre_revision_testbench(task_id: str) -> None:
    tb = f"tasks/{task_id}/tb/test_{task_id}.py"
    blob = subprocess.run(
        ["git", "show", f"{BASELINE_COMMIT}:{tb}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    ).stdout
    (REPO_ROOT / tb).write_bytes(blob)


def _create_isolated_worktree() -> Path:
    """Check out a disposable, detached copy of HEAD.

    Every destructive write in this module goes through this worktree instead of
    the canonical checkout (GTFS-032): the caller's tree is never touched because
    this process never resolves REPO_ROOT to it in the first place.
    """
    scratch_parent = Path(tempfile.mkdtemp(prefix="gatetruth-pre-revision-"))
    worktree_dir = scratch_parent / "worktree"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree_dir), "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return worktree_dir


def _remove_isolated_worktree(worktree_dir: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_dir)],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
    )
    shutil.rmtree(worktree_dir.parent, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("pre_revision_results.json"))
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument(
        "--restore-only",
        action="store_true",
        help="restore testbenches and exit, so the extraction step can run before measuring",
    )
    parser.add_argument(
        "--worktree",
        type=Path,
        default=None,
        help="reuse an existing isolated worktree (path printed by a prior "
        "--restore-only run) instead of creating a fresh one",
    )
    parser.add_argument(
        "--allow-live-tree",
        action="store_true",
        help=argparse.SUPPRESS,  # internal: set only when this script re-execs itself
    )
    args = parser.parse_args(argv)

    if not args.allow_live_tree:
        reusing = args.worktree is not None
        worktree = args.worktree if reusing else _create_isolated_worktree()
        child_argv = [
            sys.executable,
            str(worktree / "scripts" / "measure_pre_revision_gate.py"),
            "--out",
            str(args.out),
            "--seed",
            str(args.seed),
            "--allow-live-tree",
        ]
        if args.restore_only:
            child_argv.append("--restore-only")
        result = subprocess.run(child_argv, cwd=worktree)

        if reusing:
            # Not ours to delete: the caller owns this worktree's lifecycle.
            return result.returncode
        if args.restore_only and result.returncode == 0:
            print(f"pre-revision testbenches restored in isolated worktree: {worktree}")
            print("inside that worktree, run: python scripts/freeze_extract_hidden.py --apply")
            print(f"then continue with: --worktree {worktree}")
            print(f"or discard it with: git worktree remove --force {worktree}")
            return 0
        _remove_isolated_worktree(worktree)
        return result.returncode

    # From here on, this process IS the isolated worktree: REPO_ROOT above resolved
    # to it, computed fresh from this file's own on-disk location, so every write
    # below is confined to the disposable copy.
    drifted = [t for t in REVISED_TASKS if not verify_reference_unchanged(t)]
    if drifted:
        print(
            "REFUSING: reference RTL changed since baseline for: " + ", ".join(drifted),
            file=sys.stderr,
        )
        print("The mutant sets would differ and the comparison would be invalid.", file=sys.stderr)
        return 1
    print(f"all {len(REVISED_TASKS)} references byte-identical to {BASELINE_COMMIT}: mutant sets match")

    for task_id in REVISED_TASKS:
        restore_pre_revision_testbench(task_id)
    print(f"restored {len(REVISED_TASKS)} pre-revision testbenches")

    if args.restore_only:
        print("now run: python scripts/freeze_extract_hidden.py --apply")
        return 0

    from harness.mutate import run_mutation  # imported late: needs the container toolchain

    results: dict[str, dict] = {}
    for task_id in REVISED_TASKS:
        report = run_mutation(
            task_id=task_id, min_kill=95.0, seed=args.seed, jobs=1, official=True
        )
        results[task_id] = {
            k: report[k]
            for k in ("total", "killed", "survived", "indeterminate", "kill_rate")
        }
        print(
            f"{task_id:26s} kill_rate={report['kill_rate']:7.4f} "
            f"({report['killed']}/{report['total']})",
            flush=True,
        )
        args.out.write_text(
            json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    rates = sorted(v["kill_rate"] for v in results.values())
    median = (
        rates[len(rates) // 2]
        if len(rates) % 2
        else (rates[len(rates) // 2 - 1] + rates[len(rates) // 2]) / 2
    )
    print(f"\npre-revision median {median:.2f}%  range {rates[0]:.2f}-{rates[-1]:.2f}%")
    print(f"below the 95% floor pre-revision: {sum(1 for r in rates if r < 95)}/{len(rates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
