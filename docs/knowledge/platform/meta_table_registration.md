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


def register_platform_managed_markets(data_source_uid: str):
    return register_markets_meta_tables(
        data_source_uid=data_source_uid,
        management_mode="platform_managed",
        labels=["markets"],
        open_for_everyone=False,
        protect_from_deletion=True,
    )
```

`register_markets_meta_tables(...)` registers every model returned by
`markets_sqlalchemy_models()` in foreign-key dependency order and returns the
`target_meta_table_uid_by_fullname` mapping needed by repository contexts. The
batch helper threads already-registered parent UIDs into child registration
requests so SQLAlchemy foreign-key contracts resolve deterministically.

Applications and examples should use `msm.start(...)` as the process preflight
step when they need the complete MetaTable bootstrap:

```python
import msm

runtime = msm.start(labels=["markets"])
context = runtime.context
```

Call this once near application or example startup, before importing
MetaTable-backed models, repositories, or services. The call registers the
markets table set, builds the repository context, and caches the runtime for the
current Python process. A second call with the same arguments returns the cached
runtime; a second call with different arguments raises instead of silently
rotating table names or execution context.

Example platform resources must use the example MetaTable namespace before any
`msm.models` import maps the SQLAlchemy classes:

```python
import msm

runtime = msm.start(
    namespace="mainsequence.examples",
    labels=["asset-crud-example"],
)
```

The namespace cannot be changed safely after `msm.models` is imported because
`PlatformManagedMetaTable` derives the physical storage hash while SQLAlchemy
maps each model class. Use the independent example bootstrap module when running
examples:

```python
from examples.platform.bootstrap import start_examples_runtime

runtime = start_examples_runtime(labels=["asset-crud-example"])
context = runtime.context
```

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
        labels=["markets"],
        introspect=True,
    )
```

External mode does not import application ORM code into the backend. The
application registers a neutral table contract derived from the `msm` SQLAlchemy
model metadata.

## Repository Context

Repository and service functions need the MetaTable UID mapping returned by
registration.

```python
from msm.repositories.base import MarketsRepositoryContext

context = MarketsRepositoryContext(
    target_meta_table_uid_by_fullname=result.target_meta_table_uid_by_fullname,
    limits={"max_rows": 1000, "statement_timeout_ms": 15000},
)
```

Operations compiled by repositories use the `compiled-sql.v1` platform protocol.
Application code keeps SQLAlchemy ergonomics; TS Manager receives SQL, bound
parameters, scope tables, limits, and operation kind.
