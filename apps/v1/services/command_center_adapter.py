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
    CommandCenterOperationParameters,
    CommandCenterOperationRequestBody,
)
from command_center.contracts import CORE_TABULAR_FRAME_CONTRACT

ADAPTER_ID = "ms-markets.apps-v1"
ADAPTER_TITLE = "MainSequence Markets API"
ADAPTER_DESCRIPTION = "Adapter contract for the apps/v1 markets FastAPI surface."
CONTRACT_VERSION = 1
HEALTH_OPERATION_ID = "getApiHealth"
CONTRACT_OPERATION_ID = "getCommandCenterConnectionContract"
DIRECT_FRAME_CONTRACT = CORE_TABULAR_FRAME_CONTRACT

READ_OPERATION_IDS = frozenset(
    {
        "getApiSettings",
        "discoverAccounts",
        "discoverAccountTargetAllocationTargets",
        "discoverAssets",
        "discoverAssetRelatedMetaTables",
        "discoverAssetCategories",
        "discoverCalendars",
        "discoverCalendarDates",
        "discoverCalendarSessions",
        "discoverCalendarEvents",
        "discoverIndexTypes",
        "discoverIndexes",
        "discoverIndexFormulas",
        "discoverIndexDatasets",
        "discoverIndexRelatedMetaTables",
        "discoverPortfolioGroups",
        "discoverGroupsForPortfolio",
        "discoverPortfoliosInGroup",
        "discoverPortfolioSignals",
        "discoverPortfolios",
        "discoverVirtualFunds",
        "discoverPricingCurves",
        "discoverPricingCurveSelections",
        "discoverPricingMarketDataSets",
        "discoverPricingMarketDataBindings",
        "discoverPricingMarketDataSetBindings",
        "listAssets",
        "getAssetMonitorFrame",
        "getAsset",
        "getAssetSummary",
        "getAssetPricingDetails",
        "listAssetRelatedMetaTables",
        "listAssetCategories",
        "preflightBulkDeleteAssetCategories",
        "getAssetCategoryDetail",
        "listAccounts",
        "getAccount",
        "getAccountSummary",
        "searchAccountTargetAllocationTargets",
        "getAccountHoldings",
        "getAccountHoldingsByFund",
        "getAccountTargetPositions",
        "listIndexes",
        "getIndex",
        "getIndexSummary",
        "listIndexTypes",
        "getIndexType",
        "listIndexFormulas",
        "getIndexFormula",
        "listIndexDatasets",
        "getIndexDatasetSummary",
        "getIndexDatasetValuesFrame",
        "listIndexRelatedMetaTables",
        "getIndexDeleteImpact",
        "listPortfolios",
        "preflightBulkDeletePortfolios",
        "getPortfolio",
        "getPortfolioSummary",
        "getPortfolioGroup",
        "getPortfolioSignalWeightsFrame",
        "getPortfolioValuesFrame",
        "getPortfolioWeights",
        "listGroupsForPortfolio",
        "listPortfolioGroups",
        "preflightBulkDeletePortfolioGroups",
        "listPortfoliosInGroup",
        "getPortfolioSignal",
        "listPortfolioSignals",
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
        "getPricingCurve",
        "getPricingCurveSummary",
        "listPricingCurveSelections",
        "getPricingCurveDeleteImpact",
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

QUERY_OPERATION_IDS = frozenset(
    {
        "getAssetMonitorFrame",
        "getFixedIncomeAssetCashflowsFrame",
        "getFixedIncomeAssetNetCashflowsFrame",
        "getIndexDatasetValuesFrame",
        "getPortfolioSignalWeightsFrame",
        "getPortfolioValuesFrame",
    }
)
RESOURCE_OPERATION_IDS = READ_OPERATION_IDS - QUERY_OPERATION_IDS

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
        "createIndex",
        "updateIndex",
        "bulkCascadeDeletePortfolios",
        "bulkDeletePortfolios",
        "addPortfolioToGroup",
        "bulkDeletePortfolioGroupMemberships",
        "bulkDeletePortfolioGroups",
        "createPortfolioGroup",
        "deletePortfolio",
        "deletePortfolioGroup",
        "deletePortfolioWeights",
        "removePortfolioFromGroup",
        "updatePortfolioGroup",
        "createPortfolioSignal",
        "deletePortfolioSignal",
        "deletePortfolioSignalWeights",
        "updatePortfolioSignal",
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
        "deletePricingCurve",
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
    + tuple(sorted(RESOURCE_OPERATION_IDS))
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
    available_operations = [
        _build_operation(
            operation_id=operation_id,
            operation_lookup=operation_lookup,
        )
        for operation_id in REGISTERED_OPERATION_IDS
    ]

    return CommandCenterConnectionContract(
        contractVersion=CONTRACT_VERSION,
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
        configVariables=[],
        secretVariables=[],
        availableOperations=available_operations,
        health=CommandCenterHealthOperation(
            operationId=HEALTH_OPERATION_ID,
            expectedStatus=200,
            timeoutMs=5000,
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
    parameters = _build_parameters(openapi_operation.get("parameters", []))

    return CommandCenterOperation(
        operationId=operation_id,
        label=str(openapi_operation.get("summary") or operation_id),
        description=str(
            openapi_operation.get("description") or openapi_operation.get("summary") or operation_id
        ),
        method=method,
        path=path,
        kind=kind,
        capabilities=_operation_capabilities(kind),
        requiresTimeRange=False,
        supportsVariables=True,
        supportsMaxRows=any(parameter.key == "limit" for parameter in parameters.query),
        parameters=parameters,
        requestBody=_build_request_body(openapi_operation),
        cache=_operation_cache(kind=kind, method=method),
        responseContract=response_contract,
        responseModel=response_model,
    )


def _operation_kind(operation_id: str) -> str:
    if operation_id in QUERY_OPERATION_IDS:
        return "query"
    if operation_id == HEALTH_OPERATION_ID or operation_id in RESOURCE_OPERATION_IDS:
        return "resource"
    if operation_id in MUTATION_OPERATION_IDS:
        return "mutation"
    raise RuntimeError(f"Command Center operation {operation_id!r} is not registered.")


def _operation_capabilities(kind: str) -> list[str]:
    return [kind]


def _build_parameters(parameters: list[dict[str, Any]]) -> CommandCenterOperationParameters:
    grouped: dict[str, list[CommandCenterOperationParameter]] = {
        "path": [],
        "query": [],
        "headers": [],
    }
    for parameter in parameters:
        location = str(parameter.get("in"))
        group = "headers" if location == "header" else location
        if group in grouped:
            grouped[group].append(_build_parameter(parameter))
    return CommandCenterOperationParameters(**grouped)


def _build_parameter(parameter: dict[str, Any]) -> CommandCenterOperationParameter:
    schema = parameter.get("schema") or {}
    name = str(parameter.get("name"))
    field_type, options = _parameter_type_and_options(schema)
    return CommandCenterOperationParameter(
        key=name,
        name=name,
        label=name.replace("_", " ").title(),
        type=field_type,
        required=bool(parameter.get("required", False)),
        description=parameter.get("description"),
        defaultValue=schema.get("default"),
        options=options,
    )


def _parameter_type_and_options(
    schema: dict[str, Any],
) -> tuple[str, list[dict[str, str]] | None]:
    enum = [value for value in schema.get("enum", []) if isinstance(value, str) and value]
    if enum:
        return "select", [{"label": value, "value": value} for value in enum]
    openapi_type = schema.get("type")
    if openapi_type in {"integer", "number"}:
        return "number", None
    if openapi_type == "boolean":
        return "boolean", None
    if openapi_type in {"array", "object"}:
        return "json", None
    return "string", None


def _build_request_body(
    openapi_operation: dict[str, Any],
) -> CommandCenterOperationRequestBody | None:
    request_body = openapi_operation.get("requestBody")
    if not request_body:
        return None

    content = request_body.get("content") or {}
    content_type = (
        "application/json" if "application/json" in content else next(iter(content), None)
    )
    json_schema = (content.get(content_type) or {}).get("schema") if content_type else None
    return CommandCenterOperationRequestBody(
        required=bool(request_body.get("required", False)),
        contentType=content_type,
        schema=json_schema,
        description=request_body.get("description"),
    )


def _operation_cache(*, kind: str, method: str) -> CommandCenterOperationCache:
    enabled = kind == "query" and method == "GET"
    return CommandCenterOperationCache(
        policy="safe" if enabled else "disabled",
        ttlMs=30_000 if enabled else None,
        dedupeInFlight=enabled,
    )


def _response_model_name(openapi_operation: dict[str, Any]) -> str | None:
    response_schema = _success_json_schema(openapi_operation)
    return _schema_ref_name(response_schema)


def _response_contract(
    openapi_operation: dict[str, Any],
    response_model: str | None,
) -> str | None:
    declared_contract = openapi_operation.get("x-ui-contract")
    if isinstance(declared_contract, str) and declared_contract:
        return declared_contract
    if response_model == "TabularFrameResponse":
        return DIRECT_FRAME_CONTRACT
    return None


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
