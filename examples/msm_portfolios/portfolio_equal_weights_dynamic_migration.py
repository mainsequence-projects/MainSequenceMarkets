from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from mainsequence.meta_tables.migrations import (  # noqa: E402
    build_metatable_migration_provider,
    metadata_for_models,
)

from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    dynamic_storage_from_env,
)
from examples.msm.platform.bootstrap import (  # noqa: E402
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)
from migrations import MarketsAlembicVersion  # noqa: E402
from msm.settings import markets_namespace  # noqa: E402

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

DYNAMIC_INTERPOLATED_PRICES_STORAGE = dynamic_storage_from_env()

migration = build_metatable_migration_provider(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="migrations:",
    target_metadata=metadata_for_models([DYNAMIC_INTERPOLATED_PRICES_STORAGE]),
    alembic_registry=MarketsAlembicVersion,
    metatable_models=[DYNAMIC_INTERPOLATED_PRICES_STORAGE],
)

__all__ = ["DYNAMIC_INTERPOLATED_PRICES_STORAGE", "migration"]
