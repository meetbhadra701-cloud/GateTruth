# Outreach drafts — ON HOLD, NOT SENT

**Nothing in this file has been sent, posted, or filed.** Do not send without your explicit approval and, per AGENTS.md rule 6, maintainer sign-off.

## Recommendation: hold all five

The pilot verdict is `INCONCLUSIVE`: 6 mutants, 5 trivially detected, 0 mutants for the spec-compliant decoder, evaluator-authored references, no outside replication. A reviewer who opens the artifact will see that it does not yet demonstrate value, and Yosys `mutate` enumerates roughly an order of magnitude more candidate mutations on the same designs (33 vs 2, 112 vs 4, 84 vs 0; enumerated, not executed). Sending now would spend goodwill on a weak artifact. Remediation first (see `ADOPTION_PILOT_FINAL.md` §6): discriminating operators, 20–40 tasks incl. sequential ones, an MCY head-to-head, second-machine replication. Revisit these drafts after that; each is written so it stays accurate (counts must be updated).

Every ask below is deliberately small: *"independently re-run a one-command package and tell us where it is wrong"*. No citations, publicity, endorsement, or anything beyond candid technical feedback.

Facts used about each target come from public pages found on 2026-10-28 (links at the end); verify before sending.

---

## 1. TuRTLe — Barcelona Supercomputing Center (HPAI)

**Subject:** Small independent check of a mutation-testing harness against benchmark testbenches

Hi TuRTLe team,

TuRTLe unifies RTL benchmarks (VerilogEval, RTLLM, RTL-Repo, VeriGen) behind one evaluation framework and scores syntax, function, synthesizability and post-synthesis quality. Functional scores depend on each benchmark's testbench actually distinguishing wrong RTL from right RTL, so we built a small harness that mutates a reference design and records, per mutant, whether the unmodified testbench fails it, with invalid, equivalent and timed-out mutants reported separately.

We ran a very small pilot (3 ArchXBench level-0 tasks; 6 mutants; our own reference RTL). The honest summary: it is reproducible but too small and too easy to show anything about testbench quality, and we are working on that. Would any of you be willing to spend ~30 minutes running `reproduce_archxbench_pilot.sh` and tell us (a) whether it reproduces for you and (b) whether per-mutant verdicts like this would be useful to the testbench-quality side of TuRTLe at all? "Not useful" is a fine answer.

Repo/branch: `github.com/meetbhadra701-cloud/GateTruth` (`adoption/archxbench-pilot-2026-10-28`). Protocol: `external-audit/archxbench-pilot/reports/INDEPENDENT_EVALUATION_PROTOCOL.md`.

Thanks, Meet Bhadra

## 2. ArchXBench maintainers (Suresh Purini et al.)

**Subject:** ArchXBench level-0: reference RTL availability + a small reproducibility check

Hi,

We used ArchXBench v1.5 (commit 0db0d0d) as a real external testbench source for a mutation-testing pilot. Your `tb.v` files print a JSON summary line, which made them easy to drive without editing them — thank you; the testbenches ran byte-for-byte unmodified.

Two small, specific questions:
1. Level-0 tasks ship specs and testbenches but no reference RTL. Do you maintain reference solutions elsewhere? We wrote our own for `mux2to1`, `comparator-4bit` and `decoder-2to4` (labeled evaluator-authored, validated only against a Python oracle from your specs) and would much prefer yours.
2. Would you spend ~30 minutes running our one-command reproduction and telling us if anything looks wrong about how we treat your testbenches?

Observation, offered neutrally: by inspection `comparator-4bit` exercises 5 of 256 input combinations and `decoder-2to4` 6 of 8. We have *not* shown that this lets any plausible defect through; our operators did not produce a surviving mutant.

Repo/branch as above. No citation or endorsement requested; critique is.

Thanks, Meet Bhadra

## 3. RTLLM maintainers (HKUST, Zhiyao Xie group)

**Subject:** Independent check of a mutation-based testbench audit that ran on RTLLM

Hi,

RTLLM pairs each design with a testbench and designer-verified reference RTL, which is exactly what a mutation audit needs. [Replace with *measured* RTLLM results from `external-audit/results/rtllm/` only after maintainer sign-off under AGENTS.md rule 6 — this draft deliberately cites none.]

We would like to ask for something small: would one of you (or a student) re-run our fail-closed, one-command package on any two RTLLM designs of your choice and tell us whether the mutant verdicts (killed / survived / equivalent / invalid) match what you expect from your testbenches? We'd report any disagreement as a bug in our tool.

Thanks, Meet Bhadra

## 4. CorrectBench researchers (Qiu, Zhang, Drechsler, Schlichtmann, Li)

**Subject:** Mutants as an alternative "imperfect RTL" source for testbench validation — a question

Hi,

CorrectBench's validator uses LLM-generated imperfect RTL as judges of a generated testbench. We built a deterministic mutation harness (operators and results published, with invalid/equivalent mutants separated) and wondered whether deterministic, equivalence-checked mutants could complement LLM-generated imperfect RTL in that validator. We do **not** claim they do; our current evidence is a 6-mutant pilot that cannot support such a claim.

Small ask: would you be willing to glance at the protocol and tell us whether this comparison is even well-posed for CorrectBench's tasks (e.g. sequential circuits, where our equivalence checking does not yet work)? A two-line "not useful because …" would help us more than anything.

Thanks, Meet Bhadra

## 5. "RTLBench" maintainers — **target needs confirming**

I found no public project named exactly "RTLBench". The closest matches are **RTL-BenchLS** (`hkust-zhiyao/RTL-BenchLS`, >10k verified Verilog designs, with promised formal-verification and evaluation scripts) and RTL-Repo (completion benchmark, not testbench-based). Please confirm which project you mean. Draft assuming RTL-BenchLS:

**Subject:** Small check: mutation-testing the verification scripts of RTL-BenchLS

Hi,

RTL-BenchLS ships functionally verified designs with formal/evaluation scripts; at that scale the interesting question is how strong each design's checks are. We have a small, reproducible mutation-audit harness (3-design pilot, honest about being too small). Would you be open to running it on two designs of your choice and telling us whether the verdict categories make sense for your verification flow — or tell us why a formal flow makes this redundant (Yosys-based mutation coverage might already cover it)?

Thanks, Meet Bhadra

---

Sources consulted: TuRTLe arXiv 2504.01986; RTLLM arXiv 2308.05345 / hkust-zhiyao/RTLLM; CorrectBench arXiv 2411.08510; RTL-BenchLS arXiv 2606.08976; ArchXBench repo at commit 0db0d0d.
