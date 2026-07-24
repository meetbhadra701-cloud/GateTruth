# Contributing to SiliconBench

Thanks for your interest in SiliconBench. Contributions of new tasks, bug fixes,
and evaluation results are welcome. This document explains how the pieces fit
together so a contribution can be merged with confidence.

## Ways to contribute

- **Report a bug** in the harness, flow, or a task — open a
  [bug report](.github/ISSUE_TEMPLATE/bug_report.md).
- **Propose a new task** — open a [new-task proposal](.github/ISSUE_TEMPLATE/new_task.md)
  before sending a large PR, so the scope and tier can be agreed first.
- **Request a model** for the leaderboard — open a
  [model request](.github/ISSUE_TEMPLATE/model_request.md).
- **Improve the harness, docs, or flow** — PRs welcome; please open an issue first
  for anything non-trivial.

## Development setup

All evaluation runs inside the pinned image so results are reproducible. Build it
from the repository root:

```bash
docker build --platform linux/amd64 -t siliconbench:v1 -f flows/Dockerfile .
```

Run the tests and linter inside the image before opening a PR:

```bash
docker run --rm -v "$PWD:/work" -w /work siliconbench:v1 bash -c "pytest -q && ruff check harness/"
```

## Anatomy of a task

Every Track A task is a self-contained package under `tasks/<id>/`:

| File | Purpose |
|---|---|
| `spec.md` | Original-prose specification with a unique canary GUID |
| `interface.sv` | Locked module ports and parameters the submission must match |
| `ref/ref.sv` | Human-reviewed reference design (defines the PPA baseline) |
| `tb/` | Public smoke test + held-out hidden scoring vectors |
| `formal/` | Formal properties, for tasks where they are natural |
| `constraints.sdc` | The task's clock target |
| `task.yaml` | Tier, tags, clock, formal flag, PPA weights, review fields |

Track B packages under `tasksB/<id>/` add a suboptimal `baseline/` and an
`objective.yaml` (target + token/tool-call/wall-clock budget).

## Standards a new task must meet

1. **Original spec.** Write the specification from scratch — never copy from
   HDLBits, VerilogEval, textbooks, or any existing repository. Include a fresh
   canary GUID.
2. **Edge cases.** Enumerate at least eight behavioral edge cases and exercise
   them in the hidden tests.
3. **Mutation floor.** The test suite must kill ≥95% of generated RTL mutants.
   Run the mutation gate and paste the kill rate into the PR.
4. **Full pipeline pass.** The reference must clear lint, simulation, formal
   (where applicable), and the synthesis/timing/power flow, producing a valid
   signed manifest.
5. **Human sign-off.** Reference designs and hidden vectors are accepted only
   after human review — the maintainer performs this step; do not self-attest.

## Pull requests

- Keep PRs focused; one task or one fix per PR.
- Paste raw evidence: the commands you ran and their output (test results, lint,
  mutation kill rate, pipeline manifest).
- By contributing you agree your contribution is licensed under the repository's
  [Apache 2.0 License](LICENSE).
