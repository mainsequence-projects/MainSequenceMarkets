from __future__ import annotations

from collections.abc import Iterable

from mainsequence.meta_tables import PlatformManagedMetaTable, PlatformTimeIndexMetaData

from msm.base import MarketsBase


def _metatable_provider_model_sources() -> list[type[MarketsBase]]:
    from msm.maintenance.models import MarketsMetaTableCatalogTable
    from msm.models import markets_sqlalchemy_models
    from msm_portfolios.models import portfolio_sqlalchemy_models
    from msm_pricing.meta_tables import pricing_sqlalchemy_models

    return [
        MarketsMetaTableCatalogTable,
        *markets_sqlalchemy_models(),
        *portfolio_sqlalchemy_models(),
        *pricing_sqlalchemy_models(),
    ]


def _is_metatable_provider_model(model: type[MarketsBase]) -> bool:
    return issubclass(model, (PlatformManagedMetaTable, PlatformTimeIndexMetaData))


def _dedupe_metatable_provider_models(
    models: Iterable[type[MarketsBase]],
) -> tuple[type[MarketsBase], ...]:
    deduped: list[type[MarketsBase]] = []
    seen_models: set[type[MarketsBase]] = set()
    model_by_identifier: dict[str, type[MarketsBase]] = {}

    for model in models:
        if not isinstance(model, type) or not issubclass(model, MarketsBase):
            continue
        if not _is_metatable_provider_model(model):
            continue
        identifier = str(getattr(model, "__metatable_identifier__", "") or "")
        if not identifier:
            raise ValueError(f"Migration model {model.__name__} is missing an identifier.")
        existing = model_by_identifier.get(identifier)
        if existing is not None and existing is not model:
            raise ValueError(
                "Duplicate MetaTable provider model identifier "
                f"{identifier!r} for {existing.__name__} and {model.__name__}."
            )
        model_by_identifier[identifier] = model
        if model in seen_models:
            continue
        seen_models.add(model)
        deduped.append(model)

    return tuple(deduped)


METATABLE_PROVIDER_MODELS: tuple[type[MarketsBase], ...] = _dedupe_metatable_provider_models(
    _metatable_provider_model_sources()
)
"""Library-owned MetaTable models managed by the SDK Alembic provider."""


def metatable_provider_models() -> list[type[MarketsBase]]:
    """Return the package-owned MetaTable provider model scope."""

    return list(METATABLE_PROVIDER_MODELS)


__all__ = [
    "METATABLE_PROVIDER_MODELS",
    "metatable_provider_models",
]
