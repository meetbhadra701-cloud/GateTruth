"""Public-repository contamination checks for SiliconBench."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CANARY_RE = re.compile(
    r"SILICONBENCH-CANARY-[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-"
    r"[0-9A-F]{4}-[0-9A-F]{12}",
    re.IGNORECASE,
)
HIDDEN_MARKER = "# --- HIDDEN ---"
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".json",
    ".md",
    ".mk",
    ".ps1",
    ".py",
    ".sby",
    ".sdc",
    ".sh",
    ".sv",
    ".tcl",
    ".tex",
    ".txt",
    ".v",
    ".yaml",
    ".yml",
    ".ys",
}
TEXT_NAMES = {".gitattributes", ".gitignore", "Dockerfile", "LICENSE"}
SKIP_DIRS = {".git", ".pytest_cache", ".ruff_cache", "__pycache__", "sim_build"}
FORBIDDEN = (
    "eb" + "-1a",
    "immi" + "gration",
    "blog-" + "drafts.md",
    "hn-" + "post.md",
    "launch-" + "checklist.md",
    "outreach-" + "list.md",
    "youtube-" + "script.md",
)


class ContaminationError(ValueError):
    """Raised when public-repository hygiene checks fail."""


@dataclass(frozen=True)
class CheckReport:
    track_a_tasks: int
    package_canaries: int
    scanned_files: int
    hidden_markers: int


def run_checks(root: str | Path = REPO_ROOT) -> CheckReport:
    """Run all contamination checks and return deterministic counts."""

    repo = Path(root).resolve()
    text_files = list(_text_files(repo))
    package_roots = _package_roots(repo)
    owners = _canary_owners(package_roots)
    errors: list[str] = []
    seen = {canary: 0 for canary in owners}

    for path in text_files:
        relative = path.relative_to(repo)
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for forbidden in FORBIDDEN:
            if forbidden in lowered:
                errors.append(f"forbidden text {forbidden!r} in {relative.as_posix()}")
        for match in CANARY_RE.finditer(text):
            canary = match.group(0).upper()
            owner = owners.get(canary)
            if owner is None:
                errors.append(f"undeclared canary in {relative.as_posix()}: {canary}")
                continue
            seen[canary] += 1
            if not path.resolve().is_relative_to(owner):
                errors.append(
                    f"canary escaped {owner.relative_to(repo).as_posix()}: "
                    f"{relative.as_posix()}"
                )

    for canary, count in seen.items():
        if count == 0:
            errors.append(f"declared canary has no occurrences: {canary}")

    track_a = sorted((repo / "tasks").glob("*/task.yaml"))
    if len(track_a) != 60:
        errors.append(f"expected 60 Track A tasks, found {len(track_a)}")
    hidden_count = 0
    for task_yaml in track_a:
        task_root = task_yaml.parent
        testbenches = sorted((task_root / "tb").glob("test_*.py"))
        if len(testbenches) != 1:
            errors.append(
                f"expected one testbench for {task_root.name}, found {len(testbenches)}"
            )
            continue
        marker_count = testbenches[0].read_text(encoding="utf-8").count(HIDDEN_MARKER)
        if marker_count < 1:
            errors.append(f"hidden marker missing: {testbenches[0].relative_to(repo)}")
        else:
            hidden_count += 1

    if errors:
        raise ContaminationError("\n".join(sorted(errors)))
    return CheckReport(
        track_a_tasks=len(track_a),
        package_canaries=len(owners),
        scanned_files=len(text_files),
        hidden_markers=hidden_count,
    )


def _package_roots(repo: Path) -> list[Path]:
    roots = [path.parent.resolve() for path in (repo / "tasks").glob("*/task.yaml")]
    roots.extend(path.parent.resolve() for path in (repo / "tasksB").glob("*/task.yaml"))
    roots.extend(
        path.parent.resolve()
        for path in (repo / "harness" / "tests" / "fixtures").glob("*/task.yaml")
    )
    return sorted(roots)


def _canary_owners(package_roots: list[Path]) -> dict[str, Path]:
    owners: dict[str, Path] = {}
    for root in package_roots:
        task_yaml = root / "task.yaml"
        matches = CANARY_RE.findall(task_yaml.read_text(encoding="utf-8"))
        if len(matches) != 1:
            raise ContaminationError(f"expected one canary in {task_yaml}, found {len(matches)}")
        canary = matches[0].upper()
        if canary in owners:
            raise ContaminationError(f"duplicate task canary: {canary}")
        owners[canary] = root
    return owners


def _text_files(repo: Path):
    for path in sorted(repo.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(repo)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if relative.parts[:2] in {("site", "build"), ("paper", "data")}:
            if "build" in relative.parts:
                continue
        if path.suffix.lower() in TEXT_SUFFIXES or path.name in TEXT_NAMES:
            yield path


def main() -> int:
    try:
        report = run_checks()
    except (ContaminationError, OSError, UnicodeError) as exc:
        print("contamination_check: FAIL", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1
    print(
        "contamination_check: PASS "
        f"tasks={report.track_a_tasks} "
        f"package_canaries={report.package_canaries} "
        f"scanned_files={report.scanned_files} "
        f"hidden_markers={report.hidden_markers} "
        "forbidden_hits=0 canary_leaks=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
