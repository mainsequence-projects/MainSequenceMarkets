from __future__ import annotations

from fastapi.testclient import TestClient

from apps.v1.main import app


def _assert_paginated_schema(
    payload: dict,
    *,
    schema_ref: str,
    result_ref: str,
) -> None:
    schema_name = schema_ref.removeprefix("#/components/schemas/")
    schema = payload["components"]["schemas"][schema_name]
    assert schema["properties"]["count"]["type"] == "integer"
    assert schema["properties"]["next"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert schema["properties"]["previous"]["anyOf"] == [
        {"type": "string"},
        {"type": "null"},
    ]
    assert schema["properties"]["results"]["items"] == {"$ref": result_ref}


def _resolve_schema_ref(payload: dict, schema: dict) -> dict:
    ref = schema.get("$ref")
    if ref is None:
        return schema
    return payload["components"]["schemas"][ref.removeprefix("#/components/schemas/")]


def test_openapi_json_exposes_core_api_metadata() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    assert payload["openapi"].startswith("3.")
    assert payload["info"]["title"] == "MainSequence Markets Public API"
    assert payload["info"]["version"]
    assert payload["info"]["x-app-scope"] == "apps/v1"
    assert payload["servers"] == [{"url": "/", "description": "Current deployment"}]


def test_openapi_json_uses_one_contract_for_limit_offset_pagination() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    checked_paths = []
    for path, path_item in payload["paths"].items():
        operation = path_item.get("get")
        if operation is None:
            continue
        parameter_names = {parameter["name"] for parameter in operation.get("parameters", [])}
        if not {"limit", "offset"}.issubset(parameter_names):
            continue

        schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        resolved_schema = _resolve_schema_ref(payload, schema)
        assert {"count", "next", "previous", "results"}.issubset(resolved_schema["properties"]), (
            path
        )
        assert "limit" not in resolved_schema["properties"], path
        assert "offset" not in resolved_schema["properties"], path
        checked_paths.append(path)

    assert set(checked_paths) == {
        "/api/v1/account/",
        "/api/v1/account/target-allocation/targets/",
        "/api/v1/asset/",
        "/api/v1/asset-category/",
        "/api/v1/calendar/",
        "/api/v1/calendar/{calendar_uid}/dates/",
        "/api/v1/calendar/{calendar_uid}/events/",
        "/api/v1/calendar/{calendar_uid}/sessions/",
        "/api/v1/index/",
        "/api/v1/portfolio/",
        "/api/v1/portfolio-signal/",
        "/api/v1/pricing/curves/",
        "/api/v1/pricing/market_data/bindings/",
        "/api/v1/pricing/market_data/sets/",
        "/api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/",
        "/api/v1/virtualfund/",
    }


def test_openapi_json_documents_asset_list_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    asset_list_operation = payload["paths"]["/api/v1/asset/"]["get"]
    assert asset_list_operation["summary"] == "List assets"
    assert asset_list_operation["operationId"] == "listAssets"
    assert asset_list_operation["tags"] == ["asset"]
    assert asset_list_operation["parameters"][0]["name"] == "response_format"
    assert asset_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PaginatedResponse_Asset_"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_Asset_",
        result_ref="#/components/schemas/Asset",
    )
    assert asset_list_operation["responses"]["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    asset_detail_operation = payload["paths"]["/api/v1/asset/{uid}/"]["get"]
    assert asset_detail_operation["summary"] == "Get asset"
    assert asset_detail_operation["operationId"] == "getAsset"
    assert asset_detail_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AssetDetailResponse"
    }
    assert asset_detail_operation["responses"]["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    assert asset_detail_operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    asset_delete_operation = payload["paths"]["/api/v1/asset/{uid}/"]["delete"]
    assert asset_delete_operation["summary"] == "Delete asset"
    assert asset_delete_operation["operationId"] == "deleteAsset"
    assert asset_delete_operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    asset_summary_operation = payload["paths"]["/api/v1/asset/{uid}/summary/"]["get"]
    assert asset_summary_operation["summary"] == "Get asset summary"
    assert asset_summary_operation["operationId"] == "getAssetSummary"
    assert asset_summary_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FrontEndDetailSummary"
    }

    asset_pricing_details_operation = payload["paths"]["/api/v1/asset/{uid}/get_pricing_details/"][
        "get"
    ]
    assert asset_pricing_details_operation["summary"] == "Get asset pricing details"
    assert asset_pricing_details_operation["operationId"] == "getAssetPricingDetails"
    assert asset_pricing_details_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AssetCurrentPricingDetailsResponse"}


def test_openapi_json_documents_fixed_income_pricing_asset_endpoints() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    expected_operations = {
        "/api/v1/pricing/assets/{asset_uid}/price/": (
            "priceFixedIncomeAsset",
            "BondPriceResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/analytics/": (
            "getFixedIncomeAssetAnalytics",
            "BondAnalyticsResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/duration/": (
            "getFixedIncomeAssetDuration",
            "BondDurationResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/yield/": (
            "getFixedIncomeAssetYield",
            "BondYieldResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/z-spread/": (
            "getFixedIncomeAssetZSpread",
            "BondZSpreadResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/cashflows/": (
            "getFixedIncomeAssetCashflows",
            "BondCashflowsResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/cashflows/frame/": (
            "getFixedIncomeAssetCashflowsFrame",
            "TabularFrameResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/net-cashflows/": (
            "getFixedIncomeAssetNetCashflows",
            "BondNetCashflowsResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/net-cashflows/frame/": (
            "getFixedIncomeAssetNetCashflowsFrame",
            "TabularFrameResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/carry-roll-down/": (
            "getFixedIncomeAssetCarryRollDown",
            "BondCarryRollDownResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/curve-preview/": (
            "previewFixedIncomeAssetCurve",
            "BondCurvePreviewResponse",
        ),
        "/api/v1/pricing/assets/{asset_uid}/fixings-availability/": (
            "checkFixedIncomeAssetFixingsAvailability",
            "BondFixingsAvailabilityResponse",
        ),
    }

    for path, (operation_id, response_model) in expected_operations.items():
        operation = payload["paths"][path]["post"]
        assert operation["operationId"] == operation_id
        assert operation["requestBody"]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/AssetPricingOperationRequest"
        }
        assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
            "$ref": f"#/components/schemas/{response_model}"
        }

    request_schema = payload["components"]["schemas"]["AssetPricingOperationRequest"]
    assert request_schema["x-command-center-consumer"] == "app-component"
    assert request_schema["x-ui-form-source"] == "openapi-request-body"
    assert request_schema["properties"]["valuation_date"]["x-ui-field-kind"] == "date-time"
    assert request_schema["properties"]["valuation_date"]["x-ui-token"] == (
        "pricing.valuation_date"
    )
    assert request_schema["properties"]["parameters"]["x-ui-field-kind"] == "json"

    price_schema = payload["components"]["schemas"]["BondPriceResponse"]
    assert price_schema["x-command-center-consumer"] == "app-component"
    assert price_schema["x-ui-output-root"] == "response:$"
    assert price_schema["x-ui-response-mode"] == "provider-native-json"
    assert price_schema["x-ui-flat-outputs"] == ["price", "units"]

    cashflows_schema = payload["components"]["schemas"]["BondCashflowsResponse"]
    assert cashflows_schema["x-response-mappings"][0]["contract"] == "core.tabular_frame@v1"
    assert cashflows_schema["x-response-mappings"][0]["rowsPath"] == "$.legs.*[*]"

    cashflows_frame_operation = payload["paths"][
        "/api/v1/pricing/assets/{asset_uid}/cashflows/frame/"
    ]["post"]
    assert cashflows_frame_operation["x-ui-contract"] == "core.tabular_frame@v1"
    assert cashflows_frame_operation["x-ui-output-root"] == "response:$"


def test_openapi_json_documents_account_list_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    account_list_operation = payload["paths"]["/api/v1/account/"]["get"]
    assert account_list_operation["summary"] == "List accounts"
    assert account_list_operation["operationId"] == "listAccounts"
    assert account_list_operation["tags"] == ["account"]
    assert account_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountListResponse"
    }
    account_list_schema = payload["components"]["schemas"]["AccountListResponse"]
    assert account_list_schema["properties"]["results"]["items"] == {
        "$ref": "#/components/schemas/Account"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/AccountListResponse",
        result_ref="#/components/schemas/Account",
    )

    account_summary_operation = payload["paths"]["/api/v1/account/{uid}/summary/"]["get"]
    assert account_summary_operation["summary"] == "Get account summary"
    assert account_summary_operation["operationId"] == "getAccountSummary"
    assert account_summary_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/FrontEndDetailSummary"}

    target_candidates_operation = payload["paths"]["/api/v1/account/target-allocation/targets/"][
        "get"
    ]
    assert target_candidates_operation["summary"] == ("Search account target-allocation targets")
    assert target_candidates_operation["operationId"] == "searchAccountTargetAllocationTargets"
    assert target_candidates_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AccountTargetAllocationCandidateResponse"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/AccountTargetAllocationCandidateResponse",
        result_ref="#/components/schemas/AccountTargetAllocationCandidate",
    )

    add_holdings_operation = payload["paths"]["/api/v1/account/{account_uid}/add-holdings/"]["post"]
    assert add_holdings_operation["summary"] == "Add account holdings snapshot"
    assert add_holdings_operation["operationId"] == "addAccountHoldings"
    assert add_holdings_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountAddHoldingsRequest"
    }
    assert add_holdings_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/AccountHoldingsSnapshotResponse"
    }

    holdings_by_fund_operation = payload["paths"][
        "/api/v1/account/{account_uid}/holdings/by-fund/"
    ]["get"]
    assert holdings_by_fund_operation["summary"] == ("Get account holdings grouped by virtual fund")
    assert holdings_by_fund_operation["operationId"] == "getAccountHoldingsByFund"
    assert holdings_by_fund_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AccountHoldingsByFundResponse"}

    add_target_positions_operation = payload["paths"][
        "/api/v1/account/{account_uid}/add-target-positions/"
    ]["post"]
    assert add_target_positions_operation["summary"] == ("Add account target positions snapshot")
    assert add_target_positions_operation["operationId"] == "addAccountTargetPositions"
    assert add_target_positions_operation["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AccountAddTargetPositionsRequest"}
    assert add_target_positions_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AccountTargetPositionsSnapshotResponse"}

    account_target_positions_operation = payload["paths"][
        "/api/v1/account/{account_uid}/target-positions/"
    ]["get"]
    assert account_target_positions_operation["summary"] == (
        "Get account target positions snapshot"
    )
    assert account_target_positions_operation["operationId"] == "getAccountTargetPositions"
    assert account_target_positions_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AccountTargetPositionsSnapshotResponse"}


def test_openapi_json_documents_virtualfund_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    virtualfund_list_operation = payload["paths"]["/api/v1/virtualfund/"]["get"]
    assert virtualfund_list_operation["summary"] == "List virtual funds"
    assert virtualfund_list_operation["operationId"] == "listVirtualFunds"
    assert virtualfund_list_operation["tags"] == ["virtualfund"]
    assert virtualfund_list_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/VirtualFundListResponse"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/VirtualFundListResponse",
        result_ref="#/components/schemas/VirtualFund",
    )

    virtualfund_detail_operation = payload["paths"]["/api/v1/virtualfund/{uid}/"]["get"]
    assert virtualfund_detail_operation["summary"] == "Get virtual fund"
    assert virtualfund_detail_operation["operationId"] == "getVirtualFund"
    assert virtualfund_detail_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/VirtualFundDetailResponse"}

    virtualfund_holdings_operation = payload["paths"]["/api/v1/virtualfund/{uid}/holdings/"]["get"]
    assert virtualfund_holdings_operation["summary"] == "Get virtual fund holdings snapshot"
    assert virtualfund_holdings_operation["operationId"] == "getVirtualFundHoldings"
    assert virtualfund_holdings_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/VirtualFundHoldingsSnapshotResponse"}


def test_openapi_json_documents_asset_category_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    asset_category_list_operation = payload["paths"]["/api/v1/asset-category/"]["get"]
    assert asset_category_list_operation["summary"] == "List asset categories"
    assert asset_category_list_operation["operationId"] == "listAssetCategories"
    assert asset_category_list_operation["tags"] == ["asset-category"]
    assert asset_category_list_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PaginatedResponse_AssetCategory_"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_AssetCategory_",
        result_ref="#/components/schemas/AssetCategory",
    )

    asset_category_detail_operation = payload["paths"]["/api/v1/asset-category/{uid}/"]["get"]
    assert asset_category_detail_operation["summary"] == "Get asset category detail"
    assert asset_category_detail_operation["operationId"] == "getAssetCategoryDetail"
    assert asset_category_detail_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/AssetCategoryDetailResponse"}

    asset_category_bulk_delete_operation = payload["paths"]["/api/v1/asset-category/bulk-delete/"][
        "post"
    ]
    assert asset_category_bulk_delete_operation["summary"] == "Bulk delete asset categories"
    assert asset_category_bulk_delete_operation["operationId"] == "bulkDeleteAssetCategories"
    assert asset_category_bulk_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/BulkDeleteAssetCategoriesResponse"}


def test_openapi_json_documents_index_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    index_list_operation = payload["paths"]["/api/v1/index/"]["get"]
    assert index_list_operation["summary"] == "List indexes"
    assert index_list_operation["operationId"] == "listIndexes"
    assert index_list_operation["tags"] == ["index"]
    assert index_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PaginatedResponse_Index_"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_Index_",
        result_ref="#/components/schemas/Index",
    )

    index_detail_operation = payload["paths"]["/api/v1/index/{uid}/"]["get"]
    assert index_detail_operation["summary"] == "Get index"
    assert index_detail_operation["operationId"] == "getIndex"
    assert index_detail_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Index"
    }

    index_delete_operation = payload["paths"]["/api/v1/index/{uid}/"]["delete"]
    assert index_delete_operation["summary"] == "Delete index"
    assert index_delete_operation["operationId"] == "deleteIndex"
    assert index_delete_operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }


def test_openapi_json_documents_portfolio_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    portfolio_list_operation = payload["paths"]["/api/v1/portfolio/"]["get"]
    assert portfolio_list_operation["summary"] == "List portfolios"
    assert portfolio_list_operation["operationId"] == "listPortfolios"
    assert portfolio_list_operation["tags"] == ["portfolio"]
    assert portfolio_list_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PaginatedResponse_Portfolio_"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_Portfolio_",
        result_ref="#/components/schemas/Portfolio",
    )

    portfolio_detail_operation = payload["paths"]["/api/v1/portfolio/{uid}/"]["get"]
    assert portfolio_detail_operation["summary"] == "Get portfolio detail"
    assert portfolio_detail_operation["operationId"] == "getPortfolio"
    assert portfolio_detail_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioDetailResponse"}

    portfolio_summary_operation = payload["paths"]["/api/v1/portfolio/{uid}/summary/"]["get"]
    assert portfolio_summary_operation["summary"] == "Get portfolio summary"
    assert portfolio_summary_operation["operationId"] == "getPortfolioSummary"
    assert portfolio_summary_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/FrontEndDetailSummary"}

    portfolio_weights_operation = payload["paths"]["/api/v1/portfolio/{uid}/weights/"]["get"]
    assert portfolio_weights_operation["summary"] == "Get portfolio weights snapshot"
    assert portfolio_weights_operation["operationId"] == "getPortfolioWeights"
    assert portfolio_weights_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioWeightsSnapshotResponse"}

    portfolio_signal_weights_operation = payload["paths"][
        "/api/v1/portfolio/{uid}/signals_weights/"
    ]["get"]
    assert portfolio_signal_weights_operation["summary"] == ("Get portfolio signal weights frame")
    assert portfolio_signal_weights_operation["operationId"] == ("getPortfolioSignalWeightsFrame")
    assert portfolio_signal_weights_operation["x-ui-contract"] == "core.tabular_frame@v1"
    assert portfolio_signal_weights_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/TabularFrameResponse"}

    portfolio_values_operation = payload["paths"]["/api/v1/portfolio/{uid}/portfolio_values/"][
        "get"
    ]
    assert portfolio_values_operation["summary"] == "Get portfolio values frame"
    assert portfolio_values_operation["operationId"] == "getPortfolioValuesFrame"
    assert portfolio_values_operation["x-ui-contract"] == "core.tabular_frame@v1"
    assert portfolio_values_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/TabularFrameResponse"}

    portfolio_weights_delete_operation = payload["paths"]["/api/v1/portfolio/{uid}/weights/"][
        "delete"
    ]
    assert portfolio_weights_delete_operation["summary"] == "Delete portfolio weights"
    assert portfolio_weights_delete_operation["operationId"] == "deletePortfolioWeights"
    assert portfolio_weights_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioWeightsDeleteResponse"}
    assert "409" not in portfolio_weights_delete_operation["responses"]

    portfolio_delete_operation = payload["paths"]["/api/v1/portfolio/{uid}/"]["delete"]
    assert portfolio_delete_operation["summary"] == "Delete portfolio"
    assert portfolio_delete_operation["operationId"] == "deletePortfolio"
    assert portfolio_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioDeleteResponse"}
    assert portfolio_delete_operation["responses"]["409"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}

    portfolio_bulk_delete_operation = payload["paths"]["/api/v1/portfolio/bulk-delete/"]["post"]
    assert portfolio_bulk_delete_operation["summary"] == "Bulk delete portfolios"
    assert portfolio_bulk_delete_operation["operationId"] == "bulkDeletePortfolios"
    assert portfolio_bulk_delete_operation["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioDeleteRequest"}
    assert portfolio_bulk_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioBulkDeleteResponse"}

    portfolio_bulk_cascade_delete_operation = payload["paths"][
        "/api/v1/portfolio/bulk-cascade-delete/"
    ]["post"]
    assert portfolio_bulk_cascade_delete_operation["summary"] == "Cascade delete portfolios"
    assert (
        portfolio_bulk_cascade_delete_operation["operationId"]
        == "bulkCascadeDeletePortfolios"
    )
    assert portfolio_bulk_cascade_delete_operation["requestBody"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioDeleteRequest"}
    assert portfolio_bulk_cascade_delete_operation["responses"]["200"]["content"][
        "application/json"
    ]["schema"] == {"$ref": "#/components/schemas/PortfolioBulkCascadeDeleteResponse"}


def test_openapi_json_documents_portfolio_signal_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    signal_list_operation = payload["paths"]["/api/v1/portfolio-signal/"]["get"]
    assert signal_list_operation["summary"] == "List portfolio signals"
    assert signal_list_operation["operationId"] == "listPortfolioSignals"
    assert signal_list_operation["tags"] == ["portfolio-signal"]
    assert signal_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PaginatedResponse_SignalMetadata_"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_SignalMetadata_",
        result_ref="#/components/schemas/SignalMetadata",
    )

    signal_create_operation = payload["paths"]["/api/v1/portfolio-signal/"]["post"]
    assert signal_create_operation["summary"] == "Create portfolio signal"
    assert signal_create_operation["operationId"] == "createPortfolioSignal"
    assert signal_create_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMetadataCreate"
    }
    assert signal_create_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMetadata"
    }

    signal_detail_operation = payload["paths"]["/api/v1/portfolio-signal/{uid}/"]["get"]
    assert signal_detail_operation["summary"] == "Get portfolio signal"
    assert signal_detail_operation["operationId"] == "getPortfolioSignal"
    assert signal_detail_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMetadata"
    }

    signal_update_operation = payload["paths"]["/api/v1/portfolio-signal/{uid}/"]["patch"]
    assert signal_update_operation["summary"] == "Update portfolio signal"
    assert signal_update_operation["operationId"] == "updatePortfolioSignal"
    assert signal_update_operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/SignalMetadataUpdate"
    }

    signal_delete_operation = payload["paths"]["/api/v1/portfolio-signal/{uid}/"]["delete"]
    assert signal_delete_operation["summary"] == "Delete portfolio signal"
    assert signal_delete_operation["operationId"] == "deletePortfolioSignal"
    assert signal_delete_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PortfolioSignalDeleteResponse"
    }
    assert signal_delete_operation["responses"]["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    signal_weights_delete_operation = payload["paths"]["/api/v1/portfolio-signal/{uid}/weights/"][
        "delete"
    ]
    assert signal_weights_delete_operation["summary"] == "Delete portfolio signal weights"
    assert signal_weights_delete_operation["operationId"] == "deletePortfolioSignalWeights"
    assert signal_weights_delete_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PortfolioSignalWeightsDeleteResponse"}


def test_openapi_json_documents_calendar_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    calendar_list_operation = payload["paths"]["/api/v1/calendar/"]["get"]
    assert calendar_list_operation["summary"] == "List calendars"
    assert calendar_list_operation["operationId"] == "listCalendars"
    assert calendar_list_operation["tags"] == ["calendar"]
    assert calendar_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PaginatedResponse_Calendar_"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_Calendar_",
        result_ref="#/components/schemas/Calendar",
    )

    calendar_dates_operation = payload["paths"]["/api/v1/calendar/{calendar_uid}/dates/"]["get"]
    assert calendar_dates_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PaginatedResponse_CalendarDate_"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_CalendarDate_",
        result_ref="#/components/schemas/CalendarDate",
    )

    calendar_sessions_operation = payload["paths"]["/api/v1/calendar/{calendar_uid}/sessions/"][
        "get"
    ]
    assert calendar_sessions_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PaginatedResponse_CalendarSession_"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_CalendarSession_",
        result_ref="#/components/schemas/CalendarSession",
    )

    calendar_events_operation = payload["paths"]["/api/v1/calendar/{calendar_uid}/events/"]["get"]
    assert calendar_events_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PaginatedResponse_CalendarEvent_"}
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PaginatedResponse_CalendarEvent_",
        result_ref="#/components/schemas/CalendarEvent",
    )

    calendar_summary_operation = payload["paths"]["/api/v1/calendar/{uid}/summary/"]["get"]
    assert calendar_summary_operation["summary"] == "Get calendar summary"
    assert calendar_summary_operation["operationId"] == "getCalendarSummary"
    assert calendar_summary_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/FrontEndDetailSummary"}
    assert calendar_summary_operation["responses"]["404"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}


def test_openapi_json_documents_pricing_curve_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    curve_list_operation = payload["paths"]["/api/v1/pricing/curves/"]["get"]
    assert curve_list_operation["summary"] == "List pricing curves"
    assert curve_list_operation["operationId"] == "listPricingCurves"
    assert curve_list_operation["tags"] == ["pricing-curve"]
    assert curve_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/CurveListResponse"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/CurveListResponse",
        result_ref="#/components/schemas/Curve",
    )

    curve_summary_operation = payload["paths"]["/api/v1/pricing/curves/{uid}/summary/"]["get"]
    assert curve_summary_operation["summary"] == "Get pricing curve summary"
    assert curve_summary_operation["operationId"] == "getPricingCurveSummary"
    assert curve_summary_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/FrontEndDetailSummary"
    }
    assert curve_summary_operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    discount_curve_operation = payload["paths"]["/api/v1/pricing/curves/{uid}/discount-curve/"][
        "get"
    ]
    assert discount_curve_operation["summary"] == "Get pricing discount curve"
    assert discount_curve_operation["operationId"] == "getPricingDiscountCurve"
    assert discount_curve_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/DiscountCurveResponse"}
    assert discount_curve_operation["responses"]["404"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}


def test_openapi_json_documents_pricing_market_data_routes() -> None:
    client = TestClient(app)
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()

    card_operation = payload["paths"]["/api/v1/pricing/market_data/"]["get"]
    assert card_operation["summary"] == "Get pricing market-data API card"
    assert card_operation["operationId"] == "getPricingMarketDataCard"
    assert card_operation["tags"] == ["pricing-market-data"]
    assert card_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PricingMarketDataCardResponse"
    }

    set_list_operation = payload["paths"]["/api/v1/pricing/market_data/sets/"]["get"]
    assert set_list_operation["summary"] == "List pricing market-data sets"
    assert set_list_operation["operationId"] == "listPricingMarketDataSets"
    assert set_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PricingMarketDataSetListResponse"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PricingMarketDataSetListResponse",
        result_ref="#/components/schemas/PricingMarketDataSet",
    )

    set_detail_operation = payload["paths"]["/api/v1/pricing/market_data/sets/{uid}/"]["get"]
    assert set_detail_operation["summary"] == "Get pricing market-data set"
    assert set_detail_operation["operationId"] == "getPricingMarketDataSet"
    assert set_detail_operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }

    set_key_operation = payload["paths"]["/api/v1/pricing/market_data/sets/by-key/{set_key}/"][
        "get"
    ]
    assert set_key_operation["summary"] == "Get pricing market-data set by key"
    assert set_key_operation["operationId"] == "getPricingMarketDataSetByKey"

    assert (
        payload["paths"]["/api/v1/pricing/market_data/sets/"]["post"]["operationId"]
        == "createPricingMarketDataSet"
    )
    assert (
        payload["paths"]["/api/v1/pricing/market_data/sets/upsert/"]["post"]["operationId"]
        == "upsertPricingMarketDataSet"
    )
    assert (
        payload["paths"]["/api/v1/pricing/market_data/sets/{uid}/"]["patch"]["operationId"]
        == "updatePricingMarketDataSet"
    )
    assert (
        payload["paths"]["/api/v1/pricing/market_data/sets/{uid}/"]["delete"]["operationId"]
        == "deletePricingMarketDataSet"
    )
    assert payload["paths"]["/api/v1/pricing/market_data/sets/{uid}/"]["delete"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PricingMarketDataSetDeleteResponse"
    }

    binding_list_operation = payload["paths"]["/api/v1/pricing/market_data/bindings/"]["get"]
    assert binding_list_operation["summary"] == "List pricing market-data bindings"
    assert binding_list_operation["operationId"] == "listPricingMarketDataBindings"
    assert binding_list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PricingMarketDataSetBindingListResponse"
    }
    _assert_paginated_schema(
        payload,
        schema_ref="#/components/schemas/PricingMarketDataSetBindingListResponse",
        result_ref="#/components/schemas/PricingMarketDataSetBinding",
    )

    nested_binding_list_operation = payload["paths"][
        "/api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/"
    ]["get"]
    assert nested_binding_list_operation["summary"] == ("List pricing market-data set bindings")
    assert nested_binding_list_operation["operationId"] == ("listPricingMarketDataSetBindings")
    assert nested_binding_list_operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/PricingMarketDataSetBindingListResponse"}

    resolve_operation = payload["paths"]["/api/v1/pricing/market_data/bindings/resolve/"]["get"]
    assert resolve_operation["summary"] == "Resolve pricing market-data binding"
    assert resolve_operation["operationId"] == "resolvePricingMarketDataBinding"
    assert resolve_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PricingMarketDataBindingResolveResponse"
    }

    binding_detail_operation = payload["paths"]["/api/v1/pricing/market_data/bindings/{uid}/"][
        "get"
    ]
    assert binding_detail_operation["summary"] == "Get pricing market-data binding"
    assert binding_detail_operation["operationId"] == "getPricingMarketDataBinding"
    assert binding_detail_operation["responses"]["404"]["content"]["application/json"][
        "schema"
    ] == {"$ref": "#/components/schemas/ErrorResponse"}

    assert (
        payload["paths"]["/api/v1/pricing/market_data/bindings/"]["post"]["operationId"]
        == "createPricingMarketDataBinding"
    )
    assert (
        payload["paths"]["/api/v1/pricing/market_data/bindings/upsert/"]["post"]["operationId"]
        == "upsertPricingMarketDataBinding"
    )
    assert (
        payload["paths"]["/api/v1/pricing/market_data/bindings/{uid}/"]["patch"]["operationId"]
        == "updatePricingMarketDataBinding"
    )
    assert (
        payload["paths"]["/api/v1/pricing/market_data/bindings/{uid}/"]["delete"]["operationId"]
        == "deletePricingMarketDataBinding"
    )
    assert payload["paths"]["/api/v1/pricing/market_data/bindings/{uid}/"]["delete"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PricingMarketDataSetBindingDeleteResponse"
    }
