"""Migration provider for the example's 1-minute and daily Index-value tables.

Build cadence-configured models before constructing the provider. This makes
frequency part of the MetaTable identity and the physical storage table name.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from mainsequence.meta_tables.migrations import (  # noqa: E402
    build_metatable_migration_provider,
    metadata_for_models,
)

from examples.msm.indices.plain_index_values import (  # noqa: E402
    FREQUENCY_STORAGE_MODELS,
)
from migrations import MarketsAlembicVersion  # noqa: E402
from msm.settings import markets_namespace  # noqa: E402

migration = build_metatable_migration_provider(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="migrations:",
    target_metadata=metadata_for_models(FREQUENCY_STORAGE_MODELS),
    alembic_registry=MarketsAlembicVersion,
    metatable_models=FREQUENCY_STORAGE_MODELS,
)

__all__ = ["FREQUENCY_STORAGE_MODELS", "migration"]
