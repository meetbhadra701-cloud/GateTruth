# SiliconBench paper

LaTeX source for the SiliconBench v1.0 paper.

## Build

```bash
latexmk -pdf main.tex     # runs pdflatex + bibtex automatically
```

or upload `main.tex`, `references.bib`, and the `data/build/*.tex` fragments to Overleaf.

## Layout

- `main.tex` — the manuscript (single file, `article` class).
- `references.bib` — bibliography (5 entries, arXiv IDs verified 2026-07-24).
- `data/build/*.tex` — auto-generated result tables, `\input` by `main.tex`.
  Committed so the paper compiles from a clean checkout (the `results/` trees
  they derive from are private/ignored). Regenerate with:

  ```bash
  python data/generate_tables.py
  ```

## Notes

- The prose is Meet's rewrite pass; the assembled markdown source of record lives
  in the vault (`60-Paper/SiliconBench-v1.0.md`).
- Before submission: add the author contact/affiliation line in `main.tex`, and
  confirm the RTLLM design-count citation (30 vs the v2's 50 — see Section 8).
- This tree has not been compiled in-repo (no TeX toolchain in CI); it passes a
  structural lint (balanced environments, math parity, resolved `\input`s).
