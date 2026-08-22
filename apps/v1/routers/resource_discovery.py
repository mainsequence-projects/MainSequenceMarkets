"""Command Center discovery endpoints for every apps/v1 resource collection."""

from __future__ import annotations

from fastapi import APIRouter, Request

from apps.v1.schemas.common import ErrorResponse
from apps.v1.schemas.resource_contracts import (
    RESOURCE_DISCOVERY_CONTRACT,
    ResourceDiscovery,
)
from apps.v1.services.resource_discovery import get_resource_discovery

router = APIRouter(tags=["resource-discovery"])

_DISCOVERY_OPENAPI = {"x-ui-contract": RESOURCE_DISCOVERY_CONTRACT}
_DISCOVERY_ERRORS = {400: {"model": ErrorResponse, "description": "Invalid discovery scope."}}


def _response(spec_key: str, request: Request) -> ResourceDiscovery:
    return get_resource_discovery(spec_key, request)


@router.get(
    "/account/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverAccounts",
    summary="Discover accounts",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_accounts(request: Request) -> ResourceDiscovery:
    return _response("accounts", request)


@router.get(
    "/account/target-allocation/targets/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverAccountTargetAllocationTargets",
    summary="Discover account target-allocation candidates",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_account_target_allocation_targets(request: Request) -> ResourceDiscovery:
    return _response("account-target-allocation-targets", request)


@router.get(
    "/asset/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverAssets",
    summary="Discover assets",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_assets(request: Request) -> ResourceDiscovery:
    return _response("assets", request)


@router.get(
    "/asset/{uid}/related-meta-tables/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverAssetRelatedMetaTables",
    summary="Discover asset related MetaTables",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_asset_related_meta_tables(uid: str, request: Request) -> ResourceDiscovery:
    del uid
    return _response("asset-related-meta-tables", request)


@router.get(
    "/asset-category/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverAssetCategories",
    summary="Discover asset categories",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_asset_categories(request: Request) -> ResourceDiscovery:
    return _response("asset-categories", request)


@router.get(
    "/calendar/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverCalendars",
    summary="Discover calendars",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_calendars(request: Request) -> ResourceDiscovery:
    return _response("calendars", request)


@router.get(
    "/calendar/{calendar_uid}/dates/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverCalendarDates",
    summary="Discover calendar dates",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_calendar_dates(calendar_uid: str, request: Request) -> ResourceDiscovery:
    del calendar_uid
    return _response("calendar-dates", request)


@router.get(
    "/calendar/{calendar_uid}/sessions/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverCalendarSessions",
    summary="Discover calendar sessions",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_calendar_sessions(calendar_uid: str, request: Request) -> ResourceDiscovery:
    del calendar_uid
    return _response("calendar-sessions", request)


@router.get(
    "/calendar/{calendar_uid}/events/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverCalendarEvents",
    summary="Discover calendar events",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_calendar_events(calendar_uid: str, request: Request) -> ResourceDiscovery:
    del calendar_uid
    return _response("calendar-events", request)


@router.get(
    "/index-type/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverIndexTypes",
    summary="Discover index types",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_index_types(request: Request) -> ResourceDiscovery:
    return _response("index-types", request)


@router.get(
    "/index/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverIndexes",
    summary="Discover indexes",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_indexes(request: Request) -> ResourceDiscovery:
    return _response("indexes", request)


@router.get(
    "/index/{uid}/formulas/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverIndexFormulas",
    summary="Discover index formulas",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_index_formulas(uid: str, request: Request) -> ResourceDiscovery:
    del uid
    return _response("index-formulas", request)


@router.get(
    "/index/{uid}/datasets/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverIndexDatasets",
    summary="Discover index datasets",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_index_datasets(uid: str, request: Request) -> ResourceDiscovery:
    del uid
    return _response("index-datasets", request)


@router.get(
    "/index/{uid}/related-meta-tables/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverIndexRelatedMetaTables",
    summary="Discover index related MetaTables",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_index_related_meta_tables(uid: str, request: Request) -> ResourceDiscovery:
    del uid
    return _response("index-related-meta-tables", request)


@router.get(
    "/portfolio-group/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPortfolioGroups",
    summary="Discover portfolio groups",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_portfolio_groups(request: Request) -> ResourceDiscovery:
    return _response("portfolio-groups", request)


@router.get(
    "/portfolio-group/by-portfolio/{portfolio_uid}/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverGroupsForPortfolio",
    summary="Discover groups for a portfolio",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_groups_for_portfolio(portfolio_uid: str, request: Request) -> ResourceDiscovery:
    del portfolio_uid
    return _response("groups-for-portfolio", request)


@router.get(
    "/portfolio-group/{uid}/portfolios/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPortfoliosInGroup",
    summary="Discover portfolios in a group",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_portfolios_in_group(uid: str, request: Request) -> ResourceDiscovery:
    del uid
    return _response("portfolios-in-group", request)


@router.get(
    "/portfolio-signal/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPortfolioSignals",
    summary="Discover portfolio signals",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_portfolio_signals(request: Request) -> ResourceDiscovery:
    return _response("portfolio-signals", request)


@router.get(
    "/portfolio/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPortfolios",
    summary="Discover portfolios",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_portfolios(request: Request) -> ResourceDiscovery:
    return _response("portfolios", request)


@router.get(
    "/virtualfund/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverVirtualFunds",
    summary="Discover virtual funds",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_virtual_funds(request: Request) -> ResourceDiscovery:
    return _response("virtual-funds", request)


@router.get(
    "/pricing/curves/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPricingCurves",
    summary="Discover pricing curves",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_pricing_curves(request: Request) -> ResourceDiscovery:
    return _response("pricing-curves", request)


@router.get(
    "/pricing/curves/{uid}/curve-selections/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPricingCurveSelections",
    summary="Discover pricing curve selections",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_pricing_curve_selections(uid: str, request: Request) -> ResourceDiscovery:
    del uid
    return _response("pricing-curve-selections", request)


@router.get(
    "/pricing/market_data/sets/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPricingMarketDataSets",
    summary="Discover pricing market-data sets",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_pricing_market_data_sets(request: Request) -> ResourceDiscovery:
    return _response("pricing-market-data-sets", request)


@router.get(
    "/pricing/market_data/bindings/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPricingMarketDataBindings",
    summary="Discover pricing market-data bindings",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_pricing_market_data_bindings(request: Request) -> ResourceDiscovery:
    return _response("pricing-market-data-bindings", request)


@router.get(
    "/pricing/market_data/sets/{market_data_set_uid}/bindings/discovery/",
    response_model=ResourceDiscovery,
    operation_id="discoverPricingMarketDataSetBindings",
    summary="Discover bindings for a pricing market-data set",
    openapi_extra=_DISCOVERY_OPENAPI,
    responses=_DISCOVERY_ERRORS,
)
def discover_pricing_market_data_set_bindings(
    market_data_set_uid: str,
    request: Request,
) -> ResourceDiscovery:
    del market_data_set_uid
    return _response("pricing-market-data-set-bindings", request)


__all__ = ["router"]
