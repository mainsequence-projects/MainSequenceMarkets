from __future__ import annotations

from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.services.command_center_adapter import (
    CONTRACT_OPERATION_ID,
    DIRECT_FRAME_CONTRACT,
    HEALTH_OPERATION_ID,
    MUTATION_OPERATION_IDS,
    PROVIDER_NATIVE_CONTRACT,
    QUERY_OPERATION_IDS,
)


def _contract_payload() -> dict:
    client = TestClient(app)
    response = client.get("/.well-known/command-center/connection-contract")

    assert response.status_code == 200
    return response.json()


def _operation_by_id(payload: dict) -> dict[str, dict]:
    return {operation["operationId"]: operation for operation in payload["availableOperations"]}


def _public_operation_ids(openapi_payload: dict) -> set[str]:
    operation_ids: set[str] = set()
    for path, path_item in openapi_payload["paths"].items():
        if path != "/health" and not path.startswith("/api/v1/"):
            continue
        for method in ("get", "post", "patch", "put", "delete"):
            operation = path_item.get(method)
            if operation is not None:
                operation_ids.add(operation["operationId"])
    return operation_ids


def test_health_response_shape() -> None:
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["service"] == "apps/v1"
    assert payload["version"]


def test_command_center_contract_exposes_required_control_metadata() -> None:
    payload = _contract_payload()
    operations = _operation_by_id(payload)

    assert payload["contractVersion"] == 1
    assert payload["adapter"]["type"] == "adapter-from-api"
    assert payload["adapter"]["id"] == "ms-markets.apps-v1"
    assert payload["openapi"]["url"].endswith("/openapi.json")
    assert payload["openapi"]["version"].startswith("3.")
    assert len(payload["openapi"]["checksum"]) == 64
    assert payload["configVariables"] == []
    assert payload["secretVariables"] == []
    assert payload["health"]["operationId"] == HEALTH_OPERATION_ID
    assert payload["health"]["expectedStatus"] == 200
    assert HEALTH_OPERATION_ID in operations
    assert CONTRACT_OPERATION_ID not in operations


def test_command_center_registry_matches_current_public_openapi_operations() -> None:
    client = TestClient(app)
    openapi_payload = client.get("/openapi.json").json()
    contract_payload = _contract_payload()

    public_operation_ids = _public_operation_ids(openapi_payload)
    contract_operation_ids = set(_operation_by_id(contract_payload))

    assert public_operation_ids <= contract_operation_ids
    assert QUERY_OPERATION_IDS <= public_operation_ids
    assert MUTATION_OPERATION_IDS <= public_operation_ids
    assert HEALTH_OPERATION_ID in public_operation_ids
    assert CONTRACT_OPERATION_ID not in contract_operation_ids


def test_command_center_contract_classifies_mutations_as_non_query_operations() -> None:
    payload = _contract_payload()
    operations = _operation_by_id(payload)

    for operation_id in sorted(MUTATION_OPERATION_IDS):
        operation = operations[operation_id]
        assert operation["kind"] == "mutation", operation_id
        assert operation["capabilities"] == ["mutation"], operation_id
        assert "query" not in operation["capabilities"], operation_id
        assert operation["cache"] == {"enabled": False, "ttlSeconds": None}, operation_id


def test_command_center_contract_classifies_read_operations_as_query_operations() -> None:
    payload = _contract_payload()
    operations = _operation_by_id(payload)

    for operation_id in sorted(QUERY_OPERATION_IDS):
        operation = operations[operation_id]
        assert operation["kind"] == "query", operation_id
        assert operation["capabilities"] == ["query"], operation_id

    assert operations["listAssets"]["supportsMaxRows"] is True
    assert operations["getAsset"]["supportsMaxRows"] is False
    assert operations["priceFixedIncomeAsset"]["method"] == "POST"
    assert operations["priceFixedIncomeAsset"]["requestBody"]["schemaRef"] == (
        "AssetPricingOperationRequest"
    )
    assert operations["priceFixedIncomeAsset"]["cache"] == {
        "enabled": False,
        "ttlSeconds": None,
    }


def test_command_center_contract_exposes_portfolio_group_operations() -> None:
    payload = _contract_payload()
    operations = _operation_by_id(payload)

    expected_query_operations = {
        "listPortfolioGroups": "GET",
        "getPortfolioGroup": "GET",
        "listGroupsForPortfolio": "GET",
        "listPortfoliosInGroup": "GET",
    }
    expected_mutation_operations = {
        "createPortfolioGroup": "POST",
        "updatePortfolioGroup": "PATCH",
        "deletePortfolioGroup": "DELETE",
        "bulkDeletePortfolioGroups": "POST",
        "addPortfolioToGroup": "POST",
        "removePortfolioFromGroup": "DELETE",
        "bulkDeletePortfolioGroupMemberships": "POST",
    }

    for operation_id, method in expected_query_operations.items():
        assert operations[operation_id]["method"] == method
        assert operations[operation_id]["kind"] == "query"
        assert operations[operation_id]["capabilities"] == ["query"]

    for operation_id, method in expected_mutation_operations.items():
        assert operations[operation_id]["method"] == method
        assert operations[operation_id]["kind"] == "mutation"
        assert operations[operation_id]["capabilities"] == ["mutation"]


def test_command_center_contract_exposes_complete_index_operations() -> None:
    operations = _operation_by_id(_contract_payload())
    query_operations = {
        "listIndexTypes": "GET",
        "getIndexType": "GET",
        "listIndexes": "GET",
        "getIndex": "GET",
        "getIndexSummary": "GET",
        "listIndexMethodologies": "GET",
        "getIndexMethodology": "GET",
        "listIndexDatasets": "GET",
        "getIndexDatasetSummary": "GET",
        "getIndexDatasetValuesFrame": "GET",
        "listIndexRelatedMetaTables": "GET",
        "getIndexDeleteImpact": "GET",
    }
    mutation_operations = {
        "createIndex": "POST",
        "updateIndex": "PATCH",
        "deleteIndex": "DELETE",
    }

    for operation_id, method in query_operations.items():
        assert operations[operation_id]["method"] == method
        assert operations[operation_id]["kind"] == "query"
    for operation_id, method in mutation_operations.items():
        assert operations[operation_id]["method"] == method
        assert operations[operation_id]["kind"] == "mutation"

    values = operations["getIndexDatasetValuesFrame"]
    assert values["responseContract"] == DIRECT_FRAME_CONTRACT
    assert values["responseModel"] == "TabularFrameResponse"


def test_command_center_contract_documents_response_contract_boundaries() -> None:
    payload = _contract_payload()
    operations = _operation_by_id(payload)

    direct_frame = operations["getFixedIncomeAssetCashflowsFrame"]
    assert direct_frame["responseContract"] == DIRECT_FRAME_CONTRACT
    assert direct_frame["responseModel"] == "TabularFrameResponse"

    portfolio_signal_weights = operations["getPortfolioSignalWeightsFrame"]
    assert portfolio_signal_weights["responseContract"] == DIRECT_FRAME_CONTRACT
    assert portfolio_signal_weights["responseModel"] == "TabularFrameResponse"

    portfolio_values = operations["getPortfolioValuesFrame"]
    assert portfolio_values["responseContract"] == DIRECT_FRAME_CONTRACT
    assert portfolio_values["responseModel"] == "TabularFrameResponse"

    asset_monitor = operations["getAssetMonitorFrame"]
    assert asset_monitor["responseContract"] == DIRECT_FRAME_CONTRACT
    assert asset_monitor["responseModel"] == "TabularFrameResponse"

    provider_native = operations["getFixedIncomeAssetCashflows"]
    assert provider_native["responseContract"] == PROVIDER_NATIVE_CONTRACT
    assert provider_native["responseModel"] == "BondCashflowsResponse"
    assert provider_native["responseMappings"][0]["contract"] == DIRECT_FRAME_CONTRACT
    assert provider_native["responseMappings"][0]["rowsPath"] == "$.legs.*[*]"


def test_command_center_contract_includes_parameter_and_body_metadata() -> None:
    payload = _contract_payload()
    operations = _operation_by_id(payload)

    list_assets_parameters = {
        parameter["name"]: parameter for parameter in operations["listAssets"]["parameters"]
    }
    assert list_assets_parameters["limit"]["in"] == "query"
    assert list_assets_parameters["limit"]["type"] == "integer"
    assert list_assets_parameters["offset"]["type"] == "integer"

    add_holdings = operations["addAccountHoldings"]
    assert add_holdings["requestBody"]["contentTypes"] == ["application/json"]
    assert add_holdings["requestBody"]["schemaRef"] == "AccountAddHoldingsRequest"
