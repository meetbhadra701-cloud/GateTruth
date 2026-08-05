"""End-to-end checks for the public manifest reproducer."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.runner import run_task
from harness.schemas.canonical_json import compute_manifest_signature

REPO_ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "t1_gray_counter"
REFERENCE = REPO_ROOT / "tasks" / TASK_ID / "ref" / "ref.sv"
SCRIPT = REPO_ROOT / "scripts" / "reproduce.py"


@pytest.fixture(scope="module")
def fresh_reference_manifest(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("reproduce") / "reference.json"
    run_task(TASK_ID, REFERENCE, path)
    return path


def _run_reproducer(
    path: Path, *, official: bool = False, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SCRIPT), str(path)]
    if official:
        args.append("--official")
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        env=env,
    )


def test_fresh_reference_manifest_reproduces(
    fresh_reference_manifest: Path,
) -> None:
    result = _run_reproducer(fresh_reference_manifest)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout
    assert "signature=" in result.stdout


def test_resigned_tampered_score_is_detected(
    fresh_reference_manifest: Path,
    tmp_path: Path,
) -> None:
    raw = json.loads(fresh_reference_manifest.read_text(encoding="utf-8"))
    raw["task_score"] = 0.0
    raw["signature"] = compute_manifest_signature(raw)
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    result = _run_reproducer(tampered)

    assert result.returncode == 1
    assert "MISMATCH" in result.stderr
    assert '"task_score": 0.0' in result.stderr
    assert '"task_score": 66.66666666666667' in result.stderr


def test_forced_official_flag_without_hidden_root_fails_closed(
    fresh_reference_manifest: Path,
) -> None:
    """fresh_reference_manifest was produced non-officially, so auto-inference alone
    would already choose official=False here -- this test specifically forces
    --official to prove the explicit-override path also fails closed rather than
    silently reporting a false MATCH when no hidden root is mounted."""

    import os

    env = dict(os.environ)
    env.pop("GATETRUTH_HIDDEN_ROOT", None)
    env.pop("SILICONBENCH_HIDDEN_ROOT", None)

    result = _run_reproducer(fresh_reference_manifest, official=True, env=env)

    assert result.returncode != 0
    assert "MATCH task=" not in result.stdout


def test_modern_manifest_with_tampered_provenance_hash_is_still_rejected(
    fresh_reference_manifest: Path, tmp_path: Path
) -> None:
    """GTFS-008: the legacy-compatibility fix must only drop a provenance field from
    comparison when it is *absent* from the recorded original -- a modern manifest that
    does record submission_sha256 must still be held to it. fresh_reference_manifest
    (built via a plain run_task() call) always carries submission_sha256, since
    harness/runner.py computes it unconditionally, regardless of official mode."""

    raw = json.loads(fresh_reference_manifest.read_text(encoding="utf-8"))
    assert raw["submission_sha256"], "fixture setup did not record submission_sha256"
    raw["submission_sha256"] = "0" * 64
    raw["signature"] = compute_manifest_signature(raw)
    tampered = tmp_path / "tampered_hash.json"
    tampered.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    result = _run_reproducer(tampered)

    assert result.returncode == 1
    assert "MISMATCH" in result.stderr
    assert '"submission_sha256": "' + "0" * 64 + '"' in result.stderr


def test_legacy_shaped_manifest_missing_new_provenance_fields_still_reproduces(
    tmp_path_factory: pytest.TempPathFactory, tmp_path: Path
) -> None:
    """GTFS-008 (+GTFS-002's image_marker, added later the same way): all 420 real
    manifests under results/eval-16384/ predate submission_sha256, task_package_sha256,
    reference_metrics_sha256, hidden_module_sha256, hidden_test_count,
    docker_digest_source, and image_marker. Simulates that exact legacy shape here by
    scoring officially, then stripping those seven fields and re-signing -- exactly what
    the real historical payload looks like -- and confirms the reproducer still finds a
    MATCH rather than spuriously failing on fields that simply didn't exist yet."""

    import os

    hidden_root = REPO_ROOT.parent / "codex-SB-101" / "build" / "hidden-staging"
    if not hidden_root.is_dir():
        pytest.skip("real hidden-staging tree not present on this machine")

    env = dict(os.environ)
    env["GATETRUTH_HIDDEN_ROOT"] = str(hidden_root)

    official_path = tmp_path_factory.mktemp("reproduce-legacy-shape") / "official.json"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from harness.runner import run_task; import sys; "
            f"run_task({TASK_ID!r}, {str(REFERENCE)!r}, {str(official_path)!r}, official=True)",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        timeout=120,
    )
    raw = json.loads(official_path.read_text(encoding="utf-8"))
    assert raw["hidden_module_sha256"], "fixture setup did not actually score officially"
    for field in (
        "submission_sha256",
        "task_package_sha256",
        "reference_metrics_sha256",
        "hidden_module_sha256",
        "hidden_test_count",
        "docker_digest_source",
        "image_marker",
    ):
        raw.pop(field, None)
    raw["signature"] = compute_manifest_signature(raw)
    legacy_shaped = tmp_path / "legacy_shaped.json"
    legacy_shaped.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
    import shutil

    shutil.copy2(REFERENCE, legacy_shaped.with_suffix(".sv"))

    result = _run_reproducer(legacy_shaped, official=True, env=env)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout


def test_fresh_manifest_records_image_marker_and_reproduces_it_exactly(
    fresh_reference_manifest: Path,
) -> None:
    """GTFS-002: a manifest generated inside the real image records image_marker (the
    self-declared /etc/gatetruth-image-digest content) independently of docker_digest.
    Unlike the six GTFS-008 fields, this one is NOT expected to be absent going
    forward -- every fresh manifest carries it whenever the marker file exists -- so a
    modern-to-modern reproduction (both runs read the same file inside the same image)
    must hold it to an exact match, not silently drop it via
    LEGACY_OPTIONAL_PROVENANCE_FIELDS."""

    raw = json.loads(fresh_reference_manifest.read_text(encoding="utf-8"))
    if raw.get("image_marker") is None:
        pytest.skip("no /etc/gatetruth-image-digest marker file present on this machine")

    result = _run_reproducer(fresh_reference_manifest)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout


def test_modern_manifest_with_tampered_image_marker_is_still_rejected(
    fresh_reference_manifest: Path, tmp_path: Path
) -> None:
    raw = json.loads(fresh_reference_manifest.read_text(encoding="utf-8"))
    if raw.get("image_marker") is None:
        pytest.skip("no /etc/gatetruth-image-digest marker file present on this machine")
    raw["image_marker"] = "sha256:" + "0" * 64
    raw["signature"] = compute_manifest_signature(raw)
    tampered = tmp_path / "tampered_marker.json"
    tampered.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")

    result = _run_reproducer(tampered)

    assert result.returncode == 1
    assert "MISMATCH" in result.stderr
    assert '"image_marker": "sha256:' + "0" * 64 + '"' in result.stderr


def test_official_mode_is_inferred_from_hidden_module_sha256_without_the_flag(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The manifest schema now records hidden_module_sha256 whenever a real
    hidden-vector mount was resolved during an official run -- reproduce.py should
    use that to infer official mode automatically, not require the caller to
    separately remember and pass --official."""

    import os

    hidden_root = REPO_ROOT.parent / "codex-SB-101" / "build" / "hidden-staging"
    if not hidden_root.is_dir():
        pytest.skip("real hidden-staging tree not present on this machine")

    env = dict(os.environ)
    env["GATETRUTH_HIDDEN_ROOT"] = str(hidden_root)

    official_path = tmp_path_factory.mktemp("reproduce-official") / "official.json"
    subprocess.run(
        [
            sys.executable,
            "-c",
            "from harness.runner import run_task; import sys; "
            f"run_task({TASK_ID!r}, {str(REFERENCE)!r}, {str(official_path)!r}, official=True)",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        timeout=120,
    )
    recorded = json.loads(official_path.read_text(encoding="utf-8"))
    assert recorded["hidden_module_sha256"], "fixture setup did not actually score officially"

    # No --official flag passed; auto-inference must still choose official=True and
    # therefore still require (and here, receive) the hidden root to reproduce correctly.
    result = _run_reproducer(official_path, env=env)

    assert result.returncode == 0, result.stderr
    assert f"MATCH task={TASK_ID}" in result.stdout
    assert "official=True" in result.stdout

    # Same manifest, no hidden root this time, still no --official flag: auto-inference
    # must still choose official=True from hidden_module_sha256 alone and therefore still
    # fail closed, not silently fall back to a non-official (and therefore vacuous) match.
    env_without_root = dict(os.environ)
    env_without_root.pop("GATETRUTH_HIDDEN_ROOT", None)
    env_without_root.pop("SILICONBENCH_HIDDEN_ROOT", None)
    result = _run_reproducer(official_path, env=env_without_root)

    assert result.returncode != 0
    assert "MATCH task=" not in result.stdout
