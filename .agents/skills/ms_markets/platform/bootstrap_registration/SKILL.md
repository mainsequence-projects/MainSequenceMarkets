---
name: mainsequence-markets-bootstrap-registration
description: Use this skill when changing, documenting, or reviewing ms-markets runtime attachment, project extension table wiring, or row API startup behavior. MetaTable migrations are handled by mainsequence-sdk; this skill keeps ms-markets runtime attachment separate from SDK migration ownership.
---

# Main Sequence Markets Runtime Attachment

Use this skill for ms-markets runtime attachment after MetaTable migrations have
already been handled by `mainsequence-sdk`.

Schema changes and MetaTable registration belong to the SDK migration provider:

- `mainsequence.meta_tables.migrations.AlembicMetaTableMigration`
- the SDK MetaTable migration CLI
- the SDK migration tutorial and knowledge docs
- the project-local migration provider, when the project defines one

ms-markets runtime startup attaches to already-migrated tables. It does not own
schema migration, schema apply logic, migration registry rows, or SDK migration
status.

## Core Rule

Run the SDK MetaTable migration provider before runtime attachment.

Application code then attaches through `msm.start_engine(...)` before using row
APIs or DataNode writes:

```python
import msm

msm.start_engine(models=["AssetType", "Asset"])
```

Do not recommend row-class schema shortcuts such as:

```python
Asset.create_schemas()
```

Typed row classes such as `Asset`, `Account`, and `Portfolio` are row-operation
APIs. They may depend on an active runtime, but they do not own schema
bootstrap.

`msm.start_engine(...)` must attach runtime state only. It must not apply
migrations, register application tables, reconcile table specs, or create
schemas on first row use.

## This Skill Owns

- `msm.start_engine(...)` usage in examples, tutorials, docs, and tests.
- Runtime attachment behavior under `src/msm/bootstrap.py`.
- Model graph extension through `src/msm/models/__init__.py` and
  `markets_sqlalchemy_models()`.
- Pricing extension bootstrap through `msm_pricing.bootstrap` and
  `pricing_sqlalchemy_models()`.
- Typed row API entry wiring for MetaTable-backed Pydantic rows that subclass
  `MarketsMetaTableRow` and point at a registered SQLAlchemy model through
  `__table__`.
- The runtime boundary between SDK-managed MetaTable migration and typed row
  operations.

## This Skill Does Not Own

- Generic Main Sequence MetaTable semantics; use
  `.agents/skills/mainsequence/data_publishing/meta_tables/SKILL.md`.
- Generic DataNode update-process design; use
  `.agents/skills/mainsequence/data_publishing/data_nodes/SKILL.md`.
- Asset schema modeling details; use
  `.agents/skills/ms_markets/assets/asset_model_extension/SKILL.md`.
- Asset-indexed DataNode frame semantics; use
  `.agents/skills/ms_markets/assets/asset_indexed_data_nodes/SKILL.md`.
- Fixed-income pricing semantics; use
  `.agents/skills/ms_markets/pricing/fixed_income_curve_building/SKILL.md`.

## Read First

Before changing runtime attachment code, inspect:

1. `src/msm/bootstrap.py`
2. `src/msm/models/__init__.py`
3. `src/msm/models/registration.py`
4. `src/msm/api/base.py`
5. `mainsequence-sdk/docs/tutorial/metatable_migrations.md`
6. `mainsequence-sdk/docs/knowledge/meta_tables/migrations.md`
7. `mainsequence-sdk/mainsequence/meta_tables/migrations.py`

For pricing bootstrap changes, also inspect:

1. `src/msm_pricing/bootstrap.py`
2. `src/msm_pricing/meta_tables.py`

## User-Facing Startup Pattern

Admin workflows should run the SDK MetaTable migration provider before
application startup. Examples and application code should then attach once and
use row APIs:

```python
import msm
from msm.api.assets import Asset, AssetType

msm.start_engine(models=["AssetType", "Asset"])

AssetType.upsert(asset_type="equity", display_name="Equity")
Asset.upsert(unique_identifier="AAPL", asset_type="equity")
```

Use a narrow `models=[...]` list for small workflows. Include parent tables
before child behavior by selecting all required logical models; the startup
resolver keeps library dependency order.

Do not bootstrap or migrate implicitly from first row use. Row operations should
fail when the runtime has not been initialized for their required tables.

## Project Extension Tables

For project-local extension models, callers should be able to pass the extension
model class directly to startup after SDK migrations have registered it:

```python
import msm

from my_project.markets_models import MyAssetDetailsTable

msm.start_engine(models=[MyAssetDetailsTable])
```

The project migration provider owns schema and MetaTable registration. The only
ms-markets-specific migration hook is `after_register_metatables`, and it should
be used only when project tables need project table specs refreshed after SDK
registration.

Do not add built-in ms-markets tables to `after_register_metatables`.

Do not add project table specs when the project has no project-specific tables.

Do not create a project-local UID map, table-name resolver, direct runtime
registration flow, or row-class schema bootstrap.

When adding a new built-in markets MetaTable model:

1. Define the SQLAlchemy model with `MarketsMetaTableMixin`.
2. Add a meaningful `__metatable_description__`.
3. Declare platform-managed foreign keys with
   `MetaTableForeignKey(TargetModel, column=...)`.
4. Export the model from its package.
5. Add it to `markets_sqlalchemy_models()` in dependency order.
6. Add or update row APIs only after the storage model is in the graph.
7. Ensure SDK migration/provider work is handled outside this skill.
8. Update docs and tests so examples attach through `msm.start_engine(...)`
   after SDK migrations.

When adding DataNode storage, add the `PlatformTimeIndexMetaData` storage class
to the SDK migration provider. Do not rely on constructing a DataNode to
register its storage.

## Typed Row API Entries

Use `MarketsMetaTableRow` for simple typed row APIs backed by one primary
SQLAlchemy MetaTable model. `MarketsMetaTableRow` is a Pydantic `BaseModel`
subclass from `msm.api.base`; it is not registered as a backend MetaTable. It
provides the row operation methods (`create`, `upsert`, `filter`, lookups,
update, delete), while the SQLAlchemy model class is the registered artifact.
`MarketsRow` is only the legacy compatibility alias.

```python
import uuid
from typing import ClassVar

from pydantic import AliasChoices, Field

from msm.api.base import MarketsMetaTableRow
from my_project.markets_models import MyAssetDetailsTable


class MyAssetDetails(MarketsMetaTableRow):
    __table__: ClassVar[type[MyAssetDetailsTable]] = MyAssetDetailsTable
    __required_tables__: ClassVar[list[type[MyAssetDetailsTable]]] = [
        MyAssetDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
```

Rules:

- `__table__` points to the backing SQLAlchemy MetaTable model.
- `__required_tables__` lists the models that must be present in the active
  runtime before row operations execute.
- `__upsert_keys__` names the table columns used for upsert conflict handling.
- SDK migrations register the SQLAlchemy model's platform MetaTable.
- `msm.start_engine(...)` attaches it; the row class does not register, attach,
  or discover schemas.

```python
import msm

from my_project.api import MyAssetDetails
from my_project.markets_models import MyAssetDetailsTable

msm.start_engine(models=[MyAssetDetailsTable])

MyAssetDetails.upsert(asset_uid=asset_uid, internal_asset_class="equity")
```

Composite APIs that orchestrate multiple tables or return joined/domain-shaped
objects may inherit directly from Pydantic `BaseModel`, but their runtime
attachment still belongs to `msm.start_engine(models=[...])` and their table
dependencies must be explicit.

## Review Checklist

- User docs/examples call `msm.start_engine(...)`, not `*.create_schemas()`.
- New runtime models are present in the model graph in dependency order.
- SDK migration/provider work is handled outside this skill.
- Project table specs are refreshed through `after_register_metatables` only
  when project tables exist.
- Built-in ms-markets tables are not added to the project hook.
- Runtime attachment remains explicit and startup-scoped.
- Row APIs do not attach, register, or discover schemas on first use.
- DataNode storage is registered through the SDK migration provider before
  writes.
- Runtime attachment does not apply migrations, register application tables, or
  reconcile table specs.
