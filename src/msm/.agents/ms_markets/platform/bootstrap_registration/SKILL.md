---
name: mainsequence-markets-bootstrap-registration
description: Use this skill when changing, documenting, or reviewing ms-markets runtime attachment, SDK-managed MetaTable migrations, package migration registry, catalog finalization, registration order, or extension wiring. Use it whenever examples or user workflows need schema migration or runtime attachment before row APIs or DataNode writes. This skill owns the rule that schema/catalog mutation happens through `msm migrations ...`, while library users attach runtime through `msm.start_engine(...)`, not row-class create_schemas() shortcuts.
---

# Main Sequence Markets Migrations And Runtime Attachment

Use this skill for the ms-markets schema lifecycle: admin migrations,
application runtime attachment, catalog finalization, extending the model graph,
and documenting how users should prepare schemas before row operations or
DataNode writes.

## Core Rule

Schema and catalog mutation is admin-owned:

```bash
msm migrations upgrade --data-source-uid <dynamic-table-data-source-uid>
```

Application code attaches to the finalized schema through the runtime boundary:

```python
import msm

msm.start_engine(models=["AssetType", "Asset"])
```

Do not recommend row-class schema shortcuts such as:

```python
Asset.create_schemas()
```

Typed row classes such as `Asset`, `Account`, and `Portfolio` are row-operation
APIs. They may depend on an active runtime, but user-facing workflows should not
ask those row classes to own schema bootstrap.

`msm.start_engine(...)` must verify migration status and catalog finalization,
then attach from `MarketsMetaTableCatalogTable`. It must not sync SDK migration
rows, apply migrations, register application tables, or reconcile catalog rows.

## This Skill Owns

- `msm.start_engine(...)` usage in examples, tutorials, docs, and tests.
- Admin migration behavior under `src/msm/maintenance/migrations.py`.
- Package migration registry and revisions under `src/msm/migrations/`.
- Runtime catalog attachment behavior under `src/msm/bootstrap.py` and
  `src/msm/maintenance/catalog.py`.
- Model graph extension through `src/msm/models/__init__.py` and
  `markets_sqlalchemy_models()`.
- Pricing extension bootstrap through `msm_pricing.bootstrap` and
  `pricing_sqlalchemy_models()`.
- Typed row API entry wiring for MetaTable-backed Pydantic rows that subclass
  `MarketsMetaTableRow` and point at a registered SQLAlchemy model through
  `__table__`.
- The boundary between admin schema migration, catalog finalization, runtime
  attachment, and typed row operations.

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

Before changing bootstrap or registration code, inspect:

1. `src/msm/bootstrap.py`
2. `src/msm/maintenance/catalog.py`
3. `src/msm/maintenance/migrations.py`
4. `src/msm/migrations/registry.py`
5. `src/msm/migrations/versions/`
6. `src/msm/models/__init__.py`
7. `src/msm/models/registration.py`
8. `src/msm/api/base.py`
9. `docs/knowledge/msm/platform/meta_table_registration.md`
10. `docs/knowledge/msm/platform/metatable_migrations.md`

For pricing bootstrap changes, also inspect:

1. `src/msm_pricing/bootstrap.py`
2. `src/msm_pricing/meta_tables.py`

## User-Facing Startup Pattern

Admin workflows should run migrations before application startup. Examples and
application code should then attach once, then use row APIs:

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
project-local extension models, target ADR 0018: callers should be able to pass
the extension model class directly to startup:

```python
import msm

from my_project.markets_models import MyAssetDetailsTable

msm.start_engine(models=[MyAssetDetailsTable])
```

That call must use the same finalized maintenance catalog path as built-ins. Do
not create a project-local UID map, catalog writer, table-name resolver, or
direct runtime registration flow.

When adding a new built-in markets MetaTable model:

1. Define the SQLAlchemy model with `MarketsMetaTableMixin`.
2. Add a meaningful `__metatable_description__`.
3. Declare platform-managed foreign keys with
   `MetaTableForeignKey(TargetModel, column=...)`.
4. Export the model from its package.
5. Add it to `markets_sqlalchemy_models()` in dependency order.
6. Add or update row APIs only after the storage model is in the graph.
7. Add or update a packaged Python migration module and SQL resource.
8. Update docs and tests so examples run admin migrations before
   `msm.start_engine(...)`.

When adding DataNode storage, add the `PlatformTimeIndexMetaData` storage class
to the migration/model graph. Do not rely on constructing a DataNode to register
its storage.

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
- Admin migrations register or refresh the SQLAlchemy model's platform
  MetaTable. `msm.start_engine(...)` only attaches it; the row class does not
  register, attach, or discover schemas.

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
  migration planning.
- Duplicate logical identifiers fail before migration planning or runtime
  attachment.
- Catalog rows are finalized by admin migrations and runtime binding uses the
  same catalog path used by built-ins.
- Custom row API classes remain row-operation wrappers; startup still goes
  through `msm.start_engine(...)`.
- Catalog rows whose `meta_table_uid` no longer resolves fail runtime startup;
  repair belongs to `msm migrations upgrade` or explicit admin/platform repair.

## Review Checklist

- User docs/examples call `msm.start_engine(...)`, not `*.create_schemas()`.
- New models are present in the migration/model graph in dependency order.
- New model changes include packaged Python migration modules and SQL resources.
- Runtime attachment remains explicit and startup-scoped.
- Row APIs do not attach, register, or discover schemas on first use.
- DataNode storage is migrated/finalized through the model/catalog graph before
  writes.
- Runtime attachment does not sync migrations, apply migrations, register
  application tables, or reconcile catalog rows.
