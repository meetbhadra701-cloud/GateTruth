# GateTruth paper

LaTeX source for the GateTruth v1.0 paper.

## Build

```bash
latexmk -pdf main.tex     # runs pdflatex + bibtex automatically
```

or upload `main.tex`, `references.bib`, and the `data/build/*.tex` fragments to Overleaf.

## Layout

- `main.tex` — the manuscript (single file, `article` class).
- `references.bib` — bibliography (arXiv IDs verified).
- `data/build/*.tex` — auto-generated result tables, `\input` by `main.tex` and
  committed so the paper compiles from a clean checkout. Regenerating all of them
  currently requires running six separate scripts, not one orchestrator (that
  consolidation is tracked as future work):

  ```bash
  python data/generate_tables.py                  # mutation_table, tasks_table, eval_table, trackb_table
  python data/generate_tracka_16384.py             # eval_table_16384 (the reported Track A condition)
  python data/generate_audit_appendix.py           # audit_per_design (the external RTLLM audit)
  python data/generate_failure_taxonomy.py         # failure_taxonomy_table (Appendix, per-model breakdown)
  python data/generate_variance_appendix.py        # variance_table (Appendix, run-to-run spread)
  python data/generate_paper_facts.py              # paper_facts (prose-cited counts: terciles, operator mix, etc.)
  ```

  `generate_failure_taxonomy.py` additionally depends on `data/lint_diagnostics_ledger.json`, a
  small committed ledger regenerated from local Verilator logs by
  `../scripts/generate_lint_diagnostics_ledger.py` (see that script's docstring for why its raw
  input isn't part of the repository, matching `results/refs/` -> `harness/reference_metrics.json`).

  Each generator validates its own inputs (signatures, canonical task sets, no ambiguous duplicate
  runs, count/arithmetic invariants) and refuses to write output on any mismatch rather than
  silently emitting a wrong table.
