from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from msm.base import MarketsBase
from msm.models.registration import (
    MarketsManagementMode,
    MarketsMetaTableRegistrationResult,
    register_markets_meta_tables,
)
from msm.models.assets import AssetTable
from msm.models.indices import IndexTable

from .models.curves import CurveTable
from .models.index_convention_details import IndexConventionDetailsTable
from .models.pricing_details import AssetCurrentPricingDetailsTable

PricingManagementMode = MarketsManagementMode
PricingMetaTableRegistrationResult = MarketsMetaTableRegistrationResult
PricingModelSelector = str | type[MarketsBase]


def pricing_sqlalchemy_models() -> list[type[MarketsBase]]:
    """Return pricing SQLAlchemy models in MetaTable dependency order."""

    return [
        AssetTable,
        IndexTable,
        IndexConventionDetailsTable,
        CurveTable,
        AssetCurrentPricingDetailsTable,
    ]


def pricing_meta_table_fullname(model: type[MarketsBase]) -> str:
    return str(model.__table__.fullname)


def resolve_pricing_meta_table_model(model: PricingModelSelector) -> type[MarketsBase]:
    """Resolve a pricing MetaTable model class by class, name, identifier, or fullname."""

    if isinstance(model, type):
        return model

    model_key = str(model)
    for candidate in pricing_sqlalchemy_models():
        keys = {
            candidate.__name__,
            str(getattr(candidate, "__markets_base_identifier__", "")),
            str(getattr(candidate, "__metatable_identifier__", "")),
            pricing_meta_table_fullname(candidate),
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


def register_pricing_meta_tables(
    *,
    data_source_uid: str | None = None,
    management_mode: PricingManagementMode = "platform_managed",
    target_meta_table_uid_by_fullname: Mapping[str, Any] | None = None,
    labels: Sequence[str] | None = None,
    open_for_everyone: bool = False,
    protect_from_deletion: bool = False,
    introspect: bool | None = None,
    storage_hash_by_fullname: Mapping[str, str] | None = None,
    timeout: int | float | tuple[float, float] | None = None,
    models: Sequence[PricingModelSelector] | None = None,
) -> PricingMetaTableRegistrationResult:
    """Register pricing MetaTables while resolving core asset dependencies.

    The default pricing graph includes the core ``AssetTable`` before
    ``AssetCurrentPricingDetailsTable`` so FK target mappings are populated
    before pricing extension tables are registered.
    """

    resolved_models = resolve_pricing_meta_table_models(models)
    return register_markets_meta_tables(
        data_source_uid=data_source_uid,
        management_mode=management_mode,
        target_meta_table_uid_by_fullname=target_meta_table_uid_by_fullname,
        labels=labels,
        open_for_everyone=open_for_everyone,
        protect_from_deletion=protect_from_deletion,
        introspect=introspect,
        storage_hash_by_fullname=storage_hash_by_fullname,
        timeout=timeout,
        models=resolved_models,
    )


__all__ = [
    "PricingManagementMode",
    "PricingMetaTableRegistrationResult",
    "PricingModelSelector",
    "pricing_meta_table_fullname",
    "pricing_sqlalchemy_models",
    "register_pricing_meta_tables",
    "resolve_pricing_meta_table_model",
    "resolve_pricing_meta_table_models",
]
