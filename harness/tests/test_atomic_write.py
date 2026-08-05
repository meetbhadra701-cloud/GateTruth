from __future__ import annotations

import stat

from harness.atomic_write import atomic_write_bytes, atomic_write_text


def test_atomic_write_creates_parent_dirs_and_content(tmp_path):
    path = tmp_path / "nested" / "manifest.json"
    atomic_write_text(path, '{"a": 1}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 1}\n'


def test_atomic_write_replaces_existing_file_fully(tmp_path):
    path = tmp_path / "manifest.json"
    atomic_write_text(path, '{"a": 1}\n')
    atomic_write_text(path, '{"a": 2, "b": 3}\n')
    assert path.read_text(encoding="utf-8") == '{"a": 2, "b": 3}\n'


def test_atomic_write_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "manifest.json"
    atomic_write_text(path, "content\n")
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_atomic_write_never_leaves_a_partial_file_on_failed_replace(tmp_path, monkeypatch):
    """If os.replace itself fails, the original file (if any) must be untouched --
    never a half-written temp file masquerading at the real path."""
    import os as os_module

    path = tmp_path / "manifest.json"
    atomic_write_text(path, "original\n")

    def failing_replace(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os_module, "replace", failing_replace)
    try:
        atomic_write_text(path, "new content that must not land\n")
    except OSError:
        pass

    assert path.read_text(encoding="utf-8") == "original\n"
    leftovers = [p for p in tmp_path.iterdir() if p != path]
    assert leftovers == []


def test_atomic_write_text_produces_a_world_readable_file(tmp_path):
    """Pins the real bug this session found breaking nightly.yml's artifact
    upload: tempfile.mkstemp() creates its temp file at mode 0600, and
    os.replace() preserves that mode across the rename, so without an explicit
    chmod every file this module writes is readable only by the uid that wrote
    it. Harmless when writer and reader are the same process, a silent EACCES
    the moment they are not -- exactly what happened when a GitHub Actions
    runner (a different uid than the gatetruth:v1 container that wrote
    results/nightly/*.json) tried to upload it as a workflow artifact.
    Confirmed directly against the real failed run before writing this fix."""
    path = tmp_path / "manifest.json"
    atomic_write_text(path, "content\n")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o044 == 0o044, f"expected group/other read, got {oct(mode)}"


def test_atomic_write_bytes_produces_a_world_readable_file(tmp_path):
    path = tmp_path / "submission.sv"
    atomic_write_bytes(path, b"module m; endmodule\n")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode & 0o044 == 0o044, f"expected group/other read, got {oct(mode)}"
