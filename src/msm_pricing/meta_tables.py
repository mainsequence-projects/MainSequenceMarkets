from __future__ import annotations

from collections.abc import Sequence

from msm.base import MarketsBase, markets_meta_table_identifier
from msm.models.registration import (
    MarketsManagementMode,
    MarketsMetaTableRegistrationResult,
)
from msm.models.assets import AssetTable
from msm.models.indices import IndexTable, IndexTypeTable

from .models.curves import CurveTable
from .models.index_convention_details import IndexConventionDetailsTable
from .models.market_data_bindings import (
    PricingMarketDataSetBindingTable,
    PricingMarketDataSetTable,
)
from .models.pricing_details import AssetCurrentPricingDetailsTable

PricingManagementMode = MarketsManagementMode
PricingMetaTableRegistrationResult = MarketsMetaTableRegistrationResult
PricingModelSelector = str | type[MarketsBase]


def pricing_sqlalchemy_models() -> list[type[MarketsBase]]:
    """Return pricing SQLAlchemy models in MetaTable dependency order.

    Includes the ADR 0017 pricing DataNode output storage MetaTables after their
    FK target MetaTables (``AssetTable``, ``IndexTable``, ``CurveTable``).
    """

    return [
        AssetTable,
        IndexTypeTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
        AssetCurrentPricingDetailsTable,
        PricingMarketDataSetTable,
        PricingMarketDataSetBindingTable,
        *_pricing_data_node_storage_models(),
    ]


def _pricing_data_node_storage_models() -> list[type[MarketsBase]]:
    """Return ADR 0017 pricing DataNode output storage MetaTables in FK order.

    Imported lazily to avoid an import cycle: the pricing storage module imports
    domain/pricing MetaTables for its FK targets.
    """

    from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
    from msm_pricing.data_nodes.index_fixings.storage import IndexFixingsStorage
    from msm_pricing.data_nodes.pricing_details.storage import AssetPricingDetailsStorage

    return [
        DiscountCurvesStorage,
        IndexFixingsStorage,
        AssetPricingDetailsStorage,
    ]


def pricing_meta_table_identifier(model: type[MarketsBase]) -> str:
    return markets_meta_table_identifier(model)


def resolve_pricing_meta_table_model(model: PricingModelSelector) -> type[MarketsBase]:
    """Resolve a pricing MetaTable model class by class, name, or identifier."""

    if isinstance(model, type):
        return model

    model_key = str(model)
    for candidate in pricing_sqlalchemy_models():
        identifier = candidate.__metatable_identifier__
        keys = {
            candidate.__name__,
            identifier,
            identifier.rsplit(".", 1)[-1],
            pricing_meta_table_identifier(candidate),
            candidate.__table__.name,
        }
        if model_key in keys:
            return candidate
    raise ValueError(f"Unknown pricing MetaTable model {model_key!r}.")


def resolve_pricing_meta_table_models(
    models: Sequence[PricingModelSelector] | None = None,
) -> list[type[MarketsBase]]:
    """Resolve selected pricing MetaTable models in pricing dependency order."""

    all_models = pricing_sqlalchemy_models()
    if models is None:
        return all_models

    selected = {resolve_pricing_meta_table_model(model) for model in models}
    resolved = [model for model in all_models if model in selected]
    missing = selected.difference(resolved)
    if missing:
        missing_names = ", ".join(sorted(model.__name__ for model in missing))
        raise ValueError(f"Unsupported pricing MetaTable model selection: {missing_names}.")
    return resolved


__all__ = [
    "PricingManagementMode",
    "PricingMetaTableRegistrationResult",
    "PricingModelSelector",
    "pricing_meta_table_identifier",
    "pricing_sqlalchemy_models",
    "resolve_pricing_meta_table_model",
    "resolve_pricing_meta_table_models",
]
