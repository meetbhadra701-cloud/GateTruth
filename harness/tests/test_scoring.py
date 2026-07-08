import math

import pytest
from pydantic import ValidationError

from harness.schemas.manifest import load_manifest
from harness.scoring import task_score_from_ppa


def test_reference_score_formula():
    assert math.isclose(task_score_from_ppa(1.0), 66.66666666666667)


def test_ppa_cap():
    assert task_score_from_ppa(99.0) == 100.0


def test_gate_zero():
    assert task_score_from_ppa(0.0) == 0.0
    with pytest.raises(ValidationError):
        load_manifest("harness/tests/fixtures/bad_manifests/gate_fail_nonzero_score.json")


def test_negative_ppa_rejected():
    with pytest.raises(ValueError):
        task_score_from_ppa(-0.1)
