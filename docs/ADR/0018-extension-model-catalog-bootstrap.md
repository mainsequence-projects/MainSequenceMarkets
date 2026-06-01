# 0018. Extension Model Catalog Bootstrap

## Status

Completed

## Context

ADR 0015 moved markets MetaTable startup to a catalog-based bootstrap. ADR 0017
extended that bootstrap to DataNode storage MetaTables. That is the correct
registration boundary: application startup calls `msm.start_engine(...)`, the
maintenance catalog attaches or registers the selected MetaTables, and row
operations run only after the relevant model classes are bound to registered
platform `MetaTable.uid` values.

The current extension story is incomplete for users who create project-local
markets models. Built-in models are listed by `markets_sqlalchemy_models()` and
resolved in library dependency order. A caller can pass model classes to
`msm.start_engine(models=[...])`, but resolution is still anchored to the
built-in model list. That makes the intended external extension shape
awkward: users either have to modify the library's built-in registry or bypass
the catalog bootstrap with direct registration calls. Both outcomes are wrong.

The target user experience must be:

```python
import msm

from my_project.markets_models import MyAssetDetailsTable

msm.start_engine(models=[MyAssetDetailsTable])
```

`MyAssetDetailsTable` must be registered into the same markets maintenance
catalog as built-in models, use the same physical contract validation, and bind
back onto the authored SQLAlchemy model class. Users should not create a
parallel bootstrap, maintain MetaTable UID maps, or call row-level schema helpers
such as `Asset.create_schemas()`.

## Decision

`msm.start_engine(models=[...])` will become the public extension registration
boundary for both built-in and project-local markets MetaTable models.

The registration subject is always the SQLAlchemy MetaTable model class. In this
project that means a class such as `AssetTable`, `MyAssetDetailsTable`, or a
DataNode storage table class that subclasses the markets MetaTable base. That
SQLAlchemy model class is what is:

- attached to or registered as a backend Main Sequence `MetaTable`;
- written to the markets maintenance catalog;
- physically validated when an existing backend table is attached;
- bound back to the resolved backend `MetaTable.uid`;
- exposed through the markets runtime and repository context.

Typed row API classes such as `Asset`, `Bond`, or a project-local
`MyAssetDetails` row wrapper are not registered as MetaTables. If a row API
class is accepted by `models=[...]`, it is only a selector. Bootstrap normalizes
it to its backing SQLAlchemy model through `row_class.__table__`, and the
backing table model is the registered artifact.

The target base name for these Pydantic row API wrappers is
`MarketsMetaTableRow`. The existing `MarketsRow` name is too generic because it
does not say that the wrapper is Pydantic and MetaTable-backed.

String selectors such as `"Asset"` are also only selectors. They resolve to the
built-in SQLAlchemy model class, for example `"Asset"` resolves to `AssetTable`.
The string itself is not persisted or registered.

The `models` argument will accept these selectors:

- built-in model selectors such as `"Asset"` or `AssetTable`;
- project-local SQLAlchemy model classes that subclass `MarketsBase` through the
  appropriate markets mixin;
- row API classes whose `__table__` points at a markets SQLAlchemy model.

When a project-local model is supplied, bootstrap will include it in the same
catalog pipeline as built-ins. It will not require insertion into
`markets_sqlalchemy_models()`.

### Model Authoring Contract

Project-local extension models must follow the same authoring contract as
built-in models:

- subclass the appropriate markets SQLAlchemy base/mixin;
- declare a globally unique `__metatable_identifier__` or
  `__markets_base_identifier__`;
- declare a meaningful `__metatable_description__`;
- declare platform-managed foreign keys with
  `MetaTableForeignKey(TargetModel, column=...)`;
- avoid table-name strings, explicit FK names, manual MetaTable UID maps, and
  direct `MetaTable.register()` orchestration.

The stable logical identifier remains the catalog key. The backend
`MetaTable.uid` is resolved only by attach/register and is then bound to the
model class for compiled operation scope.

Example project-local asset detail model:

```python
import uuid

from mainsequence.meta_tables import MetaTableForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Numeric, String, Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin
from msm.models.assets import AssetTable


class MyAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "com.my_company.markets.MyAssetDetails"
    __metatable_extra_hash_components__ = {"storage_name": "my_asset_details"}
    __metatable_description__ = (
        "Project-local asset details keyed one-to-one by AssetTable.uid for "
        "custom analytics and internal asset classification."
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
    risk_weight: Mapped[float | None] = mapped_column(
        Numeric(18, 8),
        nullable=True,
        info={"description": "Optional project-defined risk weight for analytics."},
    )
```

Application startup registers the SQLAlchemy model through the shared catalog
bootstrap:

```python
import msm

from my_project.markets_models import MyAssetDetailsTable

msm.start_engine(models=[MyAssetDetailsTable])
```

That call registers or attaches `MyAssetDetailsTable` as a backend
`MetaTable`, adds or refreshes its markets catalog row, validates any existing
physical storage, and binds the resolved backend `MetaTable.uid` back to
`MyAssetDetailsTable`. The `MetaTableForeignKey(AssetTable, ...)` declaration
means bootstrap must include `AssetTable` first; the caller should not pass a
table name or UID for the target.

### Dependency Closure

Bootstrap will compute a complete dependency closure for selected models.

If a user supplies only:

```python
msm.start_engine(models=[MyAssetDetailsTable])
```

and `MyAssetDetailsTable` has a `MetaTableForeignKey(AssetTable, column="uid")`,
bootstrap will include `AssetTable` before `MyAssetDetailsTable`. The same rule
applies transitively for built-in and project-local targets.

The ordering rule is:

1. collect all requested models and row-class backing tables;
2. inspect class-based `MetaTableForeignKey(...)` targets;
3. add every transitive target model to the registration set;
4. topologically sort dependencies before dependents;
5. preserve the built-in library ordering as the tie-breaker for built-ins;
6. preserve caller order as the tie-breaker for unrelated extension models;
7. fail early on dependency cycles or duplicate logical identifiers.

This replaces any need for caller-maintained table-name maps. Dependency
expansion is model-class based, not SQLAlchemy physical-table-name based.

### Catalog And Runtime Behavior

The existing catalog behavior applies equally to extension models:

- attach the maintenance catalog first;
- attach selected rows already present in the catalog by `MetaTable.uid`;
- import pre-catalog platform registrations into the catalog when found;
- register models missing from both catalog and platform;
- validate physical storage before exposing already-registered MetaTables;
- write catalog rows keyed by logical identifier;
- bind the resolved platform `MetaTable` back onto each SQLAlchemy model class;
- expose the bound models through the active runtime and repository context.

`rotate_catalogue(ModelOrRow)` will also accept project-local models and row
classes. Rotation stays model-first: it resolves the backend MetaTable through
the model declaration and never accepts user-provided UIDs or identifier maps.

### Row API Extensions

If a project defines a typed row API around a project-local table, that row class
should remain a Pydantic row-operation wrapper. `MarketsMetaTableRow` is the
target project Pydantic base for single-table MetaTable row APIs; it is not the
registered MetaTable artifact.

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

Application startup still calls:

```python
msm.start_engine(models=[MyAssetDetailsTable])
```

or by passing the row wrapper as a selector:

```python
msm.start_engine(models=[MyAssetDetails])
```

The row class must not register, attach, or discover MetaTables on first use.

## Documentation And Skill Updates

Implementation of this ADR is not complete until the extension process is
documented in:

- `docs/knowledge/platform/meta_table_registration.md`, with a project-local
  `MyAssetDetailsTable` example that calls
  `msm.start_engine(models=[MyAssetDetailsTable])`;
- the ms-markets bootstrap/registration skill, so agents route extension work to
  `msm.start_engine(...)` and the catalog instead of direct registration;
- the asset model extension skill, so asset detail extensions show
  `MetaTableForeignKey(AssetTable, column="uid")` and startup through
  `msm.start_engine(models=[CustomAssetDetailsTable])`;
- any tutorial or example that demonstrates user-defined markets models.

The docs must explicitly say that users may write a project bootstrap wrapper,
but that wrapper delegates to `msm.start_engine(...)`. It must not implement a
separate registry, UID map, catalog writer, or table-name resolution layer.

## Implementation Tasks

- [x] 1. Introduce `MarketsMetaTableRow` in `src/msm/api/base.py` with the
  current single-table Pydantic row API behavior.
- [x] 2. Keep `MarketsRow` as a compatibility alias during migration, so
  existing row APIs and callers do not break immediately.
- [x] 3. Migrate built-in MetaTable-backed row APIs to import and subclass
  `MarketsMetaTableRow`.
- [x] 4. Split model resolution into two phases: built-in string selector
  resolution, and direct class normalization for supplied SQLAlchemy model
  classes or row API classes.
- [x] 5. Allow direct `MarketsBase` subclasses that are not in
  `markets_sqlalchemy_models()`.
- [x] 6. Add row-class normalization by reading a class `__table__` attribute
  when it points at a `MarketsBase` subclass. This must work for
  `MarketsMetaTableRow` subclasses and for the temporary `MarketsRow`
  compatibility alias.
- [x] 7. Build dependency closure from model-class
  `MetaTableForeignKey(...)` targets.
- [x] 8. Topologically sort the combined model set, with dependencies before
  dependents.
- [x] 9. Preserve built-in library ordering as the tie-breaker for built-ins and
  caller order as the tie-breaker for unrelated extension models.
- [x] 10. Detect duplicate logical identifiers before catalog bootstrap.
- [x] 11. Detect dependency cycles before registration and raise a clear error
  that names the cycle.
- [x] 12. Route the resulting ordered model list through
  `bootstrap_markets_meta_tables_from_catalog(...)` unchanged.
- [x] 13. Extend `rotate_catalogue(...)` so project-local SQLAlchemy models and
  row API wrappers resolve through the same model-normalization path.
- [x] 14. Add focused tests for extension model selection, dependency closure,
  catalog row creation/attachment, runtime UID binding, duplicate identifiers,
  dependency cycles, and catalog rotation.
- [x] 15. Update `docs/knowledge/platform/meta_table_registration.md` with the
  project-local `MyAssetDetailsTable` flow.
- [x] 16. Update the packaged and installed ms-markets bootstrap/registration
  skill so agents use `MarketsMetaTableRow` for row API wrappers and
  `msm.start_engine(models=[MyAssetDetailsTable])` for schema bootstrap.
- [x] 17. Update the asset model extension skill, tutorials, and examples so
  project-local extensions use the shared catalog bootstrap instead of direct
  registration or row-level schema helpers.

## Validation

The implementation must include focused tests proving:

- `msm.start_engine(models=[MyAssetDetailsTable])` accepts a project-local
  markets model that is not listed in `markets_sqlalchemy_models()`;
- dependency closure includes built-in FK targets such as `AssetTable`;
- catalog bootstrap creates or attaches a catalog row for the extension model;
- runtime row operations resolve the extension model's bound `MetaTable.uid`;
- duplicate logical identifiers fail before registration;
- dependency cycles fail with a clear error;
- `rotate_catalogue(MyAssetDetailsTable)` resolves the registered MetaTable
  through the model declaration;
- the packaged skill copy includes the updated bootstrap-registration guidance.

## Consequences

This makes extension bootstrap explicit, catalog-backed, and consistent with
built-in ms-markets models. Users get one registration path and one operational
mental model.

The cost is that model resolution becomes a real graph operation instead of a
filter over the built-in list. That is acceptable because foreign-key ordering
is already a bootstrap responsibility, and doing it once at process startup is
the correct place for this complexity.

This ADR does not remove the legacy row-level `create_schemas()` methods. It
does make them non-recommended for user workflows and prevents them from being
the extension mechanism.

This ADR does not introduce automatic row-operation registration. A missing
runtime remains an error, and startup remains the place where schema state is
verified.
