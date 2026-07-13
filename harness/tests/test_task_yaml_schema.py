from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.schemas.task_yaml import TaskYaml, load_task_yaml, parse_task_yaml_text

REPO_ROOT = Path(__file__).resolve().parents[2]
TOY_TASK_YAML = REPO_ROOT / "harness" / "tests" / "fixtures" / "toy_task" / "task.yaml"
TEST_CANARY = "SILICONBENCH-" + "CANARY-AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE"


def test_toy_task_yaml_loads():
    task = load_task_yaml(TOY_TASK_YAML)

    assert task.id == "toy_task"
    assert task.tier == "T1"
    assert task.weights.area == 1


def test_pilot_task_yaml_files_load():
    tasks_dir = REPO_ROOT / "tasks"
    for task_yaml in tasks_dir.glob("*/task.yaml"):
        assert load_task_yaml(task_yaml).id == task_yaml.parent.name


def test_weights_must_all_be_one():
    payload = parse_task_yaml_text(
        """
        id: bad_weights
        tier: T1
        tags: [bad]
        clock_target_ns: 10.0
        formal: false
        route_t3: false
        weights: {area: 1, delay: 2, power: 1}
        canary: "{CANARY}"
        ref_review: PENDING
        hidden_review: PENDING
        """.replace("{CANARY}", TEST_CANARY)
    )

    with pytest.raises(ValidationError, match="weights"):
        TaskYaml.model_validate(payload)


def test_unsigned_review_fields_rejected_for_official_runs():
    task = load_task_yaml(TOY_TASK_YAML)

    with pytest.raises(ValueError, match="ref_review"):
        task.require_official_reviews()


def test_signed_reviews_allowed_for_official_runs():
    payload = parse_task_yaml_text(
        """
        id: signed_task
        tier: T2
        tags: [signed]
        clock_target_ns: 10.0
        formal: true
        route_t3: false
        weights: {area: 1, delay: 1, power: 1}
        canary: "{CANARY}"
        ref_review: SIGNED-OFF-BY-MEET-2026-07-08
        hidden_review: SIGNED-OFF-BY-MEET-2026-07-08
        """.replace("{CANARY}", TEST_CANARY)
    )
    task = TaskYaml.model_validate(payload)

    task.require_official_reviews()
