# Known failures, limitations and negative findings

Nothing here has been hidden or smoothed. Items are ordered by how much they limit the conclusions.

## Scientific limits

1. **Tiny, undiscriminating sample.** 6 primary mutants, 5 valid non-equivalent; every kill is a gross fault that changes outputs on 100 % of inputs. The 5/5 score says nothing about testbench quality.
2. **Zero mutants for the spec-compliant decoder.** GateTruth's operators are text rewrites of `assign`, ` == `, ` | `, ` << ` etc. The spec forces gate-primitive instantiation, so there is nothing to mutate. The result is `INCONCLUSIVE`, not a pass. (The operator inventory was known from reading `harness/mutators/rtl.py` before the run; the decoder style follows the spec text, not mutator coverage. The behavioral variant exists only as a labeled sensitivity probe.)
3. **No operator for `&`, `~`, gate primitives, `<`/`>` boundaries, or `?:`.** So the weakest ArchXBench testbench by inspection — `comparator-4bit`, 5 of 256 input combinations; `decoder-2to4`, 6 of 8 — produced **no surviving mutant**. GateTruth did not expose those gaps; a human reading the testbench sees them immediately. Whether such gaps cause real survivors is untested (I did not invent extra mutants, per the protocol).
4. **References are evaluator-authored** (by an AI-assisted engineer, from spec text), validated only against an oracle by the same author, not reviewed by ArchXBench maintainers. AGENTS.md rule 2 ("never author reference designs … propose them for human sign-off") was followed only partially: authoring was explicitly requested, files are labeled, but **human sign-off is still pending**.
5. **Equivalence method is combinational-only.** Exhaustive simulation + SAT miter apply to these designs; sequential designs need a different method. "Legal input" assumption: all 2-state combinations (the specs define no illegal encodings).
6. **A mutant that differs from the reference is not a proven specification violation**; the reference's fidelity to the spec is the weak link.
7. **No third-party adoption evidence.** Passing tests ≠ adoption.

## Reproducibility limits

8. Replication was on the same host (Windows 11, Docker Desktop) using the locally built image. The rebuilt `gatetruth:v1` has ID `sha256:736dc86f…`, which differs from the ID in `external-audit/README.md` (`4252e0…`) for earlier audits; the Dockerfile documents that IDs are not predictable across rebuilds. The base image and OSS CAD Suite are hash/commit pinned, but the apt package set comes from a Debian snapshot and iverilog from a pinned git commit — tool versions should match, bytes may not.
9. The first image build failed on a transient `curl (18)` while downloading the OSS CAD Suite; an unchanged retry succeeded. The build needs network and tens of minutes.
10. `external-audit/README.md`'s documented build command (`-f flows/Dockerfile .`) does not match AGENTS.md (`… flows`); the Dockerfile `COPY requirements.txt` only works with `flows` as context. Not changed here (unrelated file).
11. Log files (`*.log`) are gitignored by the repo; the committed `logs/` carries only the pytest summary. The reproduction script writes the full logs into its output directory.

## Defects found in the pre-existing pilot (fixed on this branch)

12. The adapter test file did not parse (`SyntaxError`); the earlier "nine passing mocked tests" claim was never true.
13. Compile failures were counted as kills in GateTruth's `kill_rate`.
14. Testbench CRLF conversion on Windows clones silently alters the benchmark.
15. Absolute temp paths in simulator output made output hashes run-dependent.
16. See `ADOPTION_PILOT_FINAL.md` §2 for the remaining items.

## Residual adapter risks (not fixed)

- Simulator stdout is captured unbounded: a mutant printing in a zero-delay loop could exhaust memory before the timeout.
- Timeouts kill the direct child only; no process-group kill.
- The adapter trusts the testbench's own JSON summary; a testbench that lies cannot be detected.
- The ArchXBench README's documented command is plain `iverilog tb.v code.v`; the pilot uses `-g2012` (GateTruth's paper condition). Not compared across generation flags.
- `BASELINE_FAIL`, `UNSUPPORTED`, `TIMEOUT`, `SETUP_ERROR` paths are exercised by unit tests with mocked/real simulators but did not occur in the real experiment.

## Repository-policy notes for the owner

- This repo is **public**, so the pushed branch is public. AGENTS.md rule 6 says audit findings stay private until maintainer sign-off; nothing here asserts a defect in ArchXBench, but the owner should confirm that publishing this branch is acceptable.
- Outreach drafts are in `OUTREACH_READY.md`; none has been sent.
