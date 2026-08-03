import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.schemas.canonical_json import compute_manifest_signature
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


def _resigned(data: dict) -> dict:
    """Recompute the signature over the (deliberately structurally broken) data
    so these tests exercise the new stage-shape validator specifically, rather
    than failing earlier on the unrelated tamper-detection check."""

    data = dict(data)
    data["signature"] = compute_manifest_signature(data)
    return data


def test_missing_a_required_stage_is_rejected():
    data = json.loads((FIXTURES / "valid_manifest.json").read_text())
    data["stages"] = [s for s in data["stages"] if s["stage"] != 6]

    with pytest.raises(ValidationError, match=r"stages must be exactly"):
        ResultManifest.model_validate(_resigned(data))


def test_extra_stage_number_is_rejected():
    data = json.loads((FIXTURES / "valid_manifest.json").read_text())
    extra = dict(data["stages"][-1])
    extra["stage"] = 7
    extra["name"] = "extra"
    data["stages"] = data["stages"] + [extra]

    with pytest.raises(ValidationError):
        ResultManifest.model_validate(_resigned(data))


def test_stage_out_of_order_is_rejected():
    data = json.loads((FIXTURES / "valid_manifest.json").read_text())
    data["stages"] = list(reversed(data["stages"]))

    with pytest.raises(ValidationError, match=r"stages must be exactly"):
        ResultManifest.model_validate(_resigned(data))


def test_wrong_stage_name_is_rejected():
    data = json.loads((FIXTURES / "valid_manifest.json").read_text())
    data["stages"][1]["name"] = "simulation"

    with pytest.raises(ValidationError, match=r"must be named 'sim'"):
        ResultManifest.model_validate(_resigned(data))
