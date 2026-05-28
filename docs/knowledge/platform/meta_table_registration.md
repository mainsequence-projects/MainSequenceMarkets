# MetaTable Registration

`msm` persists market-domain records through SQLAlchemy models registered as
Main Sequence MetaTables. The library owns the model definitions and dependency
order; TS Manager owns governed execution.

## Platform Managed

Use platform-managed registration when TS Manager should create or update the
physical tables on the configured DynamicTable data source.

Market models inherit `MarketsMetaTableMixin`, which itself inherits the SDK
`PlatformManagedMetaTable` mixin. Do not set `__tablename__` on normal markets
MetaTable models. The SDK derives the physical table name from storage-relevant
SQLAlchemy metadata, including columns, indexes, foreign keys, schema, and the
markets namespace.

```python
import msm


runtime = msm.start_engine(
    management_mode="platform_managed",
    open_for_everyone=False,
    protect_from_deletion=True,
)
```

`msm.start_engine(...)` is the supported startup entrypoint for
platform-managed markets tables. It resolves requested models in foreign-key
dependency order, uses the maintenance catalog before registering, and returns
the `target_meta_table_uid_by_fullname` mapping needed by repository contexts.
The lower-level `register_markets_meta_tables(...)` helper remains an internal
building block and migration escape hatch; normal applications and examples
should not use it as their registration workflow.

User-facing row operations use the active markets runtime. They do not attach
to MetaTables, register tables, or run platform discovery on first use. In
production, initialize the required schema set during application startup and
then use the typed API directly:

```python
import msm
from msm.api.assets import Asset

msm.start_engine(models=["Asset"])

asset = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)
```

If the runtime was not initialized, or if it was initialized without a required
table, row operations raise an initialization error that names the missing table
declarations.

Use `msm.start_engine(...)` as an explicit startup preflight when an
application wants to verify or create the complete MetaTable set during process
initialization:

```python
import msm

msm.start_engine()
```

`msm.start_engine(...)` is catalog-based. Startup first attaches or creates
the internal `msm.maintenance.models.MarketsMetaTableCatalogTable`, then reads
that catalog before touching application tables. Requested tables already
present in the catalog are attached by `MetaTable.uid`. Requested tables missing
from the catalog are looked up once on the platform so pre-catalog installations
can be imported. Only tables missing from both the catalog and the platform are
registered, and each successful registration is written back to the catalog
with the platform `MetaTable.uid`, namespace, identifier, description, storage
hash, and local contract hash.

For narrow explicit preflight, pass `models=[...]` to register only the tables
the process needs:

```python
import msm

msm.start_engine(models=["Asset"])
```

`runtime.table("Asset")` returns a single registered MetaTable handle with the
SQLAlchemy model, MetaTable UID, optional registered `MetaTable` object, limits,
timeout, and namespace. It remains available for lower-level repository or
service internals. User-facing examples should operate through typed
`msm.api.*` class methods and avoid passing table handles around.

Production applications normally do not pass a runtime namespace override. They
use the library's built-in MetaTable identity. They also normally leave
`MSM_AUTO_REGISTER_NAMESPACE` unset, so a missing table remains a deployment
error.

When explicit schema creation is used, call it once during application
initialization, before row operations, repositories, or services depend on the
registered tables. The call registers the selected markets table set, builds the
repository context, and caches the runtime for the current Python process. It
does not re-register tables that are already present in the maintenance catalog.
A second call with the same arguments returns the cached runtime; a second call
with different arguments raises instead of silently rotating table names or
execution context.

Schema creation emits structured Main Sequence `info` logs for the namespace
selection, catalog attach/create, application tables imported into the catalog,
application tables registered because they were missing, repository context
creation, final runtime creation, and cached-runtime reuse. Tables that already
resolve through the catalog are attached without being registered again.

`msm.start_engine(...)` does not accept labels because initialization should
not broadcast the same labels to every platform resource. The returned runtime
exposes `runtime.meta_tables`, `runtime.meta_table_models`, and
`runtime.data_nodes` so callers can decide which concrete MetaTables or
DataNodes need labels or other follow-up handling. When `models=[...]` is used,
`runtime.meta_tables` and `runtime.meta_table_models` contain only the selected
registered models.

Examples and notebooks can use `MSM_AUTO_REGISTER_NAMESPACE` only as a startup
namespace default. The explicit bootstrap call is still required before row
operations:

```python
import os

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

from msm.api.assets import Asset

Asset.create_schemas()
Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
```

With the environment variable set, `Asset.create_schemas()` uses the example
namespace and runs the catalog bootstrap for the row class's required tables.
The namespace cannot be changed safely after `msm.models` or
`msm.maintenance.models` is imported because `PlatformManagedMetaTable` derives
the physical storage hash while SQLAlchemy maps each model class.

Examples can still use explicit bootstrap when the workflow is specifically
demonstrating schema registration. When `namespace` is omitted,
`MSM_AUTO_REGISTER_NAMESPACE` is used first, and the default markets namespace is
used only when the environment variable is unset:

```python
import msm

msm.start_engine(
    models=["Asset"],
)
```

Repository and service helpers receive table handles or context objects, not a
namespace argument. Those lower-level objects already point at the MetaTable UID
registered for the selected namespace. Normal examples should avoid exposing
that plumbing and use the `msm.api` row API instead.

## External Registered

Use external-registered mode when the application owns table DDL with
SQLAlchemy, Alembic, Terraform, or another migration system. TS Manager still
registers the tables, enforces auth, and executes compiled operations.

```python
import msm


runtime = msm.start_engine(
    data_source_uid=data_source_uid,
    management_mode="external_registered",
    storage_hash_by_fullname=storage_hash_by_fullname,
    introspect=True,
)
```

External mode does not import application ORM code into the backend. The
application registers a neutral table contract derived from the `msm` SQLAlchemy
model metadata.

## Table Handles And Repository Context

Repository and service functions need registered MetaTable UIDs. Single-table
helpers should receive a `MarketsMetaTableHandle`; multi-table helpers should
receive the full `MarketsRepositoryContext`.

```python
from msm.repositories.base import MarketsRepositoryContext

context = MarketsRepositoryContext(
    target_meta_table_uid_by_fullname=result.target_meta_table_uid_by_fullname,
    limits={"max_rows": 1000, "statement_timeout_ms": 15000},
)
asset_table = context.table("Asset")
```

Operations compiled by repositories use the `compiled-sql.v1` platform protocol.
Application code keeps SQLAlchemy ergonomics; TS Manager receives SQL, bound
parameters, scope tables, limits, and operation kind.
