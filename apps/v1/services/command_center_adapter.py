from __future__ import annotations

import hashlib
import json
from importlib.metadata import version
from typing import Any

from apps.v1.schemas.command_center_adapter import (
    ApiHealthResponse,
    CommandCenterAdapterInfo,
    CommandCenterConnectionContract,
    CommandCenterHealthOperation,
    CommandCenterOpenApiInfo,
    CommandCenterOperation,
    CommandCenterOperationCache,
    CommandCenterOperationParameter,
    CommandCenterOperationRequestBody,
    CommandCenterResponseMapping,
)

ADAPTER_ID = "ms-markets.apps-v1"
ADAPTER_TITLE = "MainSequence Markets API"
ADAPTER_DESCRIPTION = "Adapter contract for the apps/v1 markets FastAPI surface."
CONTRACT_VERSION = 1
HEALTH_OPERATION_ID = "getApiHealth"
CONTRACT_OPERATION_ID = "getCommandCenterConnectionContract"
DIRECT_FRAME_CONTRACT = "core.tabular_frame@v1"
PROVIDER_NATIVE_CONTRACT = "provider-native-json"

QUERY_OPERATION_IDS = frozenset(
    {
        "getApiSettings",
        "listAssets",
        "getAsset",
        "getAssetSummary",
        "getAssetPricingDetails",
        "listAssetCategories",
        "getAssetCategoryDetail",
        "listAccounts",
        "getAccountSummary",
        "searchAccountTargetAllocationTargets",
        "getAccountHoldings",
        "getAccountHoldingsByFund",
        "getAccountTargetPositions",
        "listIndexes",
        "getIndex",
        "listPortfolios",
        "getPortfolio",
        "getPortfolioSummary",
        "getPortfolioWeights",
        "listVirtualFunds",
        "getVirtualFund",
        "getVirtualFundSummary",
        "getVirtualFundHoldings",
        "listCalendars",
        "getCalendar",
        "getCalendarSummary",
        "listCalendarDates",
        "getCalendarDate",
        "listCalendarSessions",
        "getCalendarSession",
        "listCalendarEvents",
        "getCalendarEvent",
        "listPricingCurves",
        "getPricingCurveSummary",
        "getPricingDiscountCurve",
        "getPricingMarketDataCard",
        "listPricingMarketDataSets",
        "getPricingMarketDataSetByKey",
        "getPricingMarketDataSet",
        "listPricingMarketDataBindings",
        "listPricingMarketDataSetBindings",
        "resolvePricingMarketDataBinding",
        "getPricingMarketDataBinding",
        "priceFixedIncomeAsset",
        "getFixedIncomeAssetAnalytics",
        "getFixedIncomeAssetDuration",
        "getFixedIncomeAssetYield",
        "getFixedIncomeAssetZSpread",
        "getFixedIncomeAssetCashflows",
        "getFixedIncomeAssetCashflowsFrame",
        "getFixedIncomeAssetNetCashflows",
        "getFixedIncomeAssetNetCashflowsFrame",
        "getFixedIncomeAssetCarryRollDown",
        "previewFixedIncomeAssetCurve",
        "checkFixedIncomeAssetFixingsAvailability",
    }
)

MUTATION_OPERATION_IDS = frozenset(
    {
        "deleteAsset",
        "createAssetCategory",
        "bulkDeleteAssetCategories",
        "updateAssetCategory",
        "deleteAssetCategory",
        "addAccountHoldings",
        "addAccountTargetPositions",
        "deleteIndex",
        "bulkDeletePortfolios",
        "deletePortfolio",
        "createCalendar",
        "updateCalendar",
        "deleteCalendar",
        "createCalendarDate",
        "bulkUpsertCalendarDates",
        "updateCalendarDate",
        "deleteCalendarDate",
        "createCalendarSession",
        "bulkUpsertCalendarSessions",
        "updateCalendarSession",
        "deleteCalendarSession",
        "createCalendarEvent",
        "bulkUpsertCalendarEvents",
        "updateCalendarEvent",
        "deleteCalendarEvent",
        "createPricingMarketDataSet",
        "upsertPricingMarketDataSet",
        "updatePricingMarketDataSet",
        "deletePricingMarketDataSet",
        "createPricingMarketDataBinding",
        "upsertPricingMarketDataBinding",
        "updatePricingMarketDataBinding",
        "deletePricingMarketDataBinding",
    }
)

REGISTERED_OPERATION_IDS = (
    (HEALTH_OPERATION_ID,)
    + tuple(sorted(QUERY_OPERATION_IDS))
    + tuple(sorted(MUTATION_OPERATION_IDS))
)


def get_api_health() -> ApiHealthResponse:
    return ApiHealthResponse(
        status="ok",
        service="apps/v1",
        version=version("ms-markets"),
    )


def build_command_center_connection_contract(
    *,
    openapi_schema: dict[str, Any],
    openapi_url: str,
) -> CommandCenterConnectionContract:
    operation_lookup = _build_operation_lookup(openapi_schema)
    schemas = openapi_schema.get("components", {}).get("schemas", {})
    available_operations = [
        _build_operation(
            operation_id=operation_id,
            operation_lookup=operation_lookup,
            schemas=schemas,
        )
        for operation_id in REGISTERED_OPERATION_IDS
    ]

    return CommandCenterConnectionContract(
        contract_version=CONTRACT_VERSION,
        adapter=CommandCenterAdapterInfo(
            type="adapter-from-api",
            id=ADAPTER_ID,
            title=ADAPTER_TITLE,
            description=ADAPTER_DESCRIPTION,
        ),
        openapi=CommandCenterOpenApiInfo(
            url=openapi_url,
            version=str(openapi_schema.get("openapi", "")),
            checksum=_openapi_checksum(openapi_schema),
        ),
        config_variables=[],
        secret_variables=[],
        available_operations=available_operations,
        health=CommandCenterHealthOperation(
            operation_id=HEALTH_OPERATION_ID,
            expected_status=200,
            timeout_ms=5000,
        ),
    )


def _build_operation_lookup(
    openapi_schema: dict[str, Any],
) -> dict[str, tuple[str, str, dict[str, Any]]]:
    lookup: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, path_item in openapi_schema.get("paths", {}).items():
        for method in ("get", "post", "patch", "put", "delete"):
            operation = path_item.get(method)
            if not operation:
                continue
            operation_id = operation.get("operationId")
            if operation_id:
                lookup[operation_id] = (path, method.upper(), operation)
    return lookup


def _build_operation(
    *,
    operation_id: str,
    operation_lookup: dict[str, tuple[str, str, dict[str, Any]]],
    schemas: dict[str, Any],
) -> CommandCenterOperation:
    try:
        path, method, openapi_operation = operation_lookup[operation_id]
    except KeyError as exc:
        raise RuntimeError(
            f"Command Center operation {operation_id!r} is not present in /openapi.json."
        ) from exc

    kind = _operation_kind(operation_id)
    response_model = _response_model_name(openapi_operation)
    response_contract = _response_contract(openapi_operation, response_model)
    parameters = [
        _build_parameter(parameter) for parameter in openapi_operation.get("parameters", [])
    ]

    return CommandCenterOperation(
        operation_id=operation_id,
        label=str(openapi_operation.get("summary") or operation_id),
        description=str(
            openapi_operation.get("description") or openapi_operation.get("summary") or operation_id
        ),
        method=method,
        path=path,
        kind=kind,
        capabilities=_operation_capabilities(kind),
        requires_time_range=False,
        supports_variables=True,
        supports_max_rows=any(parameter.name == "limit" for parameter in parameters),
        parameters=parameters,
        request_body=_build_request_body(openapi_operation),
        response_mappings=_response_mappings(
            openapi_operation,
            response_contract,
            schemas,
        ),
        cache=_operation_cache(kind=kind, method=method),
        response_contract=response_contract,
        response_model=response_model,
    )


def _operation_kind(operation_id: str) -> str:
    if operation_id == HEALTH_OPERATION_ID:
        return "health"
    if operation_id in QUERY_OPERATION_IDS:
        return "query"
    if operation_id in MUTATION_OPERATION_IDS:
        return "mutation"
    raise RuntimeError(f"Command Center operation {operation_id!r} is not registered.")


def _operation_capabilities(kind: str) -> list[str]:
    if kind == "query":
        return ["query"]
    return [kind]


def _build_parameter(parameter: dict[str, Any]) -> CommandCenterOperationParameter:
    schema = parameter.get("schema") or {}
    return CommandCenterOperationParameter(
        name=str(parameter.get("name")),
        in_=str(parameter.get("in")),
        required=bool(parameter.get("required", False)),
        type=schema.get("type"),
        description=parameter.get("description"),
        schema_=schema,
    )


def _build_request_body(
    openapi_operation: dict[str, Any],
) -> CommandCenterOperationRequestBody | None:
    request_body = openapi_operation.get("requestBody")
    if not request_body:
        return None

    content = request_body.get("content") or {}
    json_schema = (content.get("application/json") or {}).get("schema")
    return CommandCenterOperationRequestBody(
        required=bool(request_body.get("required", False)),
        content_types=sorted(content),
        schema_=json_schema,
        schema_ref=_schema_ref_name(json_schema),
    )


def _operation_cache(*, kind: str, method: str) -> CommandCenterOperationCache:
    enabled = kind == "query" and method == "GET"
    return CommandCenterOperationCache(
        enabled=enabled,
        ttl_seconds=30 if enabled else None,
    )


def _response_model_name(openapi_operation: dict[str, Any]) -> str | None:
    response_schema = _success_json_schema(openapi_operation)
    return _schema_ref_name(response_schema)


def _response_contract(
    openapi_operation: dict[str, Any],
    response_model: str | None,
) -> str:
    if (
        response_model == "TabularFrameResponse"
        or openapi_operation.get("x-ui-contract") == DIRECT_FRAME_CONTRACT
    ):
        return DIRECT_FRAME_CONTRACT
    return PROVIDER_NATIVE_CONTRACT


def _response_mappings(
    openapi_operation: dict[str, Any],
    response_contract: str,
    schemas: dict[str, Any],
) -> list[CommandCenterResponseMapping]:
    mappings = [
        CommandCenterResponseMapping.model_validate(mapping)
        for mapping in openapi_operation.get("x-response-mappings", [])
    ]
    if response_contract == DIRECT_FRAME_CONTRACT:
        return mappings

    response_schema = _success_json_schema(openapi_operation)
    response_ref = _schema_ref_name(response_schema)
    if response_ref is not None:
        schema = schemas.get(response_ref, {})
        mappings.extend(
            CommandCenterResponseMapping.model_validate(mapping)
            for mapping in schema.get("x-response-mappings", [])
        )
        mappings.extend(_provider_native_mappings_for_schema(response_ref, schema))
    return mappings


def _provider_native_mappings_for_schema(
    response_ref: str,
    schema: dict[str, Any],
) -> list[CommandCenterResponseMapping]:
    schema_properties = schema.get("properties", {})
    if {"count", "results"}.issubset(schema_properties):
        return [
            CommandCenterResponseMapping(
                id="results",
                label="Results",
                contract=DIRECT_FRAME_CONTRACT,
                status_code="200",
                content_type="application/json",
                rows_path="$.results",
                field_types=None,
            )
        ]

    mapping_by_schema = {
        "AccountHoldingsSnapshotResponse": [
            CommandCenterResponseMapping(
                id="holdings",
                label="Holdings",
                contract=DIRECT_FRAME_CONTRACT,
                status_code="200",
                content_type="application/json",
                rows_path="$.holdings",
                field_types=None,
            )
        ],
        "AccountTargetPositionsSnapshotResponse": [
            CommandCenterResponseMapping(
                id="positions",
                label="Positions",
                contract=DIRECT_FRAME_CONTRACT,
                status_code="200",
                content_type="application/json",
                rows_path="$.positions",
                field_types=None,
            )
        ],
        "AccountHoldingsByFundResponse": [
            CommandCenterResponseMapping(
                id="funds",
                label="Funds",
                contract=DIRECT_FRAME_CONTRACT,
                status_code="200",
                content_type="application/json",
                rows_path="$.funds",
                field_types=None,
            ),
            CommandCenterResponseMapping(
                id="residuals",
                label="Residuals",
                contract=DIRECT_FRAME_CONTRACT,
                status_code="200",
                content_type="application/json",
                rows_path="$.residuals",
                field_types=None,
            ),
        ],
        "VirtualFundHoldingsSnapshotResponse": [
            CommandCenterResponseMapping(
                id="holdings",
                label="Holdings",
                contract=DIRECT_FRAME_CONTRACT,
                status_code="200",
                content_type="application/json",
                rows_path="$.holdings",
                field_types=None,
            )
        ],
    }
    return mapping_by_schema.get(response_ref, [])


def _success_json_schema(openapi_operation: dict[str, Any]) -> dict[str, Any] | None:
    response = openapi_operation.get("responses", {}).get("200") or {}
    content = response.get("content") or {}
    return (content.get("application/json") or {}).get("schema")


def _schema_ref_name(schema: dict[str, Any] | None) -> str | None:
    if not schema:
        return None
    ref = schema.get("$ref")
    if not ref:
        return None
    return ref.removeprefix("#/components/schemas/")


def _openapi_checksum(openapi_schema: dict[str, Any]) -> str:
    payload = json.dumps(
        openapi_schema,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
