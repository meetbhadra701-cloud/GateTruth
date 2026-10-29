# Independent Evaluation Protocol — GateTruth × ArchXBench pilot

Audience: an outside researcher or benchmark maintainer who wants to check this artifact
without trusting its author. Estimated effort: under one hour, most of it the one-time image build.

## 0. What you are (and are not) being asked to evaluate

You are asked to evaluate whether this *small, controlled pilot* is reproducible and
technically sound. You are **not** asked to endorse GateTruth, cite it, or accept the
evaluator-authored reference RTL as an ArchXBench artifact. ArchXBench ships no reference
RTL for its level-0 tasks; the three references here were written by the evaluator
(an AI-assisted engineer, not the benchmark authors) from the published specifications
and are labeled as such in every file and result.

## 1. Prerequisites

- Linux/amd64, macOS, or Windows with a working Docker (linux/amd64 containers), `git`, `bash`.
- Network access for the first run only (clone ArchXBench at the pinned commit; build the
  pinned `gatetruth:v1` image — about 10–25 minutes). Experiment containers run with `--network none`.

## 2. Reproduce

```bash
git clone https://github.com/meetbhadra701-cloud/GateTruth.git
cd GateTruth && git checkout adoption/archxbench-pilot-2026-10-28
./external-audit/archxbench-pilot/reproduce_archxbench_pilot.sh --out /tmp/gt-pilot-out
```

Expected last line: `PILOT_REPRODUCED`. The script fails closed (exit 1 or 2 with a reason) if
Docker, the pinned vendor commit, a clean vendor tree, the unit tests, determinism,
or the comparison against the committed results does not hold. It refuses to write into a
non-empty output directory and mounts both the repository and the vendor tree read-only.

## 3. Independent checks the reproduction does *not* do for you (please do these)

| # | Check | How |
|---|-------|-----|
| 1 | Testbenches are pristine upstream | `git -C ArchXBench status --porcelain` is empty; compare `sha256sum level-0/*/tb.v` with `REPRODUCIBILITY_MANIFEST.json` |
| 2 | References follow the *spec*, not the testbench | Read `design-specs.txt` for `mux2to1`, `comparator-4bit`, `decoder-2to4`; read `references/*.v`; flag any semantic disagreement |
| 3 | The oracle is independent | Read `external-audit/archxbench_oracles.py` (Python truth functions from the spec prose; shares no code with the RTL) |
| 4 | A sampled mutant verdict | Pick any ID in `results/<design>.run1.analysis.json`, apply `source_diff` to the reference, run `iverilog -g2012 -s <tb_top> tb.v code.v && vvp a.out` yourself |
| 5 | Equivalence claims | For each `EQUIVALENT` mutant, confirm with your own tool (e.g. Yosys `equiv_*`, SymbiYosys, or by hand for 3-input logic) |
| 6 | Operator coverage honesty | Read `harness/mutators/rtl.py`: note which constructs it can and cannot mutate (see KNOWN_FAILURES.md) |

## 4. What would change our conclusions

- A reference that disagrees with the spec ⇒ the baseline and every kill/survive verdict for that design are void.
- An `EQUIVALENT` mutant that your tool shows to differ ⇒ a bug in our equivalence procedure; please report it.
- A `BEHAVIORAL_KILL` that does not reproduce under plain `iverilog tb.v code.v` ⇒ a bug in the adapter.
- Any difference between `run1` and `run2`, or between your results and `results/` ⇒ non-reproducibility.

## 5. Feedback requested (all optional)

1. Would this evidence type (per-mutant verdicts against an unmodified benchmark testbench) be useful for your benchmark's maintenance?
2. Which of your tasks would be worth a larger, maintainer-validated reference set?
3. Any disagreement with the category definitions in `archxbench_analysis.py` (module docstring).

Please send corrections or "this is not useful" verdicts: negative feedback is as valuable as positive.
