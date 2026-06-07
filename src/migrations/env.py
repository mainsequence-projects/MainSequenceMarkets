from __future__ import annotations

from mainsequence.meta_tables.migrations.env import run_mainsequence_alembic_env

from msm.base import MARKETS_DEFAULT_SCHEMA, MARKETS_SCHEMA
from migrations import migration as default_migration


def _included_schema(name: str | None) -> bool:
    if MARKETS_SCHEMA is None:
        return name in (None, MARKETS_DEFAULT_SCHEMA)
    return name == MARKETS_SCHEMA


run_mainsequence_alembic_env(
    default_provider=default_migration,
    included_schema=_included_schema,
)
