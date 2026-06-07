# Refactor ms-markets To SDK-Owned MetaTable Migration Helpers

## Status

Implemented locally.

## Goal

Replace the ms-markets local MetaTable migration boilerplate with the
SDK-owned helpers introduced in `mainsequence.meta_tables.migrations`.

The final project state should keep the same provider behavior, but stop
hand-rolling SDK conventions:

```text
ms-markets SQLAlchemy models
  -> SDK provider helper
  -> SDK Alembic env helper
  -> SDK registry/model-scope helper
  -> generated Alembic revisions when authored
  -> backend MetaTable reservation/finalization
```

This is a refactor, not a schema migration. It must not create, rename, move,
or edit generated Alembic revision files. Documentation and tests must not
assume that revision files have already been generated or that migrations have
already been applied.

## Scope

This task targets migration scaffolding and provider wiring in ms-markets:

- `src/migrations/__init__.py`
- `src/migrations/registry.py`
- `src/migrations/env.py`
- `src/migrations/script.py.mako`
- dynamic migration providers, especially portfolio/example providers that
  build one-model or configured providers
- docs, tutorials, and packaged skills that still describe local migration
  boilerplate as the standard path

The task should use the SDK helpers:

- `build_alembic_version_metatable(...)`
- `build_metatable_migration_provider(...)`
- `build_metatable_model_registry(...)`
- `metadata_for_models(...)`
- `namespace_version_slug(...)`
- `namespace_version_location(...)`
- `run_mainsequence_alembic_env(...)`
- SDK-owned `script.py.mako`

## Non-Goals

- Do not change physical table names.
- Do not rename the Alembic version table.
- Do not change `package`, `migration_namespace`, or migration provider key.
- Do not move, rename, or edit generated revision files under
  `src/migrations/versions/`.
- Do not edit already-applied Alembic revisions.
- Do not add a catalog table or catalog refresh hook back into the provider.
- Do not add direct `MetaTable.register()` or model `.register()` calls outside
  the migration workflow.
- Do not add SDK reset/reconcile commands for stale reserved rows.

## Current Usage Inventory

The pre-refactor ms-markets migration package owned boilerplate that should now be
SDK-owned:

- `src/migrations/__init__.py` defines local namespace slugging,
  `active_namespace_version_location()`, `MarketsAlembicVersion`, and a manual
  `AlembicMetaTableMigration(...)`.
- `src/migrations/registry.py` filters, validates, and deduplicates provider
  models manually.
- `src/migrations/env.py` wires Alembic context configuration, provider lookup,
  schema filtering, include hooks, online/offline execution, and migration role
  application manually.
- `src/migrations/script.py.mako` repeats the standard revision template.
- Dynamic providers repeat parts of the same provider construction logic.

Keep direct runtime binding from the backend lookup path. This task must not
reintroduce `MarketsMetaTableCatalogTable` or any catalog refresh hook removed
by the platform catalog cleanup.

## Critical Invariants

Before changing code, record the current resolved values from the existing
provider:

- `migration.package`
- `migration.migration_namespace`
- `migration.migration_provider_key`
- `migration.script_location`
- `migration.resolved_version_locations()`
- `migration.resolved_version_path()`
- `migration.version_table`
- `migration.version_table_schema`
- `migration.alembic_registry.__metatable_identifier__`
- `migration.alembic_registry.__alembic_version_table_name__`
- ordered `[model.__table__.name for model in migration.metatable_models]`
- ordered `[model.__metatable_identifier__ for model in migration.metatable_models]`

After the refactor, provider identity values must remain the same unless the
project owner explicitly approves a separate provider contract change.

Pay special attention to version locations. The SDK provider factory derives
`version_locations` and `version_path` from `migration_namespace`. Because this
checkout has no generated revision history to preserve, ms-markets should use
that SDK-derived provider path directly and should not keep a project-local
`markets_auto_register_namespace()` version-location policy.

## Implementation Tasks

### Stage 1: SDK Baseline And Provider Snapshot

- [ ] Ensure the project uses an SDK version or editable SDK checkout that
      exposes `mainsequence.meta_tables.migrations` as a package.
- [ ] Verify these imports work in the ms-markets virtual environment:
      `build_alembic_version_metatable`,
      `build_metatable_migration_provider`,
      `build_metatable_model_registry`,
      `metadata_for_models`,
      `namespace_version_location`, and
      `run_mainsequence_alembic_env`.
- [ ] Add a small temporary inspection command or focused test that prints the
      current provider invariants listed above.
- [ ] Save the provider invariant output in the task notes or test fixture
      comments so reviewers can see that the refactor preserves history.

### Stage 2: Refactor Provider Model Registry

- [ ] Replace local `_is_metatable_provider_model(...)` and
      `_dedupe_metatable_provider_models(...)` logic in
      `src/migrations/registry.py` with
      `build_metatable_model_registry(...)`.
- [ ] Keep the current model source functions and provider model order.
- [ ] Keep the `MarketsBase` scope check by passing `base=MarketsBase`.
- [ ] Keep returning a fresh list from `metatable_provider_models()`.
- [ ] Add or update tests for duplicate identifiers, missing identifiers, and
      order preservation through the SDK helper.

Expected shape:

```python
from mainsequence.meta_tables.migrations import build_metatable_model_registry

from msm.base import MarketsBase


def _metatable_provider_model_sources() -> list[type[MarketsBase]]:
    ...


METATABLE_PROVIDER_MODELS: tuple[type[MarketsBase], ...] = tuple(
    build_metatable_model_registry(
        _metatable_provider_model_sources(),
        base=MarketsBase,
    )
)


def metatable_provider_models() -> list[type[MarketsBase]]:
    return list(METATABLE_PROVIDER_MODELS)
```

### Stage 3: Refactor Main Migration Provider

- [ ] Remove local `hashlib` / `re` namespace slugging helpers from
      `src/migrations/__init__.py`.
- [ ] Replace the hand-written `MarketsAlembicVersion` subclass with
      `build_alembic_version_metatable(...)`.
- [ ] Replace local version-path calculation with SDK
      `namespace_version_location(...)`, or with
      `build_metatable_migration_provider(...)` if it preserves the exact
      existing path.
- [ ] Keep the same Alembic version MetaTable namespace, identifier, schema,
      table name, and column name.
- [ ] Keep the same provider package, migration namespace, script location,
      version locations, version path, metadata, registry class, and
      metatable model list.

Preferred shape when SDK provider factory preserves the existing version path:

```python
from mainsequence.meta_tables.migrations import (
    build_alembic_version_metatable,
    build_metatable_migration_provider,
)

from msm.base import MARKETS_SCHEMA, MARKETS_TABLE_APP, MarketsBase, markets_table_name
from msm.settings import (
    markets_auto_register_namespace,
    markets_identifier,
    markets_namespace,
)
from migrations.registry import metatable_provider_models


MarketsAlembicVersion = build_alembic_version_metatable(
    class_name="MarketsAlembicVersion",
    namespace=markets_namespace(),
    identifier=markets_identifier("msm.alembic_version"),
    schema=MARKETS_SCHEMA,
    table_name=markets_table_name(
        MARKETS_TABLE_APP,
        "alembic_version",
        suffix=markets_auto_register_namespace(),
    ),
)

migration = build_metatable_migration_provider(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="migrations:",
    version_location_prefix="migrations:versions",
    target_metadata=MarketsBase.metadata,
    alembic_registry=MarketsAlembicVersion,
    metatable_models=metatable_provider_models(),
)
```

Fallback shape when the existing version directory is based on a different
namespace value:

```python
from mainsequence.meta_tables.migrations import (
    AlembicMetaTableMigration,
    build_alembic_version_metatable,
    namespace_version_location,
)

version_location = namespace_version_location(
    markets_auto_register_namespace(),
    prefix="migrations:versions",
)

migration = AlembicMetaTableMigration(
    package="msm",
    migration_namespace=markets_namespace(),
    script_location="migrations:",
    version_locations=[version_location],
    version_path=version_location,
    target_metadata=MarketsBase.metadata,
    alembic_registry=MarketsAlembicVersion,
    metatable_models=metatable_provider_models(),
)
```

### Stage 4: Refactor Alembic env.py

- [ ] Replace custom Alembic online/offline boilerplate in
      `src/migrations/env.py` with `run_mainsequence_alembic_env(...)`.
- [ ] Preserve ms-markets schema filtering through the helper's
      `included_schema` callback.
- [ ] Keep fallback provider import only in the local scaffolded file.
- [ ] Remove local `engine_from_config`, `pool`, explicit `context.configure`,
      explicit `apply_mainsequence_migration_role`, and local include hook
      wrappers when the SDK helper covers them.

Expected shape:

```python
from __future__ import annotations

from mainsequence.meta_tables.migrations.env import run_mainsequence_alembic_env

from msm.base import MARKETS_DEFAULT_SCHEMA, MARKETS_SCHEMA
from migrations import migration as default_migration


def _included_schema(name: str | None) -> bool:
    if MARKETS_SCHEMA is None:
        return name in (None, MARKETS_DEFAULT_SCHEMA)
    return name == MARKETS_SCHEMA


run_mainsequence_alembic_env(
    default_provider=default_migration,
    included_schema=_included_schema,
)
```

### Stage 5: Replace Revision Template With SDK Template

- [ ] Replace `src/migrations/script.py.mako` with the SDK-owned template from
      `mainsequence.meta_tables.migrations.templates`.
- [ ] Confirm the generated revision format is equivalent to the existing
      template for `revision`, `down_revision`, `branch_labels`, and
      `depends_on`.
- [ ] Do not rewrite historical revision files.

### Stage 6: Refactor Dynamic And Example Providers

- [ ] Find dynamic providers with:
      `rg "AlembicMetaTableMigration|metadata_for_models|script_location|version_locations" examples src`.
- [ ] Replace repeated version table construction with
      `build_alembic_version_metatable(...)`.
- [ ] Replace repeated one-model metadata construction with
      `metadata_for_models([Model])`.
- [ ] Use `build_metatable_migration_provider(...)` when it preserves the
      intended version location.
- [ ] Ensure dynamic provider hooks, if any, use provider-scoped
      `context.metatable_models` and `context.registered_metatables`; they must
      not import the full package registry.
- [ ] Keep each dynamic provider's `metatable_models` list scoped to only the
      table or tables that provider owns.

### Stage 7: Documentation And Skills

- [ ] Update ms-markets migration docs to show SDK helper-based providers.
- [ ] Update ms-markets tutorials to use `mainsequence migrations scaffold` for
      new migration packages.
- [ ] Update packaged skills to route MetaTable migration lifecycle work to the
      migration workflow and not to direct model `.register()` calls.
- [ ] Remove mentions of project-local namespace slugging, project-local
      registry dedupe, hand-written Alembic env internals, and hand-written
      revision templates as the recommended path.
- [ ] Keep any historical ADR text intact unless it is explicitly superseded.

### Stage 8: Search Cleanup

- [ ] Remove or justify remaining local helper references:
      `namespace_version_slug`, `active_namespace_version_slug`,
      `active_namespace_version_location`,
      `_dedupe_metatable_provider_models`,
      `_is_metatable_provider_model`,
      `run_migrations_online`, `run_migrations_offline`,
      `engine_from_config`, and `script.py.mako`.
- [ ] Verify remaining `AlembicMetaTableMigration(...)` constructors are only
      retained where the SDK provider factory cannot preserve the existing
      version-location policy.
- [ ] Verify no platform-managed application path calls `.register()` directly
      outside migration commands.

## Validation

- [ ] Run `git diff --check`.
- [ ] Run focused import checks:
      `python -c "import migrations; print(migrations.migration.resolved_version_locations())"`.
- [ ] Run provider invariant checks before and after the refactor and verify no
      unintended value changed.
- [ ] Run focused migration provider tests.
- [ ] Run focused startup/bootstrap tests that bind normal `MetaTable` and
      `TimeIndexMetaTable` models by backend lookup.
- [ ] Run dynamic portfolio/example migration provider tests.
- [ ] Run `mainsequence migrations current --provider migrations:migration` in
      a configured local project.
- [ ] Run a no-op or controlled test `mainsequence migrations upgrade --provider
      migrations:migration head` against a disposable/local backend.
- [ ] Run `mkdocs build --strict` if documentation changed.

## Done Criteria

- `src/migrations/__init__.py` no longer owns local namespace slugging or a
  hand-written Alembic version-table subclass unless a direct constructor is
  required to preserve existing version locations.
- `src/migrations/registry.py` uses `build_metatable_model_registry(...)`.
- `src/migrations/env.py` delegates to `run_mainsequence_alembic_env(...)`.
- `src/migrations/script.py.mako` matches the SDK template.
- Dynamic providers use SDK helper functions and remain provider scoped.
- Existing Alembic revision directories, revision IDs, and version-table
  identity are unchanged.
- Main provider `metatable_models` order and contents are unchanged except for
  already-approved catalog removal.
- Docs and skills describe the SDK helper/scaffold path as the standard
  migration workflow.
