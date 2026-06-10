# MetaTable Registration

`msm` persists market-domain records through SQLAlchemy models registered as
Main Sequence MetaTables. The library owns the model definitions and dependency
order; TS Manager owns governed execution.

## Platform Managed

Use platform-managed models when TS Manager should own physical tables on the
configured DynamicTable data source. Creating or evolving those tables is now
handled by the SDK `mainsequence migrations ... --provider migrations:migration`
admin flow, not by runtime startup.

Market models inherit `MarketsMetaTableMixin`, which itself inherits the SDK
`PlatformManagedMetaTable` base. Time-indexed DataNode storage inherits
`PlatformTimeIndexMetaTable` through `MarketsTimeIndexMetaTableMixin`.
Do not set `__tablename__` on normal markets MetaTable models. The markets
mixins assign physical SQLAlchemy table names from the storage app segment, the
authored MetaTable identifier, and the optional namespace suffix. Built-in
library tables use the package-owned default app segment `ms_markets`, producing
names such as `ms_markets__account`. Project-local extension tables may set
`__markets_storage_app__` to a project-owned app segment, producing names such
as `binance_spot__binancespotaccountdetails`. When
`MSM_AUTO_REGISTER_NAMESPACE` is set before model import, the namespace is
appended as a suffix, for example
`binance_spot__binancespotaccountdetails__mainsequence_examples`.

Every concrete markets MetaTable model must declare `__metatable_description__`.
That description is the durable platform-level discovery text copied into the
registered MetaTable. It should state the row grain and business use of the
table; it should not be a generic column list.
DataNode output storage classes follow the same rule, and their default DataNode
descriptions are sourced from the storage table's `__metatable_description__`.
Every physical column must also carry non-empty SQLAlchemy `info["description"]`
metadata so generated UIs can explain fields without
guessing from column names.

```python
import msm


runtime = msm.start_engine(
    management_mode="platform_managed",
)
```

`msm.start_engine(...)` is the supported runtime attachment entrypoint for
platform-managed markets tables. It resolves requested models in foreign-key
dependency order, resolves registered backend `MetaTable` and
`TimeIndexMetaTable` objects by each model's SQLAlchemy table name, and binds
those backend objects onto their SQLAlchemy model classes. It must not create
application tables, apply migrations, or repair catalog drift.

The schema mutation entrypoint is the admin CLI:

```bash
mainsequence migrations upgrade --provider migrations:migration head
```

MetaTable registration is migration-owned. Normal applications, examples, and
runtime bootstrap code should not call model `.register()` methods or local
registration helpers. The SDK migration provider resolves the package model
registry, applies Alembic migrations, and registers the MetaTables as part of
the admin migration flow.

Runtime lookup is keyed by the SQLAlchemy table name because the SDK migration
flow uses that name as the stable MetaTable identity. For example,
`AccountTable` resolves as `ms_markets__account`, or as
`ms_markets__account__mainsequence_examples` when
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` is set before model import.
The registered platform `MetaTable.uid` is only known after migration
finalization and runtime attachment. Row operations read that UID from the
bound model when compiling operation scope.

Foreign keys between platform-managed MetaTables are normal SQLAlchemy/Alembic
foreign keys:

```python
from sqlalchemy import ForeignKey
from sqlalchemy.orm import mapped_column
from sqlalchemy.types import Uuid

from msm.models.assets import AssetTable


asset_uid = mapped_column(
    Uuid(as_uuid=True),
    ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="RESTRICT"),
    nullable=False,
)
```

The authored target is the SQLAlchemy table/column. The SDK migration provider
reserves and finalizes the MetaTables, while Alembic renders and applies the
physical FK DDL from the SQLAlchemy metadata.

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

`msm.start_engine(...)` is direct and read-only. Startup queries backend
`MetaTable` and `TimeIndexMetaTable` resources by requested table names. Missing
backend rows are treated as missing migration finalization, not as permission to
register application tables.

The catalog is finalized by the SDK migration upgrade flow. That command applies
Alembic-rendered SQL through the backend migration endpoint, synchronizes the
provider MetaTable catalog, and runs the `msm` provider hook that writes the
catalog projection with the current platform UID, namespace, table name,
description, model name, and SDK version. The catalog is an inventory
projection, not the schema authority and not the runtime binding source. The
catalog is intentionally MetaTable-specific; DataNode registration state belongs
in a separate catalog if it is needed later.

When startup attaches platform-managed MetaTables, it partitions requested
models into normal `MetaTable` models and `PlatformTimeIndexMetaTable` storage
models, then performs one backend filter lookup per resource type keyed by
`model.__table__.name`. Runtime attachment does not call `MetaTable.get_by_uid(...)`
one table at a time and does not introspect physical storage. Physical schema
validation belongs to the SDK migration flow and explicit diagnostics, not to
normal application startup.

For narrow explicit startup, pass `models=[...]` to attach only the tables the
process needs:

```python
import msm

msm.start_engine(models=["Asset"])
```

Project-local extension models use the same startup boundary. The registered
artifact is the SQLAlchemy MetaTable model class, not the Pydantic row wrapper:

```python
import uuid

import msm
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import String, Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin
from msm.models.assets import AssetTable


class MyProjectMarketsMetaTableMixin(MarketsMetaTableMixin):
    __abstract__ = True
    __metatable_namespace__ = "com.my_company.markets"
    __markets_storage_app__ = "my_project_markets"


class MyAssetDetailsTable(MyProjectMarketsMetaTableMixin, MarketsBase):
    __markets_base_identifier__ = "MyAssetDetails"
    __metatable_description__ = (
        "Project-local asset details keyed one-to-one by AssetTable.uid for "
        "custom analytics and internal classification."
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="CASCADE"),
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

Startup expands SQLAlchemy `ForeignKey(...)` dependencies, so `AssetTable` is
verified and attached before `MyAssetDetailsTable`. The caller does not pass a
MetaTable UID.

`__metatable_namespace__` is the project-local default namespace for extension
models that inherit from the local mixin. `__markets_base_identifier__` is the
bare concept identifier that ms-markets combines with that namespace to produce
the globally unique MetaTable identifier:
`com.my_company.markets.MyAssetDetails`.

`MSM_AUTO_REGISTER_NAMESPACE` still overrides the mixin namespace when it is set
before model import. Use that for isolated tests and example environments, not
as the primary project extension contract.

`__markets_storage_app__` is only the SQLAlchemy physical table-name app
segment. It does not replace the logical MetaTable identifier, does not
participate in row API selection, and does not create a project-local UID map.
Set it in the class body before SQLAlchemy maps the table. Changing it after a
table has been migrated and registered points the model at a different physical
table name and must go through the normal SDK migration and registration path.

Projects with several extension tables can define an abstract local mixin once:

```python
class MyProjectMarketsMetaTableMixin(MarketsMetaTableMixin):
    __abstract__ = True
    __metatable_namespace__ = "com.my_company.markets"
    __markets_storage_app__ = "my_project_markets"


class MyAssetDetailsTable(MyProjectMarketsMetaTableMixin, MarketsBase):
    __markets_base_identifier__ = "MyAssetDetails"
    __metatable_description__ = (
        "Project-local asset details keyed one-to-one by AssetTable.uid for "
        "custom analytics and internal classification."
    )
```

Already-qualified `__metatable_identifier__` values are still accepted for
existing models. Prefer `__markets_base_identifier__` on new project-local
extension models so the project mixin namespace and test namespace override
remain explicit.

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
registered tables. The call verifies the selected markets table set, builds the
repository context, and caches the runtime for the current Python process. A
second call with the same arguments returns the cached
runtime; a second call with different arguments raises instead of silently
rotating table names or execution context.

Runtime attachment emits structured Main Sequence `info` logs for namespace
selection, model resolution, direct backend attachment, repository context
creation, final runtime creation, and cached-runtime reuse. Missing backend
`MetaTable` or `TimeIndexMetaTable` resources fail startup and must be
corrected by the SDK migration upgrade flow or an explicit admin/platform
repair.

`msm.start_engine(...)` does not accept labels because initialization should
not broadcast the same labels to every platform resource. The returned runtime
exposes `runtime.meta_tables` and `runtime.meta_table_models` so callers can
decide which concrete MetaTables need labels or other follow-up handling. When
`models=[...]` is used, those runtime collections contain only the selected
registered models. DataNode classes are imported from their owning package
modules, not from the runtime attachment object.

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
namespace and resolves the selected backend tables by their namespaced
SQLAlchemy table identifiers.
The namespace cannot be changed safely after `msm.models` or
another MetaTable-backed package is imported because the markets mixins assign
the physical table name while SQLAlchemy maps each model class.

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
application-owned physical tables. Runtime startup still attaches by direct
backend lookup. It does not perform external table
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
been bound by `msm.start_engine(...)`. Single-table helpers should receive a
`MarketsMetaTableHandle`; multi-table helpers should receive the full
`MarketsRepositoryContext`.

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
