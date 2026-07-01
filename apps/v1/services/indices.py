from __future__ import annotations

from typing import Any

from apps.v1.schemas.delete_impact import DeleteImpactResponse
from apps.v1.schemas.indices import Index
from msm.api.base import operation_result_rows


def list_indices(
    *,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[Index]:
    runtime = _get_runtime()
    rows = _list_index_catalog_rows(
        runtime.context,
        search=search,
        limit=limit,
        offset=offset,
    )
    return [Index.model_validate(row) for row in rows]


def get_index(*, uid: str) -> Index | None:
    runtime = _get_runtime()
    record = _get_index_record(runtime.context, uid=uid)
    if record is None:
        return None
    return Index.model_validate(record)


def get_index_delete_impact(*, uid: str) -> DeleteImpactResponse | None:
    core_runtime = _get_delete_impact_runtime()
    record = _get_index_record(core_runtime.context, uid=uid)
    if record is None:
        return None

    pricing_runtime = _get_delete_impact_pricing_runtime()
    relationships = _build_index_delete_impact_relationships(
        uid=uid,
        unique_identifier=str(record["unique_identifier"]),
        core_context=core_runtime.context,
        pricing_context=pricing_runtime.context,
    )
    blocking_count = sum(item["count"] for item in relationships if item["blocks_delete"])
    affected_count = sum(item["count"] for item in relationships)

    warnings: list[str] = []
    if blocking_count:
        warnings.append("Delete is blocked while dependent rows reference this index.")
    for item in relationships:
        if item["count"] <= 0:
            continue
        if item["effect"] == "set_null":
            warnings.append(
                "Portfolio rows referencing this published index will keep the row "
                "but clear published_index_uid."
            )
        elif item["effect"] == "cascade_delete":
            warnings.append("Index convention details will be deleted by cascade.")
        elif item["effect"] == "blocks_cascade":
            warnings.append("A dependent relationship blocks a cascade delete path.")
        elif item["effect"] == "manual_cleanup_required":
            warnings.append(
                "Pricing curve selections use this index as selector and must be "
                "removed or repointed before delete."
            )

    if not warnings:
        warnings.append("No dependent rows were found for this index.")

    return DeleteImpactResponse.model_validate(
        {
            "resource_type": "index",
            "uid": record["uid"],
            "identifier": record["unique_identifier"],
            "display_name": record["display_name"],
            "can_delete": blocking_count == 0,
            "blocking_count": blocking_count,
            "affected_count": affected_count,
            "delete_endpoint": f"/api/v1/index/{uid}/",
            "relationships": relationships,
            "warnings": warnings,
        }
    )


def delete_index(*, uid: str) -> bool:
    runtime = _get_runtime()
    return bool(_delete_index_record(runtime.context, uid=uid))


def _get_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=["IndexType", "Index"],
        row_model_name="Index apps/v1",
    )


def _get_delete_impact_runtime():
    from apps.v1.runtime_bootstrap import resolve_apps_v1_runtime

    return resolve_apps_v1_runtime(
        models=["IndexType", "Index", "FutureAssetDetails", "Portfolio"],
        row_model_name="Index delete impact apps/v1",
    )


def _get_delete_impact_pricing_runtime():
    from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime
    from msm_pricing.bootstrap import resolve_pricing_runtime

    ensure_apps_v1_pricing_runtime()
    return resolve_pricing_runtime(
        models=[
            "IndexType",
            "Index",
            "IndexConventionDetails",
            "PricingMarketDataSetCurveBinding",
            "IndexFixingsStorage",
        ],
        row_model_name="Index delete impact apps/v1",
    )


def _build_index_delete_impact_relationships(
    *,
    uid: str,
    unique_identifier: str,
    core_context: Any,
    pricing_context: Any,
) -> list[dict[str, Any]]:
    from msm.models import FutureAssetDetailsTable, PortfolioTable
    from msm.repositories.crud import count_model
    from msm_pricing.data_nodes.index_fixings.storage import IndexFixingsStorage
    from msm_pricing.models.index_convention_details import IndexConventionDetailsTable
    from msm_pricing.models.market_data_bindings import PricingMarketDataSetCurveBindingTable

    def count(context: Any, model: Any, filters: dict[str, Any]) -> int:
        return _count_from_result(count_model(context, model=model, filters=filters))

    future_asset_details_count = count(
        core_context,
        FutureAssetDetailsTable,
        {"underlying_index_uid": uid},
    )
    index_fixings_count = count(
        pricing_context,
        IndexFixingsStorage,
        {"index_identifier": unique_identifier},
    )
    portfolio_published_index_count = count(
        core_context,
        PortfolioTable,
        {"published_index_uid": uid},
    )
    index_convention_details_count = count(
        pricing_context,
        IndexConventionDetailsTable,
        {"index_uid": uid},
    )
    pricing_curve_selections_count = count(
        pricing_context,
        PricingMarketDataSetCurveBindingTable,
        {
            "selector_type": "index",
            "selector_key": uid,
        },
    )

    return [
        {
            "key": "future_asset_details",
            "label": "Future asset details",
            "model": "FutureAssetDetailsTable",
            "column": "underlying_index_uid",
            "relationship_type": "direct",
            "on_delete": "RESTRICT",
            "count": future_asset_details_count,
            "effect": "blocks_delete",
            "severity": "blocking",
            "blocks_delete": future_asset_details_count > 0,
            "description": (
                "Future contract detail rows reference this index as their underlying index."
            ),
        },
        {
            "key": "index_fixings",
            "label": "Index fixings",
            "model": "IndexFixingsStorage",
            "column": "index_identifier",
            "relationship_type": "direct",
            "on_delete": "RESTRICT",
            "count": index_fixings_count,
            "effect": "blocks_delete",
            "severity": "blocking",
            "blocks_delete": index_fixings_count > 0,
            "description": ("Timestamped fixing rows reference this index by unique identifier."),
        },
        {
            "key": "portfolio_published_index",
            "label": "Published portfolio links",
            "model": "PortfolioTable",
            "column": "published_index_uid",
            "relationship_type": "direct",
            "on_delete": "SET NULL",
            "count": portfolio_published_index_count,
            "effect": "set_null",
            "severity": "mutating",
            "blocks_delete": False,
            "description": (
                "Portfolio rows published as this index will have published_index_uid cleared."
            ),
        },
        {
            "key": "index_convention_details",
            "label": "Index convention details",
            "model": "IndexConventionDetailsTable",
            "column": "index_uid",
            "relationship_type": "direct",
            "on_delete": "CASCADE",
            "count": index_convention_details_count,
            "effect": "cascade_delete",
            "severity": "destructive",
            "blocks_delete": False,
            "description": (
                "Pricing convention details are keyed by this index and cascade on delete."
            ),
        },
        {
            "key": "pricing_curve_selections",
            "label": "Pricing curve selections",
            "model": "PricingMarketDataSetCurveBindingTable",
            "column": "selector_key",
            "relationship_type": "derived",
            "on_delete": "APPLICATION",
            "count": pricing_curve_selections_count,
            "effect": "manual_cleanup_required",
            "severity": "blocking",
            "blocks_delete": pricing_curve_selections_count > 0,
            "description": ("Market-data-set curve selections use this index as their selector."),
        },
    ]


def _count_from_result(result: dict[str, Any] | list[Any] | None) -> int:
    rows = operation_result_rows(result)
    if not rows:
        return 0
    return int(rows[0].get("count") or 0)


def _list_index_catalog_rows(context, **kwargs):
    from msm.services import list_index_catalog_rows

    return list_index_catalog_rows(context, **kwargs)


def _get_index_record(context, **kwargs):
    from msm.services import get_index_record

    return get_index_record(context, **kwargs)


def _delete_index_record(context, **kwargs):
    from msm.services import delete_index_record

    return delete_index_record(context, **kwargs)
