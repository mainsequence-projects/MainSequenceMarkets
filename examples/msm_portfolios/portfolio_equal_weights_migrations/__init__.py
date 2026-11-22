"""The equal-weight example's own migrations: its interpolated-price table, and no Markets table.

Apply the committed revision after Markets' own migrations, in each database:

    metatables --local migrations upgrade \\
        --provider examples.msm_portfolios.portfolio_equal_weights_migrations:migration head

Another interpolation configuration is another table, with another committed revision of
this provider. Apply the committed ones first, then autogenerate that one with
`metatables --local migrations revision` and the same `--provider`.
"""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import use_local_runtime  # noqa: E402

# MetaTables registers a provider's tables before it runs a revision, so this example
# selects the local runtime as it loads. A project's own provider has no such line: its
# deployment's migration Job applies it to the hosted Environment.
use_local_runtime()

from metatables.migrations import (  # noqa: E402
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)

from examples.msm_portfolios.portfolio_equal_weights_config import (  # noqa: E402
    INTERPOLATED_PRICES_STORAGE,
    PROVIDER_NAMESPACE,
    PROVIDER_STORAGE_APP,
    ProviderBase,
)

MODULE = "examples.msm_portfolios.portfolio_equal_weights_migrations"

EqualWeightExampleAlembicVersion = build_alembic_version_metatable(
    class_name="EqualWeightExampleAlembicVersion",
    namespace=PROVIDER_NAMESPACE,
    identifier=f"{PROVIDER_STORAGE_APP}.alembic_version",
    schema=None,
    table_name=f"{PROVIDER_STORAGE_APP}__alembic_version",
)

migration = build_metatable_migration_provider(
    package=PROVIDER_STORAGE_APP,
    migration_namespace=PROVIDER_NAMESPACE,
    script_location=f"{MODULE}:",
    version_location_prefix=f"{MODULE}:versions",
    target_metadata=ProviderBase.metadata,
    alembic_registry=EqualWeightExampleAlembicVersion,
    metatable_models=[INTERPOLATED_PRICES_STORAGE],
)

__all__ = ["EqualWeightExampleAlembicVersion", "migration"]
