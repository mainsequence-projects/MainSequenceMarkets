from __future__ import annotations

from mainsequence.meta_tables.migrations import build_metatable_model_registry

from msm.base import MarketsBase


def _metatable_provider_model_sources() -> list[type[MarketsBase]]:
    from msm.models import markets_sqlalchemy_models
    from msm_portfolios.models import portfolio_sqlalchemy_models
    from msm_pricing.meta_tables import pricing_sqlalchemy_models

    return [
        *markets_sqlalchemy_models(),
        *portfolio_sqlalchemy_models(),
        *pricing_sqlalchemy_models(),
    ]


METATABLE_PROVIDER_MODELS: tuple[type[MarketsBase], ...] = tuple(
    build_metatable_model_registry(
        _metatable_provider_model_sources(),
        base=MarketsBase,
    )
)
"""Library-owned MetaTable models managed by the SDK Alembic provider."""


def metatable_provider_models() -> list[type[MarketsBase]]:
    """Return the package-owned MetaTable provider model scope."""

    return list(METATABLE_PROVIDER_MODELS)


__all__ = [
    "METATABLE_PROVIDER_MODELS",
    "metatable_provider_models",
]
