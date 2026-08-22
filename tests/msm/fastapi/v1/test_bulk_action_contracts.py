from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError
from referencing import Registry, Resource

from apps.v1.schemas.bulk_actions import (
    BULK_ACTION_EXECUTION_CONTRACT,
    BULK_ACTION_PREFLIGHT_CONTRACT,
    BulkActionExecutionRequest,
    BulkActionPreflightResponse,
)
from apps.v1.schemas.resource_contracts import (
    RESOURCE_COLLECTION_CONTRACT,
    RESOURCE_DISCOVERY_CONTRACT,
    ResourceCollection,
    ResourceDiscovery,
)

COMMAND_CENTER_SDK_TAG = "v0.1.13"
COMMAND_CENTER_SDK_COMMIT = "f11c0ea8c5d3fc267997e476aa1522c798fdaced"
CONTRACTS_ROOT = (
    Path(__file__).parents[3] / "contracts" / "command-center-sdk-v0.1.13"
)

_CONTRACT_MODELS = {
    RESOURCE_COLLECTION_CONTRACT: ResourceCollection[dict[str, Any]],
    RESOURCE_DISCOVERY_CONTRACT: ResourceDiscovery,
    BULK_ACTION_EXECUTION_CONTRACT: BulkActionExecutionRequest,
    BULK_ACTION_PREFLIGHT_CONTRACT: BulkActionPreflightResponse,
}


def _schema_registry() -> Registry:
    schemas = [
        json.loads(path.read_text())
        for path in (CONTRACTS_ROOT / "schemas").glob("*.schema.json")
    ]
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )


def test_vendored_contract_bundle_is_pinned_to_latest_verified_revision() -> None:
    pin = (CONTRACTS_ROOT / "PINNED_FROM.txt").read_text()
    assert f"tag={COMMAND_CENTER_SDK_TAG}" in pin
    assert f"commit={COMMAND_CENTER_SDK_COMMIT}" in pin


@pytest.mark.parametrize("contract_id", sorted(_CONTRACT_MODELS))
def test_wire_models_match_authoritative_sdk_fixtures(contract_id: str) -> None:
    manifest = json.loads((CONTRACTS_ROOT / "manifest.json").read_text())
    entry = next(item for item in manifest["schemas"] if item["contract"] == contract_id)
    schema = json.loads((CONTRACTS_ROOT / entry["file"]).read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, registry=_schema_registry())
    model = _CONTRACT_MODELS[contract_id]

    for fixture_path in entry["fixtures"]["valid"]:
        payload = json.loads((CONTRACTS_ROOT / fixture_path).read_text())
        validator.validate(payload)
        model.model_validate(payload)

    for fixture_path in entry["fixtures"]["invalid"]:
        payload = json.loads((CONTRACTS_ROOT / fixture_path).read_text())
        assert list(validator.iter_errors(payload)), fixture_path
        with pytest.raises(ValidationError):
            model.model_validate(payload)
