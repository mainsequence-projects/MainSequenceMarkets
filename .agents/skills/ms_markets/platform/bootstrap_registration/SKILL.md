---
name: mainsequence-markets-bootstrap-registration
description: Use this skill when changing, documenting, or reviewing ms-markets runtime attachment, model resolution, catalog-based table binding, row API startup behavior, or DataNode startup prerequisites. This skill owns the rule that ms-markets runtime startup attaches to already-migrated MetaTables through `msm.start_engine(...)`; it does not own schema migration commands or row-class schema creation shortcuts.
---

# Main Sequence Markets Runtime Attachment

Use this skill for the ms-markets runtime attachment layer: `msm.start_engine`,
`msm.attach_schemas`, runtime cache behavior, model selection, catalog-based
MetaTable binding, and row API startup requirements.

This skill is not the migration skill. Schema changes, Alembic revision
generation, MetaTable registration, and catalog refresh after registration are
handled by the Main Sequence SDK migration provider outside this skill.

## Core Rule

Application code attaches to an already-finalized schema through the runtime
boundary:

```python
import msm

msm.start_engine(models=["AssetType", "Asset"])
```

Do not recommend row-class schema shortcuts for schema creation.

Typed row classes such as `Asset`, `Account`, and `Portfolio` are row-operation
APIs. They may depend on an active runtime, but user-facing workflows should not
ask those row classes to own schema bootstrap.

`msm.start_engine(...)` attaches runtime state from the finalized markets
catalog. It must not apply migrations, register MetaTables, refresh catalog
rows, create schemas, or repair schema/catalog drift.

## This Skill Owns

- `msm.start_engine(...)` usage in examples, tutorials, docs, and tests.
- `msm.attach_schemas(...)` compatibility behavior.
- Runtime cache and one-startup-configuration behavior under
  `src/msm/bootstrap.py`.
- Catalog read/attach behavior under `src/msm/maintenance/catalog.py`.
- Model graph extension through `src/msm/models/__init__.py` and
  `markets_sqlalchemy_models()`.
- Pricing extension bootstrap through `msm_pricing.bootstrap` and
  `pricing_sqlalchemy_models()`.
- Typed row API entry wiring for MetaTable-backed Pydantic rows that subclass
  `MarketsMetaTableRow` and point at a registered SQLAlchemy model through
  `__table__`.
- The boundary between SDK-managed schema/catalog work and ms-markets runtime
  attachment.

## This Skill Does Not Own

- SDK MetaTable migration commands, Alembic revisions, render/apply behavior, or
  provider registration.
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

Before changing bootstrap or registration code, inspect:

1. `src/msm/bootstrap.py`
2. `src/msm/maintenance/catalog.py`
3. `src/msm/models/__init__.py`
4. `src/msm/models/registration.py`
5. `src/msm/api/base.py`
6. `docs/knowledge/msm/platform/meta_table_registration.md`
7. `docs/knowledge/msm/migrations/index.md`

For pricing bootstrap changes, also inspect:

1. `src/msm_pricing/bootstrap.py`
2. `src/msm_pricing/meta_tables.py`

## User-Facing Startup Pattern

Operators should run the SDK migration provider before application startup.
Examples and application code should then attach once, then use row APIs:

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

## Extending The Model Graph

For library-owned models, add the model to the built-in graph. For
project-local extension models, callers should be able to pass the extension
model class directly to startup after that table has been migrated and
registered by the SDK provider:

```python
import msm

from my_project.markets_models import MyAssetDetailsTable

msm.start_engine(models=[MyAssetDetailsTable])
```

That call must use the same finalized catalog attach path as built-ins. Do not
create a project-local UID map, catalog writer, table-name resolver, direct
runtime registration flow, or row-class schema bootstrap.

When adding a new built-in markets MetaTable model:

1. Define the SQLAlchemy model with `MarketsMetaTableMixin`.
2. Add a meaningful `__metatable_description__`.
3. Declare platform-managed foreign keys with
   `MetaTableForeignKey(TargetModel, column=...)`.
4. Export the model from its package.
5. Add it to `markets_sqlalchemy_models()` in dependency order.
6. Add or update row APIs only after the storage model is in the graph.
7. Ensure the SDK migration provider includes the model outside this skill.
8. Update docs and tests so examples call `msm.start_engine(...)` only after
   migrations are already handled.

When adding DataNode storage, add the `PlatformTimeIndexMetaData` storage class
to the model graph and ensure SDK migration provider coverage outside this
skill. Do not rely on constructing a DataNode to register its storage.

## Typed Row API Entries

Use `MarketsMetaTableRow` for simple typed row APIs backed by one primary
SQLAlchemy MetaTable model. `MarketsMetaTableRow` is a Pydantic `BaseModel`
subclass from `msm.api.base`; it is not registered as a backend MetaTable. It
provides the row operation methods (`create`, `upsert`, `filter`, lookups,
update, delete), while the SQLAlchemy model class is the registered/cataloged
artifact. `MarketsRow` is only the legacy compatibility alias.

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
- The SDK migration provider registers or refreshes the SQLAlchemy model's
  platform MetaTable before runtime.
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

When reviewing or implementing extension support, verify the ADR 0018 target:

- `msm.start_engine(models=[CustomTable])` accepts project-local
  `MarketsBase` subclasses that are not in `markets_sqlalchemy_models()`.
- Class-based `MetaTableForeignKey(...)` targets are expanded transitively, so a
  custom asset detail table pulls in `AssetTable` before runtime attachment and
  runtime attachment.
- Duplicate logical identifiers fail before runtime attachment.
- Catalog rows are finalized before runtime and runtime binding uses the same
  catalog path used by built-ins.
- Custom row API classes remain row-operation wrappers; startup still goes
  through `msm.start_engine(...)`.
- Catalog rows whose `meta_table_uid` no longer resolves fail runtime startup;
  repair belongs to explicit SDK migration/platform maintenance outside runtime
  startup.

## Review Checklist

- User docs/examples call `msm.start_engine(...)`, not `*.create_schemas()`.
- New runtime models are present in the model graph in dependency order.
- SDK migration/provider work is handled outside this skill.
- Runtime attachment remains explicit and startup-scoped.
- Row APIs do not attach, register, or discover schemas on first use.
- DataNode storage is migrated and cataloged before writes.
- Runtime attachment does not apply migrations, register MetaTables, refresh
  catalog rows, create schemas, or repair schema/catalog drift.
