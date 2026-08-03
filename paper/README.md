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
  currently requires running three separate scripts, not one orchestrator (that
  consolidation is tracked as future work):

  ```bash
  python data/generate_tables.py           # mutation_table, tasks_table, eval_table, trackb_table
  python data/generate_tracka_16384.py     # eval_table_16384 (the reported Track A condition)
  python data/generate_audit_appendix.py   # audit_per_design (the external RTLLM audit)
  ```

  Each validates its own inputs (signatures, canonical task sets, no ambiguous duplicate runs)
  and refuses to write output on any mismatch rather than silently emitting a wrong table.
