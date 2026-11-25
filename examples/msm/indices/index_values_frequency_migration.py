"""The provider's own migrations for its 1-minute and daily Index-value tables.

The provider lists its table classes, one class statement per cadence, as
`metatable_models`: frequency is part of the MetaTable identity and the physical storage
table name. In a project this provider is `<package>/migrations/__init__.py`, which
`metatables migrations scaffold` creates with its `env.py` and versions folder.
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

from examples.msm.indices.plain_index_values import (  # noqa: E402
    FREQUENCY_STORAGE_MODELS,
    PROVIDER_NAMESPACE,
    PROVIDER_STORAGE_APP,
    ProviderBase,
)

ProviderAlembicVersion = build_alembic_version_metatable(
    class_name="IndexValuesExampleAlembicVersion",
    namespace=PROVIDER_NAMESPACE,
    identifier=f"{PROVIDER_STORAGE_APP}.alembic_version",
    schema=None,
    table_name=f"{PROVIDER_STORAGE_APP}__alembic_version",
)

migration = build_metatable_migration_provider(
    package=PROVIDER_STORAGE_APP,
    migration_namespace=PROVIDER_NAMESPACE,
    script_location=f"{PROVIDER_STORAGE_APP}.migrations:",
    version_location_prefix=f"{PROVIDER_STORAGE_APP}.migrations:versions",
    target_metadata=ProviderBase.metadata,
    alembic_registry=ProviderAlembicVersion,
    metatable_models=FREQUENCY_STORAGE_MODELS,
)

__all__ = ["FREQUENCY_STORAGE_MODELS", "migration"]
