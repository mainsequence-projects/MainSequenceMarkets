"""Static, contract-validated discovery metadata for apps/v1 resource lists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request

from apps.v1.schemas.bulk_actions import BulkActionDefinition
from apps.v1.schemas.resource_contracts import (
    ResourceBooleanFilter,
    ResourceColumn,
    ResourceDescriptor,
    ResourceDiscovery,
    ResourceFilter,
    ResourceFilterOption,
    ResourceIdentity,
    ResourceListControls,
    ResourceListDiscovery,
    ResourceSearchControl,
    ResourceSelectFilter,
    ResourceTextFilter,
)
from apps.v1.services.bulk_actions import build_bulk_delete_action

_PRESENTATION_QUERY_KEYS = frozenset(
    {"light", "limit", "offset", "ordering", "page", "page_size", "sort"}
)


@dataclass(frozen=True)
class ResourceDiscoverySpec:
    response: ResourceDiscovery
    semantic_query_keys: frozenset[str]


def get_resource_discovery(spec_key: str, request: Request) -> ResourceDiscovery:
    spec = RESOURCE_DISCOVERY_SPECS[spec_key]
    supplied = set(request.query_params)
    presentation_keys = sorted(supplied.intersection(_PRESENTATION_QUERY_KEYS))
    if presentation_keys:
        raise HTTPException(
            status_code=400,
            detail=(
                "Resource discovery does not accept presentation query keys: "
                + ", ".join(presentation_keys)
                + "."
            ),
        )
    unknown = sorted(supplied.difference(spec.semantic_query_keys))
    if unknown:
        raise HTTPException(
            status_code=400,
            detail="Unsupported resource discovery query keys: " + ", ".join(unknown) + ".",
        )
    return spec.response


def _column(
    value_path: str,
    header: str,
    data_type: Literal[
        "text", "number", "boolean", "date", "datetime", "badge", "list", "json"
    ] = "text",
    *,
    importance: Literal["primary", "secondary", "tertiary"] | None = None,
    filter_key: str | None = None,
) -> ResourceColumn:
    return ResourceColumn(
        id=value_path.replace("_", "-").replace(".", "-"),
        header=header,
        value_path=value_path,
        data_type=data_type,
        default_visible=True,
        hideable=True,
        importance=importance,
        filter_key=filter_key,
    )


def _text_filter(key: str, label: str) -> ResourceTextFilter:
    return ResourceTextFilter(key=key, label=label)


def _boolean_filter(key: str, label: str) -> ResourceBooleanFilter:
    return ResourceBooleanFilter(key=key, label=label)


def _select_filter(
    key: str,
    label: str,
    values: tuple[tuple[str, str], ...],
) -> ResourceSelectFilter:
    return ResourceSelectFilter(
        key=key,
        label=label,
        options=[
            ResourceFilterOption(value=value, label=option_label) for value, option_label in values
        ],
    )


def _spec(
    *,
    resource_id: str,
    label: str,
    item_label: str,
    identity_fields: tuple[str, ...],
    columns: tuple[ResourceColumn, ...],
    search: bool = False,
    filters: tuple[ResourceFilter, ...] = (),
    bulk_actions: tuple[BulkActionDefinition, ...] = (),
) -> ResourceDiscoverySpec:
    semantic_query_keys = {item.key for item in filters}
    search_control = None
    if search:
        semantic_query_keys.add("search")
        search_control = ResourceSearchControl(
            placeholder=f"Search {item_label}",
            fields=[column.id for column in columns],
        )
    return ResourceDiscoverySpec(
        response=ResourceDiscovery(
            resource=ResourceDescriptor(
                id=resource_id,
                label=label,
                item_label=item_label,
                identity=ResourceIdentity(fields=list(identity_fields)),
            ),
            list=ResourceListDiscovery(
                controls=ResourceListControls(
                    search=search_control,
                    filters=list(filters),
                    ordering=[],
                ),
                columns=list(columns),
            ),
            bulk_actions=list(bulk_actions),
        ),
        semantic_query_keys=frozenset(semantic_query_keys),
    )


_ASSET_CATEGORY_DELETE = build_bulk_delete_action(
    action_id="bulk-delete-asset-categories",
    label="Delete selected",
    endpoint="/api/v1/asset-category/bulk-delete/",
    preflight_endpoint="/api/v1/asset-category/bulk-delete/preflight/",
    confirmation_title="Delete asset categories",
    confirmation_warning="Deleted asset categories cannot be restored.",
)
_PORTFOLIO_GROUP_DELETE = build_bulk_delete_action(
    action_id="bulk-delete-portfolio-groups",
    label="Delete selected",
    endpoint="/api/v1/portfolio-group/bulk-delete/",
    preflight_endpoint="/api/v1/portfolio-group/bulk-delete/preflight/",
    confirmation_title="Delete portfolio groups",
    confirmation_warning="Deleted portfolio groups cannot be restored.",
)
_PORTFOLIO_DELETE = build_bulk_delete_action(
    action_id="bulk-delete-portfolios",
    label="Delete selected",
    endpoint="/api/v1/portfolio/bulk-delete/",
    preflight_endpoint="/api/v1/portfolio/bulk-delete/preflight/",
    confirmation_title="Delete portfolios",
    confirmation_warning="Deleted portfolios cannot be restored.",
)


RESOURCE_DISCOVERY_SPECS: dict[str, ResourceDiscoverySpec] = {
    "accounts": _spec(
        resource_id="accounts",
        label="Accounts",
        item_label="accounts",
        identity_fields=("uid",),
        search=True,
        columns=(
            _column("account_name", "Name", importance="primary"),
            _column("unique_identifier", "Identifier"),
            _column("account_is_active", "Active", "boolean"),
            _column("is_paper", "Paper", "boolean"),
            _column("uid", "UID"),
        ),
    ),
    "account-target-allocation-targets": _spec(
        resource_id="account-target-allocation-targets",
        label="Target allocation candidates",
        item_label="target allocation candidates",
        identity_fields=("target_type", "target_uid"),
        search=True,
        filters=(
            _select_filter(
                "target_type",
                "Target type",
                (("all", "All"), ("asset", "Asset"), ("portfolio", "Portfolio")),
            ),
        ),
        columns=(
            _column("display_label", "Name", importance="primary"),
            _column("identifier", "Identifier"),
            _column("target_type", "Target type", filter_key="target_type"),
            _column("secondary_label", "Details"),
            _column("target_uid", "Target UID"),
        ),
    ),
    "assets": _spec(
        resource_id="assets",
        label="Assets",
        item_label="assets",
        identity_fields=("uid",),
        search=True,
        filters=(_text_filter("categories__uid", "Category UID"),),
        columns=(
            _column("unique_identifier", "Identifier", importance="primary"),
            _column("asset_type", "Asset type"),
            _column("uid", "UID"),
        ),
    ),
    "asset-related-meta-tables": _spec(
        resource_id="asset-related-meta-tables",
        label="Asset related MetaTables",
        item_label="related MetaTables",
        identity_fields=("key",),
        filters=(
            _boolean_filter("numeric", "Numeric"),
            _boolean_filter("timestamped", "Timestamped"),
        ),
        columns=(
            _column("label", "Label", importance="primary"),
            _column("identifier", "Identifier"),
            _column("relationship_type", "Relationship"),
            _column("count", "Rows", "number"),
            _column("delete_capability", "Delete behavior"),
        ),
    ),
    "asset-categories": _spec(
        resource_id="asset-categories",
        label="Asset categories",
        item_label="asset categories",
        identity_fields=("uid",),
        search=True,
        bulk_actions=(_ASSET_CATEGORY_DELETE,),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("unique_identifier", "Identifier"),
            _column("description", "Description"),
            _column("uid", "UID"),
        ),
    ),
    "calendars": _spec(
        resource_id="calendars",
        label="Calendars",
        item_label="calendars",
        identity_fields=("uid",),
        search=True,
        filters=(
            _text_filter("unique_identifier", "Identifier"),
            _text_filter("unique_identifier_contains", "Identifier contains"),
            _text_filter("calendar_type", "Calendar type"),
            _text_filter("source", "Source"),
            _text_filter("source_identifier", "Source identifier"),
        ),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("unique_identifier", "Identifier", filter_key="unique_identifier"),
            _column("calendar_type", "Type", filter_key="calendar_type"),
            _column("timezone", "Timezone"),
            _column("source", "Source", filter_key="source"),
        ),
    ),
    "calendar-dates": _spec(
        resource_id="calendar-dates",
        label="Calendar dates",
        item_label="calendar dates",
        identity_fields=("uid",),
        filters=(
            _text_filter("start_date", "Start date"),
            _text_filter("end_date", "End date"),
            _boolean_filter("is_business_day", "Business day"),
            _boolean_filter("is_holiday", "Holiday"),
            _boolean_filter("is_weekend", "Weekend"),
            _boolean_filter("is_early_close", "Early close"),
        ),
        columns=(
            _column("local_date", "Date", "date", importance="primary"),
            _column("is_business_day", "Business day", "boolean", filter_key="is_business_day"),
            _column("is_holiday", "Holiday", "boolean", filter_key="is_holiday"),
            _column("is_early_close", "Early close", "boolean", filter_key="is_early_close"),
            _column("holiday_name", "Holiday name"),
        ),
    ),
    "calendar-sessions": _spec(
        resource_id="calendar-sessions",
        label="Calendar sessions",
        item_label="calendar sessions",
        identity_fields=("uid",),
        filters=(
            _text_filter("start_date", "Start date"),
            _text_filter("end_date", "End date"),
            _text_filter("session_label", "Session label"),
            _boolean_filter("is_primary", "Primary"),
        ),
        columns=(
            _column("local_date", "Date", "date", importance="primary"),
            _column("session_label", "Session", filter_key="session_label"),
            _column("opens_at", "Opens", "datetime"),
            _column("closes_at", "Closes", "datetime"),
            _column("timezone", "Timezone"),
        ),
    ),
    "calendar-events": _spec(
        resource_id="calendar-events",
        label="Calendar events",
        item_label="calendar events",
        identity_fields=("uid",),
        filters=(
            _text_filter("start_date", "Start date"),
            _text_filter("end_date", "End date"),
            _text_filter("event_type", "Event type"),
            _text_filter("event_label", "Event label"),
            _text_filter("target_type", "Target type"),
            _text_filter("target_uid", "Target UID"),
            _text_filter("target_identifier", "Target identifier"),
        ),
        columns=(
            _column("event_date", "Date", "date", importance="primary"),
            _column("event_type", "Type", filter_key="event_type"),
            _column("event_label", "Label", filter_key="event_label"),
            _column("target_identifier", "Target", filter_key="target_identifier"),
            _column("event_time", "Time"),
        ),
    ),
    "index-types": _spec(
        resource_id="index-types",
        label="Index types",
        item_label="index types",
        identity_fields=("uid",),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("index_type", "Type"),
            _column("description", "Description"),
            _column("uid", "UID"),
        ),
    ),
    "indexes": _spec(
        resource_id="indexes",
        label="Indexes",
        item_label="indexes",
        identity_fields=("uid",),
        search=True,
        filters=(
            _text_filter("index_type", "Index type"),
            _boolean_filter("has_formula", "Has formula"),
            _boolean_filter("has_canonical_values", "Has canonical values"),
            _text_filter("cadence", "Cadence"),
        ),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("unique_identifier", "Identifier"),
            _column("index_type", "Type", filter_key="index_type"),
            _column("calculation_method", "Calculation"),
            _column("uid", "UID"),
        ),
    ),
    "index-formulas": _spec(
        resource_id="index-formulas",
        label="Index formulas",
        item_label="index formulas",
        identity_fields=("uid",),
        columns=(
            _column("version", "Version", "number", importance="primary"),
            _column("status", "Status", "badge"),
            _column("valid_from", "Valid from", "datetime"),
            _column("input_count", "Inputs", "number"),
            _column("formula", "Formula"),
        ),
    ),
    "index-datasets": _spec(
        resource_id="index-datasets",
        label="Index datasets",
        item_label="index datasets",
        identity_fields=("dataset.meta_table_uid",),
        filters=(_boolean_filter("include_empty", "Include empty"),),
        columns=(
            _column("dataset.identifier", "Identifier", importance="primary"),
            _column("population_state", "Population", "badge"),
            _column("row_count", "Rows", "number"),
            _column("latest_time_index", "Latest time", "datetime"),
            _column("dataset.cadence", "Cadence"),
        ),
    ),
    "index-related-meta-tables": _spec(
        resource_id="index-related-meta-tables",
        label="Index related MetaTables",
        item_label="related MetaTables",
        identity_fields=("key",),
        filters=(
            _boolean_filter("numeric", "Numeric"),
            _boolean_filter("timestamped", "Timestamped"),
        ),
        columns=(
            _column("label", "Label", importance="primary"),
            _column("identifier", "Identifier"),
            _column("relationship_type", "Relationship"),
            _column("count", "Rows", "number"),
            _column("delete_capability", "Delete behavior"),
        ),
    ),
    "portfolio-groups": _spec(
        resource_id="portfolio-groups",
        label="Portfolio groups",
        item_label="portfolio groups",
        identity_fields=("uid",),
        search=True,
        filters=(
            _text_filter("unique_identifier", "Identifier"),
            _text_filter("display_name", "Display name"),
        ),
        bulk_actions=(_PORTFOLIO_GROUP_DELETE,),
        columns=(
            _column("display_name", "Name", importance="primary", filter_key="display_name"),
            _column("unique_identifier", "Identifier", filter_key="unique_identifier"),
            _column("description", "Description"),
            _column("uid", "UID"),
        ),
    ),
    "groups-for-portfolio": _spec(
        resource_id="groups-for-portfolio",
        label="Groups for portfolio",
        item_label="portfolio groups",
        identity_fields=("uid",),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("unique_identifier", "Identifier"),
            _column("description", "Description"),
            _column("uid", "UID"),
        ),
    ),
    "portfolios-in-group": _spec(
        resource_id="portfolios-in-group",
        label="Portfolios in group",
        item_label="portfolios",
        identity_fields=("uid",),
        columns=(
            _column("unique_identifier", "Identifier", importance="primary"),
            _column("calendar_uid", "Calendar"),
            _column("published_index_uid", "Published index"),
            _column("uid", "UID"),
        ),
    ),
    "portfolio-signals": _spec(
        resource_id="portfolio-signals",
        label="Portfolio signals",
        item_label="portfolio signals",
        identity_fields=("uid",),
        search=True,
        filters=(_text_filter("signal_uid", "Signal UID"),),
        columns=(
            _column("signal_uid", "Signal UID", importance="primary", filter_key="signal_uid"),
            _column("signal_description", "Description"),
            _column("uid", "UID"),
        ),
    ),
    "portfolios": _spec(
        resource_id="portfolios",
        label="Portfolios",
        item_label="portfolios",
        identity_fields=("uid",),
        search=True,
        filters=(_text_filter("calendar_uid", "Calendar UID"),),
        bulk_actions=(_PORTFOLIO_DELETE,),
        columns=(
            _column("unique_identifier", "Identifier", importance="primary"),
            _column("calendar_uid", "Calendar", filter_key="calendar_uid"),
            _column("published_index_uid", "Published index"),
            _column("signal_uid", "Signal"),
            _column("uid", "UID"),
        ),
    ),
    "virtual-funds": _spec(
        resource_id="virtual-funds",
        label="Virtual funds",
        item_label="virtual funds",
        identity_fields=("uid",),
        search=True,
        filters=(
            _text_filter("account_uid", "Account UID"),
            _text_filter("portfolio_uid", "Portfolio UID"),
        ),
        columns=(
            _column("unique_identifier", "Identifier", importance="primary"),
            _column("account_uid", "Account", filter_key="account_uid"),
            _column("target_portfolio_uid", "Target portfolio"),
            _column("uid", "UID"),
        ),
    ),
    "pricing-curves": _spec(
        resource_id="pricing-curves",
        label="Pricing curves",
        item_label="pricing curves",
        identity_fields=("uid",),
        search=True,
        filters=(
            _text_filter("curve_type", "Curve type"),
            _text_filter("source", "Source"),
        ),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("unique_identifier", "Identifier"),
            _column("curve_type", "Curve type", filter_key="curve_type"),
            _column("currency_code", "Currency"),
            _column("status", "Status", "badge"),
        ),
    ),
    "pricing-curve-selections": _spec(
        resource_id="pricing-curve-selections",
        label="Pricing curve selections",
        item_label="curve selections",
        identity_fields=("binding_uid",),
        columns=(
            _column("role_key", "Role", importance="primary"),
            _column("status", "Status", "badge"),
            _column("source", "Source"),
            _column("quote_side", "Quote side"),
            _column("binding_uid", "Binding UID"),
        ),
    ),
    "pricing-market-data-sets": _spec(
        resource_id="pricing-market-data-sets",
        label="Market data sets",
        item_label="market data sets",
        identity_fields=("uid",),
        filters=(
            _text_filter("status", "Status"),
            _text_filter("set_key", "Set key"),
        ),
        columns=(
            _column("display_name", "Name", importance="primary"),
            _column("set_key", "Set key", filter_key="set_key"),
            _column("status", "Status", "badge", filter_key="status"),
            _column("description", "Description"),
            _column("uid", "UID"),
        ),
    ),
    "pricing-market-data-bindings": _spec(
        resource_id="pricing-market-data-bindings",
        label="Market data bindings",
        item_label="market data bindings",
        identity_fields=("uid",),
        filters=(
            _text_filter("market_data_set_uid", "Market data set UID"),
            _text_filter("concept_key", "Concept key"),
        ),
        columns=(
            _column("concept_key", "Concept", importance="primary", filter_key="concept_key"),
            _column("source", "Source"),
            _column("data_node_uid", "TimeIndexTableUpdater"),
            _column("storage_table_identifier", "Storage table"),
            _column("uid", "UID"),
        ),
    ),
    "pricing-market-data-set-bindings": _spec(
        resource_id="pricing-market-data-set-bindings",
        label="Market data set bindings",
        item_label="market data bindings",
        identity_fields=("uid",),
        columns=(
            _column("concept_key", "Concept", importance="primary"),
            _column("source", "Source"),
            _column("data_node_uid", "TimeIndexTableUpdater"),
            _column("storage_table_identifier", "Storage table"),
            _column("uid", "UID"),
        ),
    ),
}


__all__ = ["RESOURCE_DISCOVERY_SPECS", "get_resource_discovery"]
