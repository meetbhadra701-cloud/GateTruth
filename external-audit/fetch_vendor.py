"""Fetch pinned external benchmark sources for local, read-only audit use."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

AUDIT_ROOT = Path(__file__).resolve().parent
DEFAULT_VENDOR_ROOT = AUDIT_ROOT / "vendor"
LOCK_PATH = AUDIT_ROOT / "provenance.lock.json"
PROVENANCE_PATH = AUDIT_ROOT / "PROVENANCE.md"
FETCH_DATE = date(2026, 7, 29)


@dataclass(frozen=True)
class Vendor:
    key: str
    name: str
    directory: str
    url: str
    revision: str
    license_name: str
    license_url: str
    license_path: str | None
    item_count: int | None = None
    item_scope: str | None = None


VENDORS = {
    "rtllm": Vendor(
        key="rtllm",
        name="RTLLM v2.0",
        directory="RTLLM",
        url="https://github.com/hkust-zhiyao/RTLLM.git",
        revision="41b26896e33b536940116a975626455eed3de65e",
        license_name="MIT",
        license_url="https://github.com/hkust-zhiyao/RTLLM/blob/main/LICENSE",
        license_path="LICENSE",
        item_count=50,
        item_scope="design directories with self-checking testbenches",
    ),
    "cvdp-harness": Vendor(
        key="cvdp-harness",
        name="CVDP benchmark harness",
        directory="cvdp_benchmark",
        url="https://github.com/NVlabs/cvdp_benchmark.git",
        revision="8e894cf74414ab1eaea1e2b4e80a02f123df07b6",
        license_name="Apache-2.0",
        license_url="https://github.com/NVlabs/cvdp_benchmark/blob/main/LICENSE",
        license_path="LICENSE",
    ),
    "cvdp-dataset": Vendor(
        key="cvdp-dataset",
        name="CVDP benchmark dataset",
        directory="cvdp-benchmark-dataset",
        url="https://huggingface.co/datasets/nvidia/cvdp-benchmark-dataset",
        revision="5b807d945f6a99aa645f7e43a64a2115e281b4bf",
        license_name="Mixed: CC BY 4.0 / Apache-2.0 / component terms",
        license_url=(
            "https://huggingface.co/datasets/nvidia/"
            "cvdp-benchmark-dataset/blob/main/LICENSE"
        ),
        license_path="LICENSE",
        item_count=302,
        item_scope="v1.1.0 nonagentic code-generation no-commercial rows",
    ),
}


def _run(args: list[str], *, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(args)}\n{result.stdout}")
    return result.stdout.strip()


def _make_writable(root: Path) -> None:
    if os.name == "nt":
        return
    for path in [root, *root.rglob("*")]:
        try:
            path.chmod(path.stat().st_mode | stat.S_IWUSR)
        except OSError:
            pass


def _make_read_only(root: Path) -> None:
    if os.name == "nt":
        print(
            f"warning: chmod read-only enforcement is unavailable on Windows for {root}; "
            "mount this directory read-only in containers",
            file=sys.stderr,
        )
        return
    for path in sorted(root.rglob("*"), reverse=True):
        try:
            mode = path.stat().st_mode
            path.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        except OSError:
            pass
    root.chmod(root.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))


def _checkout(vendor: Vendor, vendor_root: Path) -> Path:
    destination = vendor_root / vendor.directory
    if destination.exists():
        _make_writable(destination)
        origin = _run(["git", "remote", "get-url", "origin"], cwd=destination)
        if origin.rstrip("/") != vendor.url.rstrip("/"):
            raise RuntimeError(
                f"{destination} origin mismatch: expected {vendor.url}, found {origin}"
            )
    else:
        vendor_root.mkdir(parents=True, exist_ok=True)
        _run(["git", "clone", "--no-checkout", vendor.url, str(destination)])

    _run(["git", "fetch", "--depth", "1", "origin", vendor.revision], cwd=destination)
    _run(["git", "checkout", "--detach", "--force", vendor.revision], cwd=destination)
    head = _run(["git", "rev-parse", "HEAD"], cwd=destination)
    if head != vendor.revision:
        raise RuntimeError(
            f"{vendor.name} revision mismatch: expected {vendor.revision}, found {head}"
        )
    status = _run(["git", "status", "--porcelain"], cwd=destination)
    if status:
        raise RuntimeError(f"{vendor.name} checkout is dirty:\n{status}")
    _make_read_only(destination)
    return destination


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(
        (
            path.relative_to(root).as_posix(),
            path,
        )
        for path in root.rglob("*")
        if ".git" not in path.relative_to(root).parts
    )
    for relative, path in paths:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        if path.is_symlink():
            digest.update(b"L")
            digest.update(os.readlink(path).encode("utf-8"))
        elif path.is_file():
            digest.update(b"F")
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        elif path.is_dir():
            digest.update(b"D")
        digest.update(b"\0")
    return digest.hexdigest()


def _file_hash(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_provenance(
    records: dict[str, dict[str, object]],
    *,
    lock_path: Path = LOCK_PATH,
    provenance_path: Path = PROVENANCE_PATH,
) -> None:
    lock_path.write_text(
        json.dumps(
            {
                "fetch_date": FETCH_DATE.isoformat(),
                "vendors": records,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    sections = [
        "# External Audit Provenance",
        "",
        f"Fetch date: {FETCH_DATE.isoformat()}",
        "",
        "Vendor source trees are not redistributed. Only GateTruth-generated JSON reports",
        "containing stable identifiers and hashes are committed. Audit runs mount vendor trees",
        "read-only and execute mutants from temporary copies.",
        "",
    ]
    for key in sorted(records):
        record = records[key]
        sections.extend(
            [
                f"## {record['name']}",
                "",
                f"- Upstream: {record['url']}",
                f"- Pinned revision: `{record['revision']}`",
                f"- License: [{record['license_name']}]({record['license_url']})",
                f"- License SHA-256: `{record['license_sha256'] or 'metadata-only'}`",
                f"- Content SHA-256: `{record['content_sha256']}`",
                (
                    f"- Audited inventory: {record['item_count']} "
                    f"{record['item_scope']}"
                    if record.get("item_count") is not None
                    else "- Audited inventory: infrastructure only"
                ),
                f"- Local directory: `external-audit/vendor/{record['directory']}` (gitignored)",
                "",
            ]
        )
    provenance_path.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")


def _selected_vendors(only: str) -> list[Vendor]:
    if only == "rtllm":
        return [VENDORS["rtllm"]]
    if only == "cvdp":
        return [VENDORS["cvdp-harness"], VENDORS["cvdp-dataset"]]
    return list(VENDORS.values())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", choices=("all", "rtllm", "cvdp"), default="all")
    parser.add_argument("--vendor-root", type=Path, default=DEFAULT_VENDOR_ROOT)
    args = parser.parse_args(argv)

    existing: dict[str, dict[str, object]] = {}
    if LOCK_PATH.is_file():
        raw = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        existing = dict(raw.get("vendors", {}))

    for vendor in _selected_vendors(args.only):
        checkout = _checkout(vendor, args.vendor_root)
        license_path = checkout / vendor.license_path if vendor.license_path else None
        existing[vendor.key] = {
            "content_sha256": tree_hash(checkout),
            "directory": vendor.directory,
            "item_count": vendor.item_count,
            "item_scope": vendor.item_scope,
            "license_name": vendor.license_name,
            "license_sha256": _file_hash(license_path),
            "license_url": vendor.license_url,
            "name": vendor.name,
            "revision": vendor.revision,
            "url": vendor.url,
        }
        print(f"{vendor.key}: {vendor.revision}")

    _write_provenance(existing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
