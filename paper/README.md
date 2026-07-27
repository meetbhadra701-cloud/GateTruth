# SiliconBench paper

LaTeX source for the SiliconBench v1.0 paper.

## Build

```bash
latexmk -pdf main.tex     # runs pdflatex + bibtex automatically
```

or upload `main.tex`, `references.bib`, and the `data/build/*.tex` fragments to Overleaf.

## Layout

- `main.tex` — the manuscript (single file, `article` class).
- `references.bib` — bibliography (arXiv IDs verified).
- `data/build/*.tex` — auto-generated result tables, `\input` by `main.tex` and
  committed so the paper compiles from a clean checkout. They are regenerated from
  the committed official result manifests under `results/eval/` with:

  ```bash
  python data/generate_tables.py
  ```
