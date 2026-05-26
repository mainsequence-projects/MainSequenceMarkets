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
from msm.meta_tables import register_markets_meta_tables


def register_platform_managed_markets():
    return register_markets_meta_tables(
        management_mode="platform_managed",
        open_for_everyone=False,
        protect_from_deletion=True,
    )
```

`register_markets_meta_tables(...)` registers every model returned by
`markets_sqlalchemy_models()` in foreign-key dependency order and returns the
`target_meta_table_uid_by_fullname` mapping needed by repository contexts. The
batch helper threads already-registered parent UIDs into child registration
requests so SQLAlchemy foreign-key contracts resolve deterministically.

Applications and examples should use `msm.create_schemas(...)` as the process
initialization preflight when they need the complete MetaTable bootstrap:

```python
import msm

runtime = msm.create_schemas()
context = runtime.context
```

For narrow workflows, pass `models=[...]` to register only the tables the
process needs. String selectors avoid importing `msm.models` before an example
namespace is configured:

```python
import msm

runtime = msm.create_schemas(models=["Asset"])
asset_table = runtime.table("Asset")
```

`runtime.table("Asset")` returns a single registered MetaTable handle with the
SQLAlchemy model, MetaTable UID, optional registered `MetaTable` object, limits,
timeout, and namespace. Prefer that handle for single-table service helpers.
Use `runtime.context` when compiling operations that touch multiple registered
models.

Production applications normally do not pass a runtime namespace override. They
use the library's built-in MetaTable identity and keep
`runtime.context.namespace` as `None`.

Call this once during application or example initialization, before importing
MetaTable-backed models, repositories, or services. The call registers the
markets table set, builds the repository context, and caches the runtime for the
current Python process. A second call with the same arguments returns the cached
runtime; a second call with different arguments raises instead of silently
rotating table names or execution context.

Schema creation emits structured Main Sequence `info` logs for the namespace
selection, each MetaTable model being registered, registered MetaTable handles,
repository context creation, final runtime creation, and cached-runtime reuse.
These logs make the initialization preflight visible without changing the table
registration flow.

`msm.create_schemas(...)` does not accept labels because initialization should
not broadcast the same labels to every platform resource. The returned runtime
exposes `runtime.meta_tables`, `runtime.meta_table_models`, and
`runtime.data_nodes` so callers can decide which concrete MetaTables or
DataNodes need labels or other follow-up handling. When `models=[...]` is used,
`runtime.meta_tables` and `runtime.meta_table_models` contain only the selected
registered models.

Example platform resources must use the example MetaTable namespace before any
`msm.models` import maps the SQLAlchemy classes:

```python
import msm

runtime = msm.create_schemas(
    namespace="mainsequence.examples",
)
```

The namespace cannot be changed safely after `msm.models` is imported because
`PlatformManagedMetaTable` derives the physical storage hash while SQLAlchemy
maps each model class. Examples keep the namespace in a plain constant and call
the real bootstrap directly:

```python
import msm

from examples.platform.bootstrap import EXAMPLE_METATABLE_NAMESPACE

runtime = msm.create_schemas(namespace=EXAMPLE_METATABLE_NAMESPACE)
context = runtime.context
```

Asset-only examples can register and use just the asset table:

```python
import msm

from examples.platform.bootstrap import EXAMPLE_METATABLE_NAMESPACE
from msm.services import upsert_asset

runtime = msm.create_schemas(
    namespace=EXAMPLE_METATABLE_NAMESPACE,
    models=["Asset"],
)
asset_table = runtime.table("Asset")
upsert_asset(
    asset_table,
    unique_identifier="example-asset-btc",
    asset_type="crypto",
)
```

Service helpers such as `upsert_asset(asset_table, ...)` receive the table
handle, not a namespace argument. The handle already points at the MetaTable UID
registered for the selected namespace.

## External Registered

Use external-registered mode when the application owns table DDL with
SQLAlchemy, Alembic, Terraform, or another migration system. TS Manager still
registers the tables, enforces auth, and executes compiled operations.

```python
from msm.meta_tables import register_markets_meta_tables


def register_external_markets(data_source_uid: str, storage_hash_by_fullname: dict[str, str]):
    return register_markets_meta_tables(
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
