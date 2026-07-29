# Guidance for AI coding assistants

This file orients AI coding agents (and their humans) working in the GateTruth
repository. For the full contributor workflow and task standards, see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Golden rules

1. **Everything runs in the pinned image.** Build, test, and score inside
   `gatetruth:v1` (`flows/Dockerfile`), never on the host — results are only
   meaningful when the toolchain is pinned. Build it with:
   ```bash
   docker build --platform linux/amd64 -t gatetruth:v1 -f flows/Dockerfile .
   ```

2. **Never author or alter reference designs or hidden test vectors.** A task's
   `ref/` design and its hidden `tb/` scoring vectors are the answer key and are
   admitted only after human review. Do not write or modify them from model
   knowledge; propose them in an issue/PR for human sign-off instead.

3. **Determinism is a contract.** The same submission and image must produce a
   byte-identical result manifest except for `timestamp`, `signature`, and
   `wall_clock_s`. Pin every tool invocation and seed; a nondeterministic flow is
   a bug, not accepted noise.

4. **Don't game the gates.** Correctness is a severability gate. Never stub, xfail,
   or weaken tests to pass; never loosen a timeout, sim cap, or scoring constant to
   force a result; never edit acceptance criteria to match an output.

5. **Verify before you claim.** Run `pytest -q` and `ruff check harness/` inside
   the image and paste the raw output into your PR. "Should pass" is not evidence.

6. **`external-audit/` is read-only against vendor sources, and its findings are
   private until maintainer sign-off.** This directory audits external RTL
   benchmarks (e.g. RTLLM, CVDP) by fetching them read-only at a pinned commit
   into `external-audit/vendor/` (gitignored, never committed) and running the
   mutation engine against them. Never write, patch, or "fix" a vendor's files —
   the only outputs are GateTruth-generated JSON reports under
   `external-audit/results/`. Never cite, publish, or reference an audit finding
   in outreach, the paper, or any public-facing text without explicit maintainer
   sign-off — this is a standing rule for the whole audit effort, not a one-off.

## Repository map

See the layout table in the [README](README.md#repository-layout). In short:
`tasks/` and `tasksB/` hold task packages, `harness/` is the evaluator, `flows/`
is the pinned image and flow scripts, `scripts/` holds reproduction and
contamination-scan utilities, and `external-audit/` holds the external-benchmark
mutation audit (see Golden Rule 6).

## Adding or changing a task

Follow the task-package format and admission standards in
[CONTRIBUTING.md](CONTRIBUTING.md): original-prose spec with a fresh canary, a
locked interface, ≥8 enumerated edge cases in the hidden tests, a ≥95% mutation
kill rate, a reference that clears the full pipeline, and human sign-off on the
reference and hidden vectors.
