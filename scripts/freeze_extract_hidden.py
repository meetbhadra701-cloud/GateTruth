"""Extract marked cocotb hidden tests into a private local staging tree."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HIDDEN_MARKER = "# --- HIDDEN ---"
LOADER_IMPORT = "from harness.hidden import load_hidden"
EXPECTED_TESTBENCHES = 68
MARKER_RE = re.compile(r"(?m)^# --- HIDDEN ---[ \t]*(?:\r?\n|$)")


@dataclass(frozen=True)
class Extraction:
    task_id: str
    kind: str
    public_path: Path
    hidden_path: Path
    status: str


def extraction_plan(root: str | Path = REPO_ROOT) -> list[Extraction]:
    """Return every frozen task testbench and its deterministic extraction status."""

    repo = Path(root).resolve()
    plan: list[Extraction] = []
    for kind in ("tasks", "tasksB"):
        for task_root in sorted((repo / kind).glob("*")):
            if not (task_root / "task.yaml").is_file():
                continue
            testbenches = sorted((task_root / "tb").glob("test_*.py"))
            if len(testbenches) != 1:
                raise ValueError(
                    f"expected one testbench for {task_root.name}, found "
                    f"{len(testbenches)}"
                )
            public_path = testbenches[0]
            text = public_path.read_text(encoding="utf-8")
            marker_count = len(MARKER_RE.findall(text))
            loader_call = f'load_hidden(globals(), "{task_root.name}")'
            if marker_count == 1:
                status = "would_extract"
            elif marker_count == 0 and loader_call in text:
                status = "already_split"
            else:
                raise ValueError(
                    f"{public_path.relative_to(repo)} has marker_count={marker_count} "
                    "and no valid loader stub"
                )
            hidden_path = (
                repo
                / "build"
                / "hidden-staging"
                / kind
                / task_root.name
                / f"hidden_{task_root.name}.py"
            )
            plan.append(
                Extraction(
                    task_id=task_root.name,
                    kind=kind,
                    public_path=public_path,
                    hidden_path=hidden_path,
                    status=status,
                )
            )
    return plan


def apply_extraction(item: Extraction) -> bool:
    """Extract one marked testbench. Return whether files changed."""

    text = item.public_path.read_text(encoding="utf-8")
    match = MARKER_RE.search(text)
    if match is None:
        loader_call = f'load_hidden(globals(), "{item.task_id}")'
        if loader_call not in text:
            raise ValueError(f"split loader stub missing: {item.public_path}")
        if not item.hidden_path.is_file():
            raise ValueError(f"staged hidden module missing: {item.hidden_path}")
        hidden_text = item.hidden_path.read_text(encoding="utf-8")
        repaired = _preserve_review_markers(text, hidden_text)
        if repaired == hidden_text:
            return False
        item.hidden_path.write_text(repaired, encoding="utf-8", newline="\n")
        return True
    if len(MARKER_RE.findall(text)) != 1:
        raise ValueError(f"expected one hidden marker: {item.public_path}")

    smoke = text[: match.start()]
    hidden = text[match.end() :].lstrip("\r\n")
    public_text = _public_source(smoke, item.task_id)
    hidden_text = _preserve_review_markers(
        smoke,
        _hidden_source(item, hidden),
    )
    item.hidden_path.parent.mkdir(parents=True, exist_ok=True)
    item.public_path.write_text(public_text, encoding="utf-8", newline="\n")
    item.hidden_path.write_text(hidden_text, encoding="utf-8", newline="\n")
    return True


def _public_source(smoke: str, task_id: str) -> str:
    if LOADER_IMPORT not in smoke:
        lines = smoke.splitlines(keepends=True)
        insert_at = next(
            (
                index
                for index, line in enumerate(lines)
                if line.startswith("import cocotb") or line.startswith("from cocotb")
            ),
            None,
        )
        if insert_at is None:
            raise ValueError(f"cannot locate cocotb imports for {task_id}")
        lines.insert(insert_at, LOADER_IMPORT + "\n")
        smoke = "".join(lines)
    return smoke.rstrip() + f'\n\n\nload_hidden(globals(), "{task_id}")\n'


def _hidden_source(item: Extraction, hidden: str) -> str:
    relative = (
        Path(item.kind) / item.task_id / "tb" / item.public_path.name
    ).as_posix()
    return (
        '"""Private hidden tests extracted from '
        + relative
        + ".\n\n"
        "Load only through harness.hidden.load_hidden; it injects the public testbench helpers.\n"
        '"""\n\n'
        + HIDDEN_MARKER
        + "\n"
        + hidden.rstrip()
        + "\n"
    )


def _preserve_review_markers(public_text: str, hidden_text: str) -> str:
    if "HUMAN REVIEW:" in hidden_text:
        return hidden_text
    review_lines = [
        line
        for line in public_text.splitlines()
        if line.lstrip().startswith("#") and "HUMAN REVIEW:" in line
    ]
    if not review_lines:
        return hidden_text
    marker = HIDDEN_MARKER + "\n"
    return hidden_text.replace(
        marker,
        marker + "\n".join(review_lines) + "\n\n",
        1,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write smoke-only public files and private staging modules",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = extraction_plan()
    if len(plan) != EXPECTED_TESTBENCHES:
        raise ValueError(
            f"expected {EXPECTED_TESTBENCHES} testbenches, found {len(plan)}"
        )
    changed = 0
    for item in plan:
        relative = item.public_path.relative_to(REPO_ROOT).as_posix()
        status = item.status
        if args.apply:
            did_change = apply_extraction(item)
            changed += int(did_change)
            status = "extracted" if did_change else "already_split"
        print(f"{status}: {relative}")
    mode = "apply" if args.apply else "dry-run"
    print(f"freeze_extract_hidden: {mode} files={len(plan)} changed={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
