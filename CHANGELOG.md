# Changelog

All notable changes to this project should be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows versioned releases.

## [Unreleased]

### Added

- Added a GitHub Actions workflow to build and publish `ms-markets` to PyPI
  when a `v*` tag is pushed, using GitHub OIDC trusted publishing.
- Added an asset CRUD example covering creation, lookup by identifier and UID,
  search, and deletion of temporary custom assets.
- Added an offline platform example for inspecting SDK-derived markets
  MetaTable model names.
- Added `msm.create_schemas(...)` to bootstrap markets MetaTables and return a
  repository runtime context for examples and applications.
- Added process-idempotent `msm.create_schemas(...)` behavior: repeated calls with the
  same startup configuration reuse the runtime, while different second calls
  fail before changing table namespace or execution context.
- Added structured Main Sequence `info` logs to `msm.create_schemas(...)` so
  initialization reports namespace configuration, one line per MetaTable
  registration, context creation, runtime creation, and cached-runtime reuse.
- Exposed registered MetaTable handles and DataNode class handles on the
  `msm.create_schemas(...)` runtime instead of accepting broad labels on startup.
- Added AssetSnapshot service entrypoints for validated DataNode frame/node
  updates.
- Added an AssetSnapshot example using an example-scoped DataNode identifier.
- Added `examples/platform/bootstrap.py` as the home for the example MetaTable
  namespace constant used before direct `msm.create_schemas(...)` bootstrap calls.
- Documented the direct example bootstrap pattern so calls like
  `upsert_asset(context, ...)` route to example-scoped MetaTables through the
  returned context while production startup remains namespace-free.
- Documented the asset CRUD workflow in the asset knowledge docs and market
  workflow tutorial.
- Corrected the examples directory name to `examples/`.
- Added the `mainsequence.examples` MetaTable namespace bootstrap for examples
  that create platform resources.

### Changed

- Updated markets MetaTable models to inherit SDK `PlatformManagedMetaTable`
  naming through `MarketsMetaTableMixin` instead of hand-writing
  `__tablename__`.
- Removed the arbitrary `metadata_json` column and create/update/upsert payload
  from the core `Asset` MetaTable model.

## [0.0.1] - 2026-05-25

### Added

- Scaffolded the `ms-markets` Python project with the import package `msm`.
- Added MkDocs documentation, ADRs, tutorial scaffold, and GitHub Pages
  deployment workflow.
- Migrated market-domain code from the SDK into `src/msm`.
- Migrated market-domain examples into `examples/`.
- Migrated market-domain agent skills into `.agents/skills/`.
- Added a future CLI package scaffold under `src/cli`.
- Added the initial `docs/knowledge` concept documentation area for `msm`
  package concepts.
- Added Apache-2.0 licensing metadata and the full project license.
- Added the `.agents/skills/library_maintenance` Open Agent skill to enforce
  library maintenance workflows across implementation, documentation, examples,
  tutorials, changelog, and validation.

### Changed

- Moved asset DataNode schemas from the obsolete `msm.assets` package boundary
  into `msm.data_nodes.assets`.
- Moved OpenFIGI provider helpers into `msm.services.assets.openfigi` and kept
  asset identity on the `msm.models.assets.Asset` MetaTable model.
- Made `msm.services` and `msm.data_nodes` package exports lazy so provider
  helpers and lightweight package imports do not initialize unrelated platform
  dependencies.
- Reworked the README into the public project overview, including logo, badges,
  documentation map, quick start, development commands, metadata, and license
  information.
- Made README links PyPI-safe by pointing package-page readers to the public
  documentation site and GitHub project files.
- Added explicit source distribution include rules so PyPI source artifacts do
  not ship local IDE, workflow, or agent-maintenance files.
- Declared the first release version directly in `pyproject.toml` as `0.0.1`.
- Refactored instrument valuation code into `msm.pricing`.
- Renamed pricing model helpers from the old `pricing_models` package to
  `msm.pricing.models`.

### Removed

- Removed migrated market-domain code, examples, and skills from the SDK tree.
