import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.schemas.manifest import ResultManifest, load_manifest

FIXTURES = Path(__file__).parent / "fixtures"
BAD_MANIFESTS = FIXTURES / "bad_manifests"


def test_valid_manifest_fixture_loads():
    manifest = load_manifest(FIXTURES / "valid_manifest.json")

    assert manifest.task_id == "toy_task"
    assert manifest.platform == "linux/amd64"
    assert manifest.task_score == pytest.approx(66.6666666667)


@pytest.mark.parametrize(
    "name",
    [
        "missing_required.json",
        "wrong_platform.json",
        "bad_stage_metrics.json",
        "gate_fail_nonzero_score.json",
        "malformed_signature.json",
    ],
)
def test_bad_manifest_fixtures_rejected(name):
    with pytest.raises(ValidationError):
        load_manifest(BAD_MANIFESTS / name)


def test_signature_tamper_rejected():
    data = json.loads((FIXTURES / "valid_manifest.json").read_text())
    data["ppa"] = 1.01

    with pytest.raises(ValidationError, match="signature"):
        ResultManifest.model_validate(data)
