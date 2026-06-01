# MetaTable Registration

`msm` persists market-domain records through SQLAlchemy models registered as
Main Sequence MetaTables. The library owns the model definitions and dependency
order; TS Manager owns governed execution.

## Platform Managed

Use platform-managed models when TS Manager should own physical tables on the
configured DynamicTable data source. Creating or evolving those tables is now
handled by `msm migrations ...` admin commands, not by runtime startup.

Market models inherit `MarketsMetaTableMixin`, which itself inherits the SDK
`MigrationManagedMetaTable` mixin. Time-indexed DataNode storage inherits
`MigrationManagedTimeIndexMetaData` through `MarketsTimeIndexMetaTableMixin`.
Do not set `__tablename__` on normal markets MetaTable models. The SDK derives
the physical table name from the stable migration-managed storage identity.

Every concrete markets MetaTable model must declare `__metatable_description__`.
That description is the durable platform-level discovery text copied into the
registered MetaTable and the internal markets catalog. It should state the row
grain and business use of the table; it should not be a generic column list.
DataNode output storage classes follow the same rule, and their default DataNode
descriptions are sourced from the storage table's `__metatable_description__`.
Every physical column must also carry non-empty SQLAlchemy `info["description"]`
metadata so catalog consumers and generated UIs can explain fields without
guessing from column names.

```python
import msm


runtime = msm.start_engine(
    management_mode="platform_managed",
    open_for_everyone=False,
    protect_from_deletion=True,
)
```

`msm.start_engine(...)` is the supported runtime attachment entrypoint for
platform-managed markets tables. It resolves requested models in foreign-key
dependency order, verifies SDK migration status and catalog finalization, reads
the maintenance catalog, and binds registered platform `MetaTable` objects back
onto their SQLAlchemy model classes. It must not create application tables,
apply migrations, or repair catalog drift.

The schema mutation entrypoint is the admin CLI:

```bash
msm migrations upgrade
```

The lower-level `register_markets_meta_tables(...)` helper remains an internal
building block for migration/admin flows. Normal applications and examples
should not use it as their registration workflow.

Catalog bookkeeping is keyed by the globally unique MetaTable identifier from
`__metatable_identifier__`, for example `AssetType` in the default namespace or
`mainsequence.examples.AssetType` when a namespace override is configured before
model import. The registered platform `MetaTable.uid` is only known after
migration finalization and catalog attach. Row operations read that UID from the
bound model when compiling operation scope. SQLAlchemy table names are storage
contract details, not runtime identity keys.

Foreign keys between platform-managed MetaTables use the SDK class-based helper:

```python
from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy.orm import mapped_column
from sqlalchemy.types import Uuid

from msm.models.assets import AssetTable


asset_uid = mapped_column(
    Uuid(as_uuid=True),
    MetaTableForeignKey(
        AssetTable,
        column="uid",
        ondelete="RESTRICT",
    ),
    nullable=False,
)
```

The authored target is the `AssetTable` model class. `register()` resolves or
recursively registers that target and writes the target `MetaTable.uid` into the
backend foreign-key contract. Do not build platform-managed foreign keys from
`Target.__table__` strings or caller-maintained table-name maps.

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

Use `msm.start_engine(...)` as an explicit startup preflight when an application
wants to verify and attach the complete MetaTable set during process
initialization:

```python
import msm

msm.start_engine()
```

`msm.start_engine(...)` is catalog-based and read-only. Startup first verifies
the SDK migration stream, then attaches the existing
`msm.maintenance.models.MarketsMetaTableCatalogTable` and reads catalog rows for
requested identifiers. Tables missing from the catalog are treated as missing
migration finalization, not as permission to register application tables.

The catalog is finalized by `msm migrations upgrade`. That command applies SDK
migrations, receives refreshed platform `MetaTable` UIDs from TS Manager, and
writes the catalog projection with the current platform UID, namespace,
identifier, description, model name, SDK version, and local contract hash. The
catalog is intentionally MetaTable-specific; DataNode registration state belongs
in a separate catalog if it is needed later.

When startup attaches an already-cataloged platform-managed MetaTable, it
introspects the physical table before exposing it to row APIs.
The preflight checks required columns, extra columns, expected index names,
index columns, and index uniqueness. A stale table can therefore fail during
runtime attachment instead of later during a compiled upsert. For example,
`AssetType.upsert(...)` uses `ON CONFLICT (asset_type)`, so the physical
`AssetType` table must have the unique `asset_type` index declared by
`AssetTypeTable`; a same-named non-unique index is treated as catalog drift and
must be repaired or migrated before normal startup.

The same rule applies to the internal maintenance catalog itself. Installations
with an older catalog physical table that still contains removed fields such as
`storage_hash` must repair or recreate that catalog resource before normal
startup.

For narrow explicit preflight, pass `models=[...]` to verify and attach only the
tables the process needs:

```python
import msm

msm.start_engine(models=["Asset"])
```

Project-local extension models use the same startup boundary. The registered
artifact is the SQLAlchemy MetaTable model class, not the Pydantic row wrapper:

```python
import uuid

import msm
from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import String, Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin
from msm.models.assets import AssetTable


class MyAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "com.my_company.markets.MyAssetDetails"
    __metatable_extra_hash_components__ = {"storage_name": "my_asset_details"}
    __metatable_description__ = (
        "Project-local asset details keyed one-to-one by AssetTable.uid for "
        "custom analytics and internal classification."
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(AssetTable, column="uid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        info={"description": "Canonical AssetTable uid for this custom detail row."},
    )
    internal_asset_class: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={"description": "Internal asset class assigned by the project."},
    )


msm.start_engine(models=[MyAssetDetailsTable])
```

Startup expands class-based `MetaTableForeignKey(...)` dependencies, so
`AssetTable` is verified and attached before `MyAssetDetailsTable`. The caller
does not pass a target table name or MetaTable UID.

If a project wants a typed row API for that table, subclass
`MarketsMetaTableRow` and keep it as a Pydantic row-operation wrapper:

```python
import uuid
from typing import ClassVar

from pydantic import AliasChoices, Field

from msm.api.base import MarketsMetaTableRow


class MyAssetDetails(MarketsMetaTableRow):
    __table__: ClassVar[type[MyAssetDetailsTable]] = MyAssetDetailsTable
    __required_tables__: ClassVar[list[type[MyAssetDetailsTable]]] = [
        MyAssetDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    internal_asset_class: str
```

The row wrapper is not registered as a MetaTable. It can be passed as a
`models=[...]` selector, but startup still normalizes it to the backing
SQLAlchemy model before catalog attachment.

See `examples/msm/platform/custom_asset_details_extension.py` for the same
extension shape in executable example form.

`runtime.table("Asset")` returns a single registered MetaTable handle with the
SQLAlchemy model, MetaTable UID, optional registered `MetaTable` object, limits,
timeout, and namespace. It remains available for lower-level repository or
service internals. User-facing examples should operate through typed
`msm.api.*` class methods and avoid passing table handles around.

Production applications normally do not pass a runtime namespace override. They
use the library's built-in MetaTable identity. They also normally leave
`MSM_AUTO_REGISTER_NAMESPACE` unset, so a missing table remains a deployment
error.

When explicit runtime attachment is used, call it once during application
initialization, before row operations, repositories, or services depend on the
registered tables. The call verifies migrations and the selected markets table
set, builds the repository context, and caches the runtime for the current
Python process. A second call with the same arguments returns the cached
runtime; a second call with different arguments raises instead of silently
rotating table names or execution context.

Runtime attachment emits structured Main Sequence `info` logs for namespace
selection, migration verification, catalog attachment, repository context
creation, final runtime creation, and cached-runtime reuse. Missing catalog
rows, stale catalog hashes, or missing backend `MetaTable.uid` resources fail
startup and must be corrected by `msm migrations upgrade` or an explicit
admin/platform repair.

`msm.start_engine(...)` does not accept labels because initialization should
not broadcast the same labels to every platform resource. The returned runtime
exposes `runtime.meta_tables`, `runtime.meta_table_models`, and
`runtime.data_nodes` so callers can decide which concrete MetaTables or
DataNodes need labels or other follow-up handling. When `models=[...]` is used,
`runtime.meta_tables` and `runtime.meta_table_models` contain only the selected
registered models.

Examples and notebooks can use `MSM_AUTO_REGISTER_NAMESPACE` only as a startup
namespace default. The explicit startup call is still required before row
operations:

```python
import os

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm
from msm.api.assets import Asset

msm.start_engine(models=["AssetType", "Asset"])
Asset.upsert(unique_identifier="example-asset-btc", asset_type="crypto")
```

With the environment variable set, `msm.start_engine(...)` uses the example
namespace, verifies migrations, and attaches the finalized catalog rows for the
selected tables.
The namespace cannot be changed safely after `msm.models` or
`msm.maintenance.models` is imported because `PlatformManagedMetaTable` derives
the physical storage hash while SQLAlchemy maps each model class.

Examples can still use explicit startup when the workflow is specifically
demonstrating runtime attachment. When `namespace` is omitted,
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

Use external-registered mode when an admin workflow has already registered
application-owned physical tables and finalized the markets catalog. Runtime
startup still attaches from catalog only. It does not perform external table
registration.

```python
import msm


runtime = msm.start_engine(
    management_mode="external_registered",
)
```

External mode does not import application ORM code into the backend. The
admin migration/registration flow registers a neutral table contract derived
from the `msm` SQLAlchemy model metadata. If an external registration flow has
to provide already registered FK targets explicitly, pass them through the SDK's
model-keyed `target_meta_tables={TargetModel: meta_table_uid}` input; do not key
runtime state by SQLAlchemy table names.

## Table Handles And Repository Context

Repository and service functions assume the relevant model classes have already
been bound by `msm.start_engine(...)` or `msm.attach_schemas(...)`. Single-table
helpers should receive a `MarketsMetaTableHandle`; multi-table helpers should
receive the full `MarketsRepositoryContext`.

```python
from msm.repositories.base import MarketsRepositoryContext

context = MarketsRepositoryContext(
    limits={"max_rows": 1000, "statement_timeout_ms": 15000},
)
asset_table = context.table("Asset")
```

Operations compiled by repositories use the `compiled-sql.v1` platform protocol.
Application code keeps SQLAlchemy ergonomics; TS Manager receives SQL, bound
parameters, scope tables, limits, and operation kind.
