from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

V1_RUNTIME_MODELS = [
    "AssetType",
    "Asset",
    "OpenFigiAssetDetails",
    "AssetCategory",
    "AssetCategoryMembership",
    "Calendar",
    "CalendarDate",
    "CalendarSession",
    "CalendarEvent",
    "IndexType",
    "Index",
    "AccountAllocationModel",
    "AccountGroup",
    "Account",
    "AccountHoldingsSet",
    "AccountHoldingsStorage",
    "AccountTargetAllocation",
    "PositionSet",
    "Portfolio",
    "PortfolioMetadata",
    "PortfolioWeightsStorage",
    "TargetPositionsStorage",
    "AssetSnapshotsStorage",
]
V1_PORTFOLIO_RUNTIME_MODELS = [
    "AssetType",
    "Asset",
    "Calendar",
    "IndexType",
    "Index",
    "AccountAllocationModel",
    "AccountGroup",
    "Account",
    "AccountHoldingsSet",
    "AccountTargetAllocation",
    "PositionSet",
    "Portfolio",
    "PortfolioMetadata",
    "PortfolioWeightsStorage",
    "TargetPositionsStorage",
    "AssetSnapshotsStorage",
]
V1_PRICING_RUNTIME_MODELS = [
    "Asset",
    "AssetCurrentPricingDetails",
    "PricingMarketDataSet",
    "PricingMarketDataSetBinding",
]
_BOOTSTRAP_COMPLETE = False
_PORTFOLIO_BOOTSTRAP_COMPLETE = False
_PRICING_BOOTSTRAP_COMPLETE = False


def prepare_apps_v1_import_namespace() -> None:
    namespace = os.getenv("MSM_AUTO_REGISTER_NAMESPACE")
    if not namespace:
        return

    from msm.bootstrap import configure_metatable_namespace

    configure_metatable_namespace(namespace)


def ensure_apps_v1_runtime() -> Any | None:
    global _BOOTSTRAP_COMPLETE

    if _BOOTSTRAP_COMPLETE:
        return None

    namespace = os.getenv("MSM_AUTO_REGISTER_NAMESPACE")
    if not namespace:
        return None

    import msm_portfolios

    runtime = msm_portfolios.start_engine(
        namespace=namespace,
        models=V1_RUNTIME_MODELS,
    )
    _BOOTSTRAP_COMPLETE = True
    return runtime


def ensure_apps_v1_portfolio_runtime() -> Any | None:
    global _PORTFOLIO_BOOTSTRAP_COMPLETE

    if _PORTFOLIO_BOOTSTRAP_COMPLETE:
        return None

    runtime = ensure_apps_v1_runtime()
    if runtime is None and not _BOOTSTRAP_COMPLETE:
        return None

    _PORTFOLIO_BOOTSTRAP_COMPLETE = True
    return runtime


def ensure_apps_v1_pricing_runtime() -> Any | None:
    global _PRICING_BOOTSTRAP_COMPLETE

    if _PRICING_BOOTSTRAP_COMPLETE:
        return None

    namespace = os.getenv("MSM_AUTO_REGISTER_NAMESPACE")
    if not namespace:
        return None

    from msm_pricing.bootstrap import attach_pricing_schemas

    runtime = attach_pricing_schemas(
        namespace=namespace,
        models=V1_PRICING_RUNTIME_MODELS,
        seed_default_market_data_bindings=False,
        replace_default_market_data_bindings=False,
    )
    _PRICING_BOOTSTRAP_COMPLETE = True
    return runtime


def resolve_apps_v1_runtime(
    *,
    models: Sequence[Any],
    row_model_name: str,
):
    ensure_apps_v1_runtime()

    from msm.bootstrap import resolve_runtime

    return resolve_runtime(
        models=models,
        row_model_name=row_model_name,
    )


def resolve_apps_v1_portfolio_runtime(
    *,
    models: Sequence[Any],
    row_model_name: str,
):
    ensure_apps_v1_portfolio_runtime()

    from msm_portfolios.bootstrap import resolve_portfolio_models
    from msm.bootstrap import resolve_runtime

    return resolve_runtime(
        models=resolve_portfolio_models(models),
        row_model_name=row_model_name,
    )


__all__ = [
    "V1_PORTFOLIO_RUNTIME_MODELS",
    "V1_PRICING_RUNTIME_MODELS",
    "V1_RUNTIME_MODELS",
    "ensure_apps_v1_portfolio_runtime",
    "ensure_apps_v1_pricing_runtime",
    "ensure_apps_v1_runtime",
    "prepare_apps_v1_import_namespace",
    "resolve_apps_v1_portfolio_runtime",
    "resolve_apps_v1_runtime",
]
