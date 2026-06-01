---
name: mainsequence-markets-metatable-migrations
description: Use this skill when adding, reviewing, documenting, or operating SDK-managed ms-markets MetaTable migrations. This skill owns the package migration registry, Python migration modules, SDK MigrationMetaTable sync/apply flow, catalog finalization, migration CLI commands, and the rule that runtime startup attaches only after migrations are current.
---

# Main Sequence Markets MetaTable Migrations

Use this skill for the `msm migrations ...` lifecycle and for any change that
creates or evolves library-owned MetaTables.

## Core Rule

Schema and catalog mutation belongs to admin commands:

```bash
msm migrations sync --data-source-uid <dynamic-table-data-source-uid>
msm migrations upgrade --data-source-uid <dynamic-table-data-source-uid>
msm migrations validate --data-source-uid <dynamic-table-data-source-uid>
```

Runtime code calls `msm.start_engine(...)` only after migration status and
catalog finalization are current. Runtime startup must not sync migration rows,
apply migrations, register application tables, or reconcile catalog rows.

## Read First

Before changing migration behavior, inspect:

1. `docs/ADR/0020-sdk-managed-metatable-migrations.md`
2. `docs/knowledge/msm/platform/metatable_migrations.md`
3. `src/msm/maintenance/migrations.py`
4. `src/msm/migrations/registry.py`
5. `src/msm/migrations/versions/`
6. `src/msm/maintenance/catalog.py`
7. `src/msm/bootstrap.py`

## Package Scope

`MIGRATION_MODEL_REGISTRY` defines the universe of `msm`-owned MetaTables that
migration commands consider. It is local source code, not migration history.

Python migration modules define revision metadata and affected models. The
runner materializes SDK manifest JSON from Python metadata at
`sync` or `upgrade` time; do not add hand-authored YAML/JSON manifest files as
the source of truth.

## Adding A Migration

When a library-owned model changes:

1. Update the SQLAlchemy model declaration.
2. Keep the model in `MIGRATION_MODEL_REGISTRY`.
3. Add a Python module under `src/msm/migrations/versions/`.
4. Define structured SDK migration operations in the Python module.
5. List affected models in the Python module.
6. Pin `OLD_CONTRACT_HASHES` when the previous declaration no longer exists in
   current code.
7. Add or update tests for manifest materialization, sync/apply routing, and
   catalog finalization.
8. Update docs, tutorial, example, changelog, and packaged skills.

Forward migrations are the only package workflow. Corrections are new forward
migrations, not downgrades.

## Review Checklist

- `msm migrations current` is read-only.
- `msm migrations sync` writes SDK registry rows but does not apply DDL.
- `msm migrations upgrade` applies through the SDK migration engine and then
  finalizes `MarketsMetaTableCatalogTable`.
- `msm migrations validate` fails unless SDK status and catalog rows match
  package code.
- `msm.start_engine(...)` verifies and attaches only.
- Catalog rows are not manually rotated to accept schema drift.
- Python migration modules are included in built wheels.
