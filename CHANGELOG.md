# Changelog

All notable changes to this project should be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows versioned releases.

## [Unreleased]

### Changed

- Refactored the `migrations:migration` provider, Alembic environment, model
  registry, and dynamic portfolio example provider onto the SDK-owned
  MetaTable migration helpers, with revision directories treated as generated
  Alembic output rather than pre-existing documentation state.
- Renamed account allocation APIs and schemas around their actual domain:
  `AccountModelPortfolio` became `AccountAllocationModel`,
  `AccountTargetPortfolio` became `AccountTargetAllocation`, and the related
  fields now use `account_allocation_model_uid` and
  `account_target_allocation_uid`.
- Moved `PortfolioTable` identity and account target-position storage into core
  `msm`; `msm_portfolios` now owns portfolio calculation workflows, while core
  `msm` owns virtual-fund identity, virtual-fund holdings storage, and account
  allocation planning.
- Added the account holdings to virtual-fund allocation planner with
  `proportional_attribution` and `strict_feasible` policies, plus an apply step
  that converts feasible plans into `VirtualFundHoldingsStorage` frames.
- Extended the account virtual-fund planner with deterministic
  `position_set_uid` input resolution, notional target conversion through the
  valuation resolver, deterministic virtual-fund identity helpers, and
  resolver-level tests plus a dry-run-first account virtual-fund allocation
  example.
- Moved virtual-fund knowledge documentation under the Accounts section as a
  standalone account allocation document.
- Reorganized DataNode storage contracts by concept: account storage now lives
  under `msm.data_nodes.accounts`, asset storage under
  `msm.data_nodes.assets`, execution storage under `msm.data_nodes.execution`,
  and portfolio/pricing storage under their matching concept packages.
- Renamed the one-pass account and portfolio example to
  `examples/msm/accounts/account_portfolio_full_workflow.py` and moved the
  PyCharm run configuration under Accounts because the workflow prepares the
  reusable portfolio sleeve and then publishes account target positions and
  holdings. The same full workflow now exposes the virtual-fund allocation
  extension through dry-run and apply flags.

### Fixed

- Normalized `InterpolatedPrices.update()` output time indexes and timestamp
  columns back to `datetime64[ns, UTC]` so backend-read microsecond timestamps
  do not fail SDK DataNode update validation.
- Fixed the equal-weight portfolio schema-preparation workflow so it derives the
  dynamic revision from the active migration namespace and runs the dynamic
  provider upgrade before `--run-after`, even when a stale metadata row already
  exists for the configured interpolation table.

### Removed

- Removed the internal markets MetaTable catalog table, generic `/api/v1/catalog`
  routes, catalog service layer, and migration catalog refresh hooks. Runtime
  attachment now stays on direct backend `MetaTable`/`TimeIndexMetaTable`
  lookup by SQLAlchemy table name.

## [0.0.39] - 2026-06-06

### Highlights

- Split the library into clear package boundaries: `msm` for core market data,
  `msm_portfolios` for portfolio and virtual-fund workflows, and
  `msm_pricing` for pricing instruments, pricing market data, curves, fixings,
  and QuantLib-backed engines.
- Completed the storage-first DataNode architecture: DataNode outputs are now
  backed by `PlatformTimeIndexMetaTable` storage classes, with schema, dtypes,
  index grain, metadata, and foreign keys owned by SQLAlchemy/SDK table
  contracts instead of DataNode-side mirrors.
- Moved MetaTable schema lifecycle to the SDK-managed Alembic provider flow and
  made runtime startup attach to already-registered tables by physical table
  name rather than using the maintenance catalog as runtime control.
- Reworked portfolio examples into explicit schema-preparation and runtime
  stages so configured interpolation storage is registered before normal
  portfolio execution.
- Added cohesive account, asset, portfolio, and pricing documentation, examples,
  and packaged agent skills that reflect the current package boundaries.

### Changed

- Reorganized examples under `examples/msm/`, `examples/msm_portfolios/`, and
  `examples/msm_pricing/`; reorganized knowledge docs under the same package
  boundaries.
- Standardized asset extension naming: public API rows use domain names such as
  `Bond`, `Future`, and `CurrencySpot`, while one-to-one MetaTables use
  `<Domain>AssetDetailsTable` with `asset_uid` as the primary key and FK to
  `AssetTable.uid`.
- Normalized asset-indexed storage identity columns to explicit names such as
  `asset_identifier`, `index_identifier`, `curve_identifier`, and
  `portfolio_identifier`, while preserving unique MetaTable business keys such
  as `AssetTable.unique_identifier`.
- Updated markets, portfolio, and pricing bootstraps to use `start_engine(...)`
  as the public runtime attachment surface.
- Replaced deprecated SDK foreign-key helper declarations with normal
  SQLAlchemy `ForeignKey(...)` declarations.
- Added inline SQLAlchemy column labels and descriptions across built-in
  MetaTables and storage tables.
- Reworked accounts around `Account`, `AccountGroup`, `AccountAllocationModel`,
  `AccountTargetAllocation`, `PositionSet`, and storage-backed holdings and
  target positions.
- Reworked virtual funds as account-owned allocation views instead of synthetic
  asset rows.
- Reworked pricing market-data configuration around UID-backed market-data sets
  and bindings, plus index convention details, index fixings, and curve rows.
- Moved QuantLib pricing engine code under `msm_pricing.pricing_engine` so
  `msm_pricing.models` remains MetaTable-only.
- Raised the Main Sequence SDK dependency floor to `mainsequence>=4.3.8`.

### Fixed

- Fixed runtime table attachment to resolve `MetaTable` and
  `TimeIndexMetaTable` resources through POST body filters on physical table
  names.
- Fixed configured `InterpolatedPrices` storage identity so schema preparation
  and runtime construction derive the same dynamic table from registered source
  storage hash, source cadence, upsample frequency, and interpolation rule.
- Fixed stale source-cadence handling in the equal-weight portfolio
  schema-preparation workflow.
- Fixed string asset scopes in `InterpolatedPrices.update()` so portfolio
  configurations using asset identifiers work consistently.
- Fixed account holdings validation for signed quantity exposure through
  `quantity * direction`.
- Blocked `msm copy-msm-skills --path .` from running inside the ms-markets
  source checkout.

### Removed

- Removed legacy DataNode schema-bootstrap/fake-row APIs, DataNode-side dtype
  maps, record definitions, duplicate index-name constants, and compatibility
  shims that mirrored storage metadata.
- Removed the local `msm migrations` command group and old migration runner in
  favor of the SDK Alembic provider flow.
- Removed duplicated row-oriented execution fact MetaTables and APIs; execution
  facts are now storage-first.
- Removed obsolete asset reference-list, pricing, portfolio, account, execution,
  and utility shims that no longer match the current package boundaries.
- Removed core dependencies that now belong to optional extras, including
  QuantLib under `pricing` and FastAPI/Uvicorn under `public_api`.

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
- Refactored instrument valuation code into `msm_pricing`.
- Renamed pricing model helpers from the old `pricing_models` package to
  `msm_pricing.models`.

### Removed

- Removed migrated market-domain code, examples, and skills from the SDK tree.
