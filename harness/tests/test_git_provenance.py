import pytest

from harness.git_provenance import harness_git

REAL_SHA = "0123456789abcdef0123456789abcdef01234567"
SHORT_SHA = "0123abc"


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GATETRUTH_GIT_COMMIT", "SILICONBENCH_GIT_COMMIT", "GITHUB_SHA"):
        monkeypatch.delenv(name, raising=False)


def test_gatetruth_env_var_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GATETRUTH_GIT_COMMIT", REAL_SHA)
    monkeypatch.setenv("GITHUB_SHA", "f" * 40)

    assert harness_git() == REAL_SHA


def test_legacy_env_var_used_when_primary_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("SILICONBENCH_GIT_COMMIT", REAL_SHA)

    assert harness_git() == REAL_SHA


def test_github_sha_used_when_gatetruth_vars_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", REAL_SHA)

    assert harness_git() == REAL_SHA


def test_short_sha_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GATETRUTH_GIT_COMMIT", SHORT_SHA)

    assert harness_git() == SHORT_SHA


def test_malformed_env_value_is_ignored_and_falls_through(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("GATETRUTH_GIT_COMMIT", "not-a-real-sha!")
    monkeypatch.setenv("GITHUB_SHA", REAL_SHA)

    assert harness_git() == REAL_SHA


def test_falls_back_to_the_real_repo_head_when_nothing_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear(monkeypatch)

    result = harness_git()

    assert result == "unavailable" or __import__("re").fullmatch(r"[0-9a-f]{7,40}", result)


def test_unavailable_when_repo_root_has_no_git_history(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    _clear(monkeypatch)

    assert harness_git(repo_root=tmp_path) == "unavailable"
