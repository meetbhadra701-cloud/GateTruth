# GateTruth × ArchXBench adoption pilot — final report

Date: 2026-10-28 · Branch: `adoption/archxbench-pilot-2026-10-28` · **Verdict: `INCONCLUSIVE`**

> Status of this document: private pre-publication finding under AGENTS.md rule 6 — do not cite
> or use in outreach without explicit maintainer sign-off.

## 1. Verdict and why

`INCONCLUSIVE` — about GateTruth's value on ArchXBench. The *package* is sound and reproducible;
the *experiment* is too small and too undiscriminating to support any claim of adoption value.

| Fact (measured) | Consequence |
|---|---|
| 6 mutants generated in total across 3 primary designs (2 / 4 / **0**) | Far too few for any rate; one design produced no mutants (INCONCLUSIVE by the prescribed rule) |
| 5 behavioral kills, 1 equivalent, 0 survivors, 0 compile failures, 0 timeouts | Score 5/5 over 5 valid non-equivalent mutants — **not** a quality claim |
| All 5 kills are output inversions or `==`→`!=` that change the output on 100 % of inputs (mux inversion 8/8, comparator 256/256 ×4) | Any testbench with a single check would kill them; they do not discriminate testbench quality |
| Reference RTL is evaluator-authored | Baselines establish a controlled pilot, not maintainer-validated ground truth |
| Not run through anyone outside the author | No third-party adoption evidence exists |

## 2. What was done

- **Environment** (Phase 1): cloned GateTruth and ArchXBench into a clean directory (`C:\Users\meetb\gt-lab`); branch HEAD matched the stated `b5e1a83…` before work, `origin/main` = `f327624…`, ArchXBench = `0db0d0d…`. Docker Desktop 29.9.2 (Linux/amd64, 8 CPU, 15.4 GiB), WSL2 Ubuntu 26.04 present. Host had no Icarus/Yosys, so everything ran in the repo's pinned `gatetruth:v1` image (rebuilt; first attempt failed on a transient download error and was retried unchanged): Icarus 12.0 (v12_0), Yosys 0.66+228, Python 3.11.2. Manifest: `REPRODUCIBILITY_MANIFEST.json`.
- **Adapter audit** (Phase 2). The previously reported "nine passing mocked tests" was **not true**: `external-audit/tests/test_archxbench_pilot.py` had a `SyntaxError` (unclosed parenthesis) and could not be collected. Defects found and fixed, each with regression tests:
  1. Compile failure was returned as `FAIL/"compile"`, and GateTruth's report counted it as a **kill** (inflating `kill_rate`). Now `NOT_RUNNABLE/"compile"` → `COMPILE_FAILURE`, never behavioral evidence.
  2. No check that the simulation ran the same number of checks as the baseline (a truncated testbench could "pass"). Added `CHECK_COUNT_MISMATCH` → indeterminate.
  3. No check that RTL declares the expected module (now `SETUP_ERROR_MODULE_MISSING`, no simulator run).
  4. Testbench integrity: now requires the vendor tree at the pinned commit **and** `tb.v` byte-identical to the committed blob (this caught a real hazard: a default Windows clone converts the testbenches to CRLF, changing the benchmark bytes).
  5. Missing simulators crashed with a traceback; now exit 3 with a message. Runner-level `OSError` → `SETUP_ERROR`.
  6. Non-UTF-8 simulator output could crash decoding (`errors="replace"`).
  7. Absolute temp paths leaked into vvp's `$finish called` line, so simulation output hashes differed between identical runs. Simulator now invoked with relative paths from an isolated work dir.
  8. Simulator environment is now minimal and locale/TZ pinned; timeout phase (compile vs simulate) recorded.
  9. `git` refused a read-only bind mount owned by another uid (`dubious ownership`): now `-c safe.directory`.
  Confirmed already-correct: exit-zero is never sufficient for PASS (`$finish(1)` in Icarus does not set the exit code, so the JSON summary is the only evidence); malformed/duplicate/boolean/negative summaries rejected; path traversal and symlink escape rejected; original testbench is copied, never edited.
- **Reference problem** (Phase 3): searched the pinned ArchXBench tree (`find` for `code.v`, golden, solution, ref files; README): no reference RTL for any level-0 task (only data/Python golden models for levels 4–6). Specs of `mux2to1`, `comparator-4bit`, `decoder-2to4` were read and judged unambiguous. References were written by the evaluator from the specs, **frozen in commit `585e84c` before any mutation ran**, and each file is labeled evaluator-authored. Validated against an independent Python oracle (`archxbench_oracles.py`) by exhaustive simulation: 8/8, 256/256, 8/8 input combinations match. The decoder follows the spec's mandatory structural-gate style. A behavioral decoder variant, explicitly **not spec-compliant**, was pre-registered as a supplementary sensitivity probe and is excluded from primary totals.
- **Experiment** (Phase 4): GateTruth's existing operators, unmodified (`include_task_specs=False`); every task executed twice.

## 3. Results (measured; denominators stated)

Score = BEHAVIORAL_KILL / (BEHAVIORAL_KILL + SURVIVED). Equivalent, compile-failed, timed-out, setup-error and indeterminate mutants are excluded and listed.

| Design | Generated | Compile OK | BEHAVIORAL_KILL | SURVIVED | EQUIVALENT | Other | Score |
|---|---|---|---|---|---|---|---|
| mux2to1 | 2 | 2 | 1 | 0 | 1 | 0 | 1/1 |
| comparator4bit | 4 | 4 | 4 | 0 | 0 | 0 | 4/4 |
| decoder2to4 (spec-compliant) | **0** | – | – | – | – | – | **inconclusive** |
| **Primary total** | 6 | 6 | 5 | 0 | 1 | 0 | **5/5** |
| *decoder2to4 behavioral (supplementary)* | 2 | 2 | 2 | 0 | 0 | 0 | 2/2 |

Per-operator: `output_inversion` 1 mux kill, 3 comparator kills (+1 supplementary); `comparator_boundary_flip` 1 comparator kill; `bitwise_inversion` (`|`→`^`) 1 mux **equivalent**; `shift_inversion` 1 supplementary kill.
The equivalent mutant is genuine: the mux product terms are mutually exclusive, so OR ≡ XOR. Simulation (all 8 inputs) and a Yosys SAT miter agree. The Yosys miter independently agreed with exhaustive simulation on all 8 decisions made (7 `different`, 1 `equivalent`).
Runtime: the whole 4-task × 2-run experiment takes ~6 s inside the container. Reproduction consistency: run1 = run2 byte-for-byte (wall-clock excluded); clean-clone reproduction matched committed results.

GateTruth's own contract report (`*.report.json`) is preserved; with the compile fix it agrees with the analysis on these designs (contract `killed`/`survived` match).

## 4. Testing performed (all in `gatetruth:v1`)

- `pytest external-audit/tests`: **81 passed**, 0 failed (incl. 7 real-simulator tests of the new code).
- Full `pytest -q`: **440 passed, 11 skipped, 0 failed** (305.7 s); skips are environment-bound (no `.git` snapshot, no hidden staging tree).
- `ruff check harness/ scripts/ paper/ external-audit/ site/`: all checks passed.
- `./external-audit/archxbench-pilot/reproduce_archxbench_pilot.sh` in a fresh clone → `PILOT_REPRODUCED`. Negative tests: non-empty output dir, dirty vendor tree and CRLF-converted testbench each stop with `REPRODUCTION_BLOCKED` (exit 2).

## 5. Skeptical-reviewer audit (Phase 6)

1. **Real external benchmark?** Yes: ArchXBench at a pinned upstream commit, original testbenches byte-verified.
2. **Testbench unchanged?** Yes: byte-identical to the committed blob (checked each run); `tb.v` is copied into an isolated dir.
3. **References independently validated?** Only against an independent Python oracle written by the same evaluator from the same spec text — independent in code, not in author. No maintainer review. Weak.
4. **Real, spec-relevant defects detected?** The kills are real behavioral differences (confirmed exhaustively + SAT), but they are gross faults any testbench would catch. Nothing here shows GateTruth finds *subtle* spec-relevant defects.
5. **Invalid/equivalent identified correctly?** 0 invalid; the single equivalent was proven two independent ways. Sample too small to say the procedure generalizes (sequential designs would need a different equivalence method).
6. **Reproducible?** Yes, same host and same locally built image, twice, plus clean clone. Not yet shown on a second machine or with a bit-identical image rebuild (the rebuilt image ID differs from the one recorded in earlier audits).
7. **Could Yosys MCY do this?** Yes, in principle, and it is ahead on this task class: MCY ships in the same image (`/opt/oss-cad-suite/bin/mcy`), and `yosys mutate` enumerates 33 / 112 / 84 netlist-level candidate mutations for these three references (including the structural decoder, where GateTruth's text operators produce none). Those were enumerated only, not executed, and many will be equivalent. MCY has not been run in this pilot.
8. **Unique value shown?** None demonstrated. Plausible but unproven differences: a lightweight Python/regex flow, a fail-closed per-benchmark adapter contract, and explicit invalid/equivalent bookkeeping. On this evidence Yosys MCY offers broader mutation coverage.
9. **What would stop a maintainer from using it?** The reference-RTL gap (ArchXBench ships none, so every task needs trusted references); operator coverage (no mutation of gate primitives, `&`, `~`, `?:`, or sequential structure beyond a few patterns); a long image build (iverilog from source plus a ~GB toolchain download; tens of minutes, and it failed once on a transient download error); no maintainer-facing "findings" beyond kill/survive.
10. **Mature enough for an outside evaluator?** For *reproducing and critiquing this pilot*: yes. For evaluating GateTruth as a useful tool: no.

Honest comparison: GateTruth's mutators are simple text rewrites (see `harness/mutators/rtl.py`), whereas Yosys `mutate` works on the elaborated netlist. I did not evaluate any other mutation-testing tool, so no novelty claim is made or supported.

## 6. Remediation plan (what would turn INCONCLUSIVE into a real result)

1. **Discriminating mutants**: add operators GateTruth lacks for this class (bitwise `&`, `~` removal, gate-primitive type swap, constant/off-by-one boundary in `<`/`>` → `<=`/`>=`) — as a *labeled* new version, with the experiment re-frozen first; do not retrofit to this result.
2. **Larger task set** (~20–40 level-0/1 tasks), including sequential ones (needs a bounded-model or SBY equivalence step for survivors).
3. **Maintainer-reviewed references** for a subset, or restrict to tasks where upstream supplies golden RTL.
4. **Head-to-head** with Yosys MCY on identical references/testbenches, reported side by side.
5. **Second-machine replication** (Linux CI) with image digest pinned via `GATETRUTH_DOCKER_DIGEST`.

## 7. Deliverables

| File | Purpose |
|---|---|
| `reports/ADOPTION_PILOT_FINAL.md` | this report |
| `reports/EXPERIMENT_RESULTS.json` | aggregate + per-mutant results |
| `reports/REPRODUCIBILITY_MANIFEST.json` | commits, versions, hashes, commands |
| `reports/INDEPENDENT_EVALUATION_PROTOCOL.md` | outsider checklist |
| `reports/OUTREACH_READY.md` | drafts, **on hold** |
| `reports/KNOWN_FAILURES.md` | limitations and negative findings |
| `results/*.json`, `logs/`, `reproduce_archxbench_pilot.sh`, `tasks.json`, `references/` | raw package |
