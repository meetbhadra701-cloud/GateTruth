<h1 align="center">GateTruth</h1>

<p align="center">
  <strong>Auditing the rigor of RTL design benchmarks via mutation testing.</strong><br>
  A testbench that never fails isn't proof of a correct design — it may just never
  stimulate what's actually broken.
</p>

<p align="center">
  <a href="LICENSE"><img alt="License: Apache 2.0" src="https://img.shields.io/badge/License-Apache_2.0-blue.svg"></a>
  <img alt="Python 3.11" src="https://img.shields.io/badge/python-3.11-blue.svg">
  <img alt="Platform linux/amd64" src="https://img.shields.io/badge/platform-linux%2Famd64-lightgrey.svg">
  <img alt="EDA: open-source" src="https://img.shields.io/badge/EDA-Yosys%20%7C%20OpenSTA%20%7C%20sky130-green.svg">
  <img alt="Reproducible" src="https://img.shields.io/badge/results-byte--reproducible-success.svg">
  <a href="https://github.com/meetbhadra701-cloud/GateTruth/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/meetbhadra701-cloud/GateTruth/actions/workflows/ci.yml/badge.svg"></a>
</p>

---

Benchmarks for LLM-generated RTL treat their own testbenches as ground truth, and
almost none check whether that trust is earned. GateTruth is a mutation-testing
engine: inject deterministic, seeded semantic faults into a reference design and
measure what fraction the testbench actually catches. A testbench that lets a
broken design pass is a testbench that will also let a broken model-generated
design pass — and no amount of pass@k tells you which kind you have.

We certify the methodology against our own open reference suite first — 60
specification-to-RTL generation tasks plus 8 agentic-repair tasks, each carried
through a **real, pinned open-source ASIC flow** (synthesis + static timing/power
on the sky130 technology) with correctness enforced as a **hard gate**, and every
one of the suite's 68 testbenches certified above a 95% mutation-kill floor — and
then point the same engine, unmodified, at external RTL benchmarks the field
already relies on. See the [paper](#citation) for the audit methodology, the
reference-suite design, and the resulting measurements.

## Leaderboard (v1.0)

Seven models, evaluated under the official pinned flow. The human reference scores
**66.67 by construction**; every model trails it.

### Track A — single-shot RTL generation (60 tasks)

| Rank | Model | Score / 100 |
|:---:|---|---:|
| 🥇 | Claude Opus 4.8 | **46.91** |
| 🥈 | Claude Sonnet 4.6 | 45.03 |
| 🥉 | Claude Haiku 4.5 | 33.58 |
| 4 | GPT-5-mini | 33.44 |
| 5 | GPT-5 | 31.64 |
| 6 | Llama 4 Maverick | 25.52 |
| 7 | Gemini 2.5 Pro | 17.83 |
| — | *human reference* | *66.67* |

### Track B — agentic PPA repair (8 tasks)

| Rank | Model | Objectives met |
|:---:|---|:---:|
| 🥇 | Claude Opus 4.8 | **5 / 8** |
| 🥈 | Claude Sonnet 4.6 | 3 / 8 |
| 🥉 | GPT-5 | 1 / 8 |
| — | Haiku 4.5 · GPT-5-mini · Gemini 2.5 Pro · Llama 4 Maverick | 0 / 8 |

Even the strongest model reaches ~70% of the human reference on generation, and
four of seven make no progress at all on agentic optimization. Cost does not track
quality. See the [paper](#citation) for full per-tier results and analysis.

**Want your model on the board?** Open a [model request](.github/ISSUE_TEMPLATE/model_request.md) —
the maintainer runs it through the official pinned flow and adds the result. Once public,
the live leaderboard is published at `https://meetbhadra701-cloud.github.io/GateTruth/`.

## Two tracks

- **Track A — RTL generation.** The model receives a natural-language spec and a
  locked interface and emits one synthesizable SystemVerilog module, scored
  through the correctness gates and the PPA pipeline.
- **Track B — agentic optimization.** An agent iterates against the synthesis and
  timing tools — editing, re-linting, re-simulating, re-synthesizing — to meet a
  concrete objective (close timing, reduce area/power, remove latches) under an
  explicit token, time, tool-call, and spend budget, with a sequential-equivalence
  gate that forbids changing what the design computes.

## How scoring works

A submission passes six stages. Stages 0–2 are **correctness gates** — each
independently zeroes the score on failure (severability):

| Stage | Check | Tool |
|---|---|---|
| 0 | Lint | `verilator --lint-only` |
| 1 | Simulation vs. hidden vectors | Icarus + cocotb |
| 2 | Formal properties (where declared) | SymbiYosys |
| 3–5 | Synthesis, timing, power | Yosys + OpenSTA (sky130hd) |

Surviving designs are scored on the PPA geometric mean against the reference:

```
ppa        = geomean(ref_area/area, ref_delay/delay, ref_power/power)
task_score = 100 * min(ppa, 1.5) / 1.5
```

The reference scores `ppa = 1.0` → `66.67`; the 100-point ceiling is a design 1.5×
better than the reference. Correctness is a **gate, not a weight**, so a model
cannot win by removing functionality.

## Quickstart

Build the pinned image from the repository root:

```bash
docker build --platform linux/amd64 -t gatetruth:v1 -f flows/Dockerfile .
```

Score a reference design through the Track A pipeline:

```bash
mkdir -p build/secure-src build/secure-output
git archive --format=tar HEAD | tar -xf - -C build/secure-src
chmod 0777 build/secure-output
docker run --rm --network none --cap-drop=ALL \
  --security-opt no-new-privileges --memory=4g --pids-limit=512 --cpus=2 \
  --mount "type=bind,src=$PWD/build/secure-src,dst=/work,readonly" \
  --mount "type=bind,src=$PWD/build/secure-output,dst=/output" \
  --workdir /work gatetruth:v1 ./gatetruth run \
    --task t1_gray_counter \
    --submission tasks/t1_gray_counter/ref/ref.sv \
    --out /output/t1_gray_counter.json
```

Build the static leaderboard site from signed result manifests:

```bash
mkdir -p build/secure-output
chmod 0777 build/secure-output
docker run --rm --network none --cap-drop=ALL \
  --security-opt no-new-privileges --memory=4g --pids-limit=512 --cpus=2 \
  --mount "type=bind,src=$PWD/build/secure-src,dst=/work,readonly" \
  --mount "type=bind,src=$PWD/build/secure-output,dst=/output" \
  --workdir /work gatetruth:v1 ./gatetruth site --out /output/site-build
```

See [Secure execution](docs/SECURE_EXECUTION.md) for the canonical isolation
contract. The staged source tree contains no `.git/`, and execution containers
never receive provider API keys.

## Repository layout

```
tasks/       60 Track A task packages (spec, interface, reference, tests, constraints)
tasksB/       8 Track B agentic task packages (baseline, objective, budget)
harness/     evaluation harness — CLI, scoring, provider adapters, spend ledger
flows/       pinned Docker image + synthesis/timing/power flow scripts
scripts/     reproduction and contamination-scan utilities
site/        static leaderboard generator
paper/       auto-generated result/task tables
docs/        methodology notes
```

Each task is a self-contained package: an original-prose spec (with a unique
canary), a locked interface, a human-reviewed reference, public smoke + held-out
hidden tests, formal properties where natural, and a timing constraint. Reference
designs and hidden vectors require human sign-off; models never see them.

## Reproducibility &amp; integrity

- **Pinned flow.** Every score is computed inside one image with fully version-locked
  tools and standard-cell library, so a result is a function of the design, not the
  tool versions.
- **Canonical manifests.** Each run emits a manifest with a SHA-256 content hash over
  its canonical JSON; re-running a design reproduces it byte-for-byte (tamper-evidence
  against accidental corruption, not a keyed authenticity signature).
- **Mutation-gated tests.** Every task's test suite must kill ≥95% of injected RTL
  mutants before the task is admitted.
- **Contamination controls.** Per-task canaries, a sign-off-gated hidden-vector
  set, and a pre-publication canary scan.
- **Reproducibility scope.** A clean public checkout runs the public smoke tests, and
  the reference reproduces its 66.67 by construction. Reproducing official *model*
  scores additionally requires the maintainer-held hidden vectors (kept private for
  contamination control), mounted via `GATETRUTH_HIDDEN_ROOT` (the legacy
  `SILICONBENCH_HIDDEN_ROOT` alias remains accepted).

## Contributing

New tasks, bug reports, and model requests are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md). Please read the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Citation

A paper describing GateTruth is in preparation. Until then, please cite the
repository (see [CITATION.cff](CITATION.cff)).

## License

[Apache License 2.0](LICENSE).
