from harness.env_compat import read_env


def test_primary_environment_value_wins_over_legacy() -> None:
    environment = {
        "GATETRUTH_VALUE": "primary",
        "SILICONBENCH_VALUE": "legacy",
    }

    assert (
        read_env(
            "VALUE",
            environ=environment,
        )
        == "primary"
    )


def test_legacy_environment_value_is_used_when_primary_is_unset() -> None:
    assert (
        read_env(
            "VALUE",
            environ={"SILICONBENCH_VALUE": "legacy"},
        )
        == "legacy"
    )


def test_set_but_empty_primary_does_not_fall_back() -> None:
    environment = {
        "GATETRUTH_VALUE": "",
        "SILICONBENCH_VALUE": "legacy",
    }

    assert (
        read_env(
            "VALUE",
            environ=environment,
        )
        == ""
    )


def test_environment_default_is_returned_when_both_names_are_unset() -> None:
    assert (
        read_env(
            "VALUE",
            "default",
            environ={},
        )
        == "default"
    )
