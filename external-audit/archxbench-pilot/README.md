# GateTruth × ArchXBench pilot

Controlled pilot of GateTruth's mutation engine against unmodified ArchXBench testbenches
(level-0 `mux2to1`, `comparator-4bit`, `decoder-2to4`). **Status: INCONCLUSIVE** — see
[`reports/ADOPTION_PILOT_FINAL.md`](reports/ADOPTION_PILOT_FINAL.md). Private pre-publication
material (AGENTS.md rule 6).

- ArchXBench ships **no** reference RTL for these tasks. `references/*.v` are **evaluator-authored**, not upstream, not maintainer-reviewed.
- Task selection and references were frozen (commit `585e84c`) before any mutation ran.
- Pinned: ArchXBench `0db0d0de25aad5238393d51bd97ce952e579fa1a`, seed `20260729`, image `gatetruth:v1` (`flows/Dockerfile`).

## Reproduce (one command, fail-closed)

```bash
./external-audit/archxbench-pilot/reproduce_archxbench_pilot.sh --out /tmp/gt-pilot-out
```

Needs bash, git, Docker (linux/amd64). Last line must be `PILOT_REPRODUCED`. Outsider checklist:
[`reports/INDEPENDENT_EVALUATION_PROTOCOL.md`](reports/INDEPENDENT_EVALUATION_PROTOCOL.md).

## Layout

| Path | Contents |
|---|---|
| `tasks.json` | frozen task list, seed, vendor commit |
| `references/` | evaluator-authored RTL (+ one labeled non-spec-compliant sensitivity variant) |
| `../archxbench_pilot.py` | fail-closed testbench adapter + CLI |
| `../archxbench_analysis.py`, `../archxbench_oracles.py` | explicit outcome categories, exhaustive + Yosys equivalence, independent oracles |
| `run_pilot.py`, `make_manifest.py` | in-container orchestration (each task twice) and manifest |
| `results/` | committed per-mutant JSON (`*.analysis.json`) and GateTruth contract reports (`*.report.json`) |
| `reports/` | final report, results JSON, manifest, protocol, outreach drafts (on hold), known failures |
| `../tests/test_archxbench_pilot.py` | 62 adapter/analysis tests (81 across external-audit) |
