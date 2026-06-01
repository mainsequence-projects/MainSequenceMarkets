from __future__ import annotations

from mainsequence.meta_tables import MigrationManagedMetaTable

from msm.base import MarketsBase
from msm.models.registration import markets_meta_table_models

MIGRATION_MODEL_REGISTRY: tuple[type[MarketsBase], ...] = tuple(
    model
    for model in markets_meta_table_models()
    if isinstance(model, type) and issubclass(model, MigrationManagedMetaTable)
)
"""Library-owned MetaTable models managed by `msm migrations` commands."""


def migration_model_registry() -> list[type[MarketsBase]]:
    """Return the package-owned MetaTable migration scope."""

    return list(MIGRATION_MODEL_REGISTRY)


__all__ = [
    "MIGRATION_MODEL_REGISTRY",
    "migration_model_registry",
]
