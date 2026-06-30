# Remove Markets MetaTable Catalog

## Status

Complete.

## Goal

Remove the internal `MarketsMetaTableCatalog` maintenance table and every code
path that treats it as a runtime, API, migration, or documentation dependency.

The final project state should use one source of truth for registered markets
tables:

```text
SQLAlchemy model graph
  -> model.__table__.name
  -> backend MetaTable / TimeIndexMetaTable lookup
  -> model._bind_meta_table(...)
```

No secondary catalog table should be required to attach runtime models, inspect
registered tables, or run examples.

## Scope

This task targets the internal maintenance catalog only:

- `MarketsMetaTableCatalogTable`
- `MarketsMetaTableCatalogRow`
- `src/msm/maintenance/catalog.py`
- catalog refresh hooks wired through Alembic migration providers
- generic `/api/v1/catalog/` FastAPI catalogue routes
- tests, docs, ADRs, skills, and examples that mention the internal catalog as
  a runtime or inventory dependency

This task does not remove domain language such as asset catalog, index catalog,
or category catalog when it means a business list of assets or indices.

## Current Usage Inventory

Runtime startup already bypasses the catalog:

- `msm.start_engine(...)` calls `resolve_registered_markets_meta_tables(...)`.
- `resolve_registered_markets_meta_tables(...)` bulk-resolves normal
  `MetaTable` rows and `TimeIndexMetaTable` rows by
  `physical_table_name__in=[model.__table__.name, ...]`.
- ADR 0025 documents the intended direct binding model.

The remaining internal catalog dependencies are:

- migration provider includes `MarketsMetaTableCatalogTable` in
  `metatable_provider_models()`;
- migration provider calls
  `after_register_metatables=refresh_markets_catalog_from_registered_metatables`;
- dynamic portfolio migration provider also refreshes the catalog;
- `apps/v1` exposes generic catalog list, row list, and delete endpoints;
- `src/msm/services/catalog.py` implements those generic endpoints;
- stale documentation and skills still describe catalog-driven attachment or
  catalog inventory as useful.

## Implementation Tasks

### Stage 1: Remove Runtime And Maintenance Code

- [x] Delete `MarketsMetaTableCatalogTable` and `MarketsMetaTableCatalogRow`
      from `src/msm/maintenance/models.py`, or remove the module if it becomes
      empty.
- [x] Remove catalog exports from `src/msm/maintenance/__init__.py`.
- [x] Delete `src/msm/maintenance/catalog.py`.
- [x] Remove catalog service exports from `src/msm/services/__init__.py`.
- [x] Delete `src/msm/services/catalog.py`.
- [x] Remove any remaining imports of `msm.maintenance.catalog` and
      `msm.maintenance.models`.
- [x] Keep `msm.start_engine(...)`, `msm.attach_schemas(...)`, pricing startup,
      and portfolio startup on the direct backend lookup path only.

### Stage 2: Remove Migration Provider Catalog Wiring

- [x] Remove `MarketsMetaTableCatalogTable` from
      `src/migrations/registry.py`.
- [x] Remove `refresh_markets_catalog_from_registered_metatables` from
      `src/migrations/__init__.py`.
- [x] Remove `after_register_metatables=...` from the main migration provider.
- [x] Remove the same catalog refresh hook from
      `examples/msm_portfolios/portfolio_equal_weights_dynamic_migration.py`.
- [x] Leave historical migration revisions untouched. Any physical-table drop
      revision is intentionally outside this implementation and will be handled
      separately by the project owner.

### Stage 3: Remove FastAPI Catalogue Surface

- [x] Delete `apps/v1/routers/catalog.py`.
- [x] Delete `apps/v1/services/catalog.py`.
- [x] Delete `apps/v1/schemas/catalog.py`.
- [x] Remove the catalog router import and `include_router(...)` call from
      `apps/v1/main.py`.
- [x] Remove the `catalog` OpenAPI tag from `apps/v1/main.py`.
- [x] Remove catalog endpoint documentation from `docs/fast_api/v1/index.md`.
- [x] Remove or replace FastAPI tests that assert `/api/v1/catalog/` routes
      exist.

### Stage 4: Remove Tests And Test Fixtures

- [x] Delete catalog-specific maintenance tests such as
      `tests/msm/maintenance/test_catalog_bootstrap.py`.
- [x] Remove catalog refresh assertions from
      `tests/msm/maintenance/test_migrations.py`.
- [x] Remove repository tests that construct `MarketsMetaTableCatalogRow` or
      include `MarketsMetaTableCatalogTable`.
- [x] Remove service tests for `msm.services.catalog`.
- [x] Remove FastAPI catalog route and OpenAPI tests.
- [x] Add or keep direct-runtime tests proving startup still resolves normal
      `MetaTable` and `TimeIndexMetaTable` resources by physical table name
      without catalog rows.

### Stage 5: Clean Documentation, ADRs, And Skills

- [x] Update ADR 0025 to say the catalog was fully removed, not merely demoted.
- [x] Review ADR 0019, ADR 0022, ADR 0024, and any other ADR mentioning
      `MarketsMetaTableCatalog`, catalog refresh, catalog inventory, or catalog
      attachment. Either remove the obsolete catalog design text or add a clear
      supersession note that the table no longer exists.
- [x] Update `docs/index.md`, `docs/getting-started.md`, tutorial pages, and
      platform knowledge docs so startup is described only as direct runtime
      lookup by `model.__table__.name`.
- [x] Remove generic catalogue endpoint documentation from the FastAPI docs.
- [x] Update `.agents/skills/ms_markets/platform/bootstrap_registration/SKILL.md`
      so it no longer says runtime attaches from the finalized catalog or owns
      catalog-based binding.
- [x] Update any other packaged skill that mentions the removed internal
      catalog.
- [x] Update `CHANGELOG.md`.

### Stage 6: Search And Cleanup

- [x] Run targeted searches and remove remaining internal catalog references:
      `MarketsMetaTableCatalog`, `MarketsMetaTableCatalogRow`,
      `MarketsMetaTableCatalogTable`, `refresh_markets_catalog`,
      `attach_markets_meta_tables_from_catalog`, `catalog_repository_context`,
      `/api/v1/catalog`, and `catalogue row`.
- [x] Review remaining `catalog` / `catalogue` hits manually and keep only
      domain uses such as asset catalog or index catalog.
- [x] Verify no import path under `src/`, `apps/`, or `examples/` depends on
      `msm.maintenance.catalog`.

## Validation

- [x] Run `git diff --check`.
- [x] Run focused import checks for `msm`, `msm_portfolios`, `msm_pricing`, and
      `apps/v1`.
- [x] Run focused runtime registration tests for direct `MetaTable` and
      `TimeIndexMetaTable` attachment.
- [x] Run focused migration provider tests.
- [x] Run FastAPI OpenAPI tests after removing catalog endpoints.
- [x] Run `mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site`.
- [x] Cover `msm.start_engine(...)` startup through focused bootstrap tests; a
      live platform example was not run because the local session has no
      Main Sequence auth token configured.

## Done Criteria

- The internal catalog table is not part of the provider model graph.
- Migration provider execution does not refresh catalog rows.
- No application route exposes generic catalog table browsing.
- Runtime startup, pricing startup, portfolio startup, examples, and row APIs
  work without `MarketsMetaTableCatalogTable`.
- Documentation and ADRs describe direct backend table lookup as the only
  runtime binding mechanism.
- Targeted search finds no internal catalog references outside intentionally
  retained historical release notes, if any are explicitly accepted.
