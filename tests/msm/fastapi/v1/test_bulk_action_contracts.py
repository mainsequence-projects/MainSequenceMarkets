from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ValidationError
from referencing import Registry, Resource

from msm.api.http import (
    BULK_ACTION_EXECUTION_CONTRACT,
    BULK_ACTION_PREFLIGHT_CONTRACT,
    CORE_TABULAR_FRAME_CONTRACT,
    BulkActionDefinition,
    BulkActionExecutionRequest,
    BulkActionPreflightResponse,
    RESOURCE_COLLECTION_CONTRACT,
    RESOURCE_DISCOVERY_CONTRACT,
    ResourceCollection,
    ResourceColumn,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceIdentity,
    ResourceListControls,
    ResourceListDiscovery,
    ResourceSearchControl,
    TabularFrameResponse,
)

COMMAND_CENTER_SDK_TAG = "v0.1.13"
COMMAND_CENTER_SDK_COMMIT = "f11c0ea8c5d3fc267997e476aa1522c798fdaced"
CONTRACTS_ROOT = Path(__file__).parents[3] / "contracts" / "command-center-sdk-v0.1.13"

_CONTRACT_MODELS = {
    RESOURCE_COLLECTION_CONTRACT: ResourceCollection[dict[str, Any]],
    RESOURCE_DISCOVERY_CONTRACT: ResourceDiscovery,
    BULK_ACTION_EXECUTION_CONTRACT: BulkActionExecutionRequest,
    BULK_ACTION_PREFLIGHT_CONTRACT: BulkActionPreflightResponse,
    CORE_TABULAR_FRAME_CONTRACT: TabularFrameResponse,
}


def _schema_registry() -> Registry:
    schemas = [
        json.loads(path.read_text()) for path in (CONTRACTS_ROOT / "schemas").glob("*.schema.json")
    ]
    return Registry().with_resources(
        (schema["$id"], Resource.from_contents(schema)) for schema in schemas
    )


def test_vendored_contract_bundle_is_pinned_to_latest_verified_revision() -> None:
    pin = (CONTRACTS_ROOT / "PINNED_FROM.txt").read_text()
    assert f"tag={COMMAND_CENTER_SDK_TAG}" in pin
    assert f"commit={COMMAND_CENTER_SDK_COMMIT}" in pin


def _manifest_entry(contract_id: str) -> dict[str, Any]:
    manifest = json.loads((CONTRACTS_ROOT / "manifest.json").read_text())
    return next(item for item in manifest["schemas"] if item["contract"] == contract_id)


def _contract_validator(contract_id: str) -> Draft202012Validator:
    schema = json.loads((CONTRACTS_ROOT / _manifest_entry(contract_id)["file"]).read_text())
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=_schema_registry())


def _null_paths(value: Any, path: str = "$") -> list[str]:
    if value is None:
        return [path]
    if isinstance(value, dict):
        return [
            null_path
            for key, item in value.items()
            for null_path in _null_paths(item, f"{path}.{key}")
        ]
    if isinstance(value, list):
        return [
            null_path
            for index, item in enumerate(value)
            for null_path in _null_paths(item, f"{path}[{index}]")
        ]
    return []


@pytest.mark.parametrize("contract_id", sorted(_CONTRACT_MODELS))
def test_wire_models_match_authoritative_sdk_fixtures(contract_id: str) -> None:
    entry = _manifest_entry(contract_id)
    validator = _contract_validator(contract_id)
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


_REQUIRED_ONLY_ACTION = BulkActionDefinition(
    id="refresh",
    label="Refresh",
    endpoint="/v1/records/actions/refresh",
    method="POST",
    selection_modes=["explicit"],
    options=[],
)


@pytest.mark.parametrize(
    ("contract_id", "model"),
    [
        (
            RESOURCE_DISCOVERY_CONTRACT,
            ResourceDiscovery(
                resource=ResourceDescriptor(
                    id="records",
                    label="Records",
                    item_label="record",
                    identity=ResourceIdentity(fields=["uid"]),
                ),
                list=ResourceListDiscovery(
                    controls=ResourceListControls(
                        search=ResourceSearchControl(placeholder="Search", fields=["uid"]),
                        filters=[],
                        ordering=[],
                    ),
                    columns=[ResourceColumn(id="uid", header="UID")],
                ),
                bulk_actions=[_REQUIRED_ONLY_ACTION],
            ),
        ),
        (BULK_ACTION_PREFLIGHT_CONTRACT, BulkActionPreflightResponse(allowed=True)),
    ],
    ids=["resource-discovery", "bulk-action-preflight"],
)
def test_wire_models_omit_unset_optional_fields(contract_id: str, model: BaseModel) -> None:
    """The SDK accepts optional contract fields only when absent or valid, never null."""

    payload = model.model_dump(mode="json", by_alias=True)

    assert _null_paths(payload) == []
    _contract_validator(contract_id).validate(payload)
