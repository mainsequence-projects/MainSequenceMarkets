from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.v1.identity import registry_write
from apps.v1.runtime_bootstrap import ensure_apps_v1_pricing_runtime
from apps.v1.schemas.pricing_market_data import (
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
    PricingMarketDataSetBindingCreate,
    PricingMarketDataSetBindingUpdate,
    PricingMarketDataSetBindingUpsert,
    PricingMarketDataSetCreate,
    PricingMarketDataSetUpdate,
    PricingMarketDataSetUpsert,
)


def pricing_market_data_card() -> dict[str, Any]:
    return {
        "resource": "pricing_market_data",
        "description": "Manage pricing market-data sets and concept bindings.",
        "resources": [
            {
                "key": "sets",
                "model": "PricingMarketDataSet",
                "list_url": "/api/v1/pricing/market_data/sets/",
                "create_url": "/api/v1/pricing/market_data/sets/",
                "upsert_url": "/api/v1/pricing/market_data/sets/upsert/",
            },
            {
                "key": "bindings",
                "model": "PricingMarketDataSetBinding",
                "list_url": "/api/v1/pricing/market_data/bindings/",
                "create_url": "/api/v1/pricing/market_data/bindings/",
                "upsert_url": "/api/v1/pricing/market_data/bindings/upsert/",
            },
        ],
    }


def list_pricing_market_data_sets(
    *,
    limit: int,
    offset: int,
    status: str | None = None,
    set_key: str | None = None,
) -> dict[str, Any]:
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSet.list(
        limit=limit,
        offset=offset,
        status=status,
        set_key=set_key,
    )


def get_pricing_market_data_set(*, uid: str):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSet.get_by_uid(uid)


def get_pricing_market_data_set_by_key(*, set_key: str):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSet.get_by_key(set_key)


@registry_write("pricing-market-data", "create:pricing-market-data-set")
def create_pricing_market_data_set(
    payload: PricingMarketDataSetCreate,
):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSet.create(payload)


@registry_write("pricing-market-data", "upsert:pricing-market-data-set")
def upsert_pricing_market_data_set(
    payload: PricingMarketDataSetUpsert,
):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSet.upsert(payload)


@registry_write("pricing-market-data", "update:pricing-market-data-set")
def update_pricing_market_data_set(
    *,
    uid: str,
    payload: PricingMarketDataSetUpdate,
):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSet.update(uid, payload)


@registry_write("pricing-market-data", "delete:pricing-market-data-set")
def delete_pricing_market_data_set(*, uid: str) -> dict[str, Any]:
    ensure_apps_v1_pricing_runtime()
    result = PricingMarketDataSet.delete(uid)
    return {
        "detail": "Deleted pricing market-data set.",
        "uid": uid,
        "deleted_count": _deleted_count(result),
    }


def list_pricing_market_data_bindings(
    *,
    limit: int,
    offset: int,
    market_data_set_uid: str | None = None,
    concept_key: str | None = None,
) -> dict[str, Any]:
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSetBinding.list(
        limit=limit,
        offset=offset,
        market_data_set_uid=market_data_set_uid,
        concept_key=concept_key,
    )


def list_pricing_market_data_set_bindings(
    *,
    market_data_set_uid: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return list_pricing_market_data_bindings(
        limit=limit,
        offset=offset,
        market_data_set_uid=market_data_set_uid,
    )


def get_pricing_market_data_binding(*, uid: str):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSetBinding.get_by_uid(uid)


def resolve_pricing_market_data_binding(
    *,
    market_data_set: str | None,
    concept_key: str,
) -> dict[str, Any]:
    ensure_apps_v1_pricing_runtime()
    storage_table_uid = PricingMarketDataSetBinding.resolve_storage_table_uid(
        market_data_set=market_data_set,
        concept_key=concept_key,
    )
    return {
        "market_data_set": market_data_set,
        "concept_key": concept_key,
        "storage_table_uid": storage_table_uid,
    }


@registry_write("pricing-market-data", "create:pricing-market-data-binding")
def create_pricing_market_data_binding(
    payload: PricingMarketDataSetBindingCreate,
):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSetBinding.create(payload)


@registry_write("pricing-market-data", "upsert:pricing-market-data-binding")
def upsert_pricing_market_data_binding(
    payload: PricingMarketDataSetBindingUpsert,
):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSetBinding.upsert(payload)


@registry_write("pricing-market-data", "update:pricing-market-data-binding")
def update_pricing_market_data_binding(
    *,
    uid: str,
    payload: PricingMarketDataSetBindingUpdate,
):
    ensure_apps_v1_pricing_runtime()
    return PricingMarketDataSetBinding.update(uid, payload)


@registry_write("pricing-market-data", "delete:pricing-market-data-binding")
def delete_pricing_market_data_binding(*, uid: str) -> dict[str, Any]:
    ensure_apps_v1_pricing_runtime()
    result = PricingMarketDataSetBinding.delete(uid)
    return {
        "detail": "Deleted pricing market-data binding.",
        "uid": uid,
        "deleted_count": _deleted_count(result),
    }


def _deleted_count(result: Mapping[str, Any] | None) -> int:
    if not result:
        return 0
    return int(result.get("deleted_count") or 0)
