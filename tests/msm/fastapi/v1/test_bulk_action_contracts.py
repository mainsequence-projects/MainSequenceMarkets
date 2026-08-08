from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from apps.v1.schemas.bulk_actions import (
    BULK_ACTION_DISCOVERY_CONTRACT,
    BULK_ACTION_EXECUTION_CONTRACT,
    BULK_ACTION_PREFLIGHT_CONTRACT,
    BulkActionDiscoveryResponse,
    BulkActionExecutionRequest,
    BulkActionPreflightResponse,
)

COMMAND_CENTER_SDK_COMMIT = "7f2c942799fb83edaacfc1c0d971452bfc8aff5c"

_CONTRACT_MODELS = {
    BULK_ACTION_DISCOVERY_CONTRACT: BulkActionDiscoveryResponse,
    BULK_ACTION_EXECUTION_CONTRACT: BulkActionExecutionRequest,
    BULK_ACTION_PREFLIGHT_CONTRACT: BulkActionPreflightResponse,
}


def _contracts_root() -> Path:
    configured_root = os.environ.get("COMMAND_CENTER_SDK_ROOT")
    if not configured_root:
        pytest.skip("Set COMMAND_CENTER_SDK_ROOT to run authoritative SDK fixture tests.")
    root = Path(configured_root)
    candidates = [
        root / "command-center-sdk" / "contracts",
        root / "contracts",
    ]
    for candidate in candidates:
        if (candidate / "manifest.json").is_file():
            return candidate
    pytest.fail(f"Could not locate command-center-sdk contracts under {root}.")


@pytest.mark.parametrize("contract_id", sorted(_CONTRACT_MODELS))
def test_bulk_action_models_match_authoritative_sdk_fixtures(contract_id: str) -> None:
    contracts_root = _contracts_root()
    manifest = json.loads((contracts_root / "manifest.json").read_text())
    entry = next(item for item in manifest["schemas"] if item["contract"] == contract_id)
    schema = json.loads((contracts_root / entry["file"]).read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    model = _CONTRACT_MODELS[contract_id]

    for fixture_path in entry["fixtures"]["valid"]:
        payload = json.loads((contracts_root / fixture_path).read_text())
        validator.validate(payload)
        model.model_validate(payload)

    for fixture_path in entry["fixtures"]["invalid"]:
        payload = json.loads((contracts_root / fixture_path).read_text())
        assert list(validator.iter_errors(payload)), fixture_path
        with pytest.raises(ValidationError):
            model.model_validate(payload)
