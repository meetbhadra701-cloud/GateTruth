from pathlib import Path

from harness.tree_hash import tree_hash


def test_tree_hash_is_content_sensitive_and_ignores_git(tmp_path: Path) -> None:
    (tmp_path / "B.txt").write_text("second\n", encoding="utf-8")
    (tmp_path / "a.txt").write_text("first\n", encoding="utf-8")
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ignored\n", encoding="utf-8")

    baseline = tree_hash(tmp_path)
    (git_dir / "HEAD").write_text("still ignored\n", encoding="utf-8")
    assert tree_hash(tmp_path) == baseline

    (tmp_path / "a.txt").write_text("changed\n", encoding="utf-8")
    assert tree_hash(tmp_path) != baseline


def test_tree_hash_is_sensitive_to_relative_path_not_just_content(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "file.txt").write_text("same content\n", encoding="utf-8")
    nested = tree_hash(tmp_path)

    (tmp_path / "sub" / "file.txt").unlink()
    (tmp_path / "file.txt").write_text("same content\n", encoding="utf-8")
    (tmp_path / "sub").rmdir()
    flat = tree_hash(tmp_path)

    assert nested != flat


def test_tree_hash_is_sensitive_to_an_added_or_removed_file(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("content\n", encoding="utf-8")
    one_file = tree_hash(tmp_path)

    (tmp_path / "b.txt").write_text("content\n", encoding="utf-8")
    two_files = tree_hash(tmp_path)

    assert one_file != two_files


def test_tree_hash_is_deterministic_across_independent_calls(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("content\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.txt").write_text("more\n", encoding="utf-8")

    assert tree_hash(tmp_path) == tree_hash(tmp_path)
