from __future__ import annotations

from harness.atomic_write import atomic_write_text


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
