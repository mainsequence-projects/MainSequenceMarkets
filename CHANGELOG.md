# Changelog

All notable changes to this project should be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows versioned releases.

## [Unreleased]

### Changed

- Reorganized `msm.data_nodes` so account, asset, execution, and index
  DataNodes live under model-shaped modules, while non-model shared DataNode
  helpers live under `msm.data_nodes.utils`.

### Added

- Added `AssetTypeTable` plus the `msm.api.assets.AssetType` row API as a
  minimal asset type registry with unique `asset_type`, optional
  `display_name`, optional `description`, and optional `metadata_json`.
- Added `CurrencySpotTable` plus the `msm.api.assets.CurrencySpot` workflow for
  currency spot pair assets keyed by canonical base and quote currency `Asset`
  rows.
- Added typed asset-type normalization so API payloads store lowercase
  underscore-separated `asset_type` keys.
- Added the `msm` console command with `copy-msm-skills` to explicitly copy the
  packaged ms-markets agent skills into a host project's
  `.agents/skills/ms_markets/` directory without import-time filesystem
  mutation.
- Added user-facing Pydantic row APIs under `msm.api.*` for every markets
  MetaTable, including asset reference data, accounts, portfolios, funds,
  metadata/configuration, and execution records.
- Added explicit `/openapi.json` metadata and documentation coverage for the
  local `apps/v1` FastAPI surface.
- Added the migrated `apps/v1` asset-category API surface, including list,
  detail, create, patch, delete, and bulk-delete routes plus
  `categories__uid` filtering on `GET /api/v1/asset/`.
- Added the local `apps/v1` index registry API surface with
  `GET /api/v1/index/`, `GET /api/v1/index/{uid}/`, and
  `DELETE /api/v1/index/{uid}/`.
- Added an ADR for a simple `GET /api/v1/index/` route that mirrors the asset
  list boundary while returning index registry rows from `IndexTable`.
- Added shared typed row helpers for explicit schema bootstrap, create/upsert,
  lookup, filter, update, and delete operations over the active markets runtime.
- Added `examples/api/typed_metatable_rows.py` to demonstrate the class-owned
  row API across multi-table markets workflows.
- Added the initial local FastAPI asset list endpoint at `GET /api/v1/asset/`
  under `apps/v1/`.
- Added a GitHub Actions workflow to build and publish `ms-markets` to PyPI
  when a `v*` tag is pushed, using GitHub OIDC trusted publishing.
- Added an asset CRUD example covering asset creation, lookup by identifier and
  UID, OpenFIGI detail registration, AssetSnapshot frame updates, created asset
  listing, and optional cleanup of temporary custom assets.
- Added `examples/assets/asset_category_workflow.py` to demonstrate creating an
  asset category, adding assets, removing assets, and printing membership after
  each change without leaving the category empty during the normal run.
- Added `examples/assets/utils/reference_data.py` so asset examples reuse the
  same asset type payloads, asset identifiers, currency definitions, and FIGI
  constants.
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
- Added lazy row-operation runtime resolution: `msm.api.*` row methods now
  attach to already-registered MetaTables by default, and
  `MSM_AUTO_REGISTER_NAMESPACE` enables opt-in example/development
  auto-registration.
- Updated `MSM_AUTO_REGISTER_NAMESPACE` so it also drives default markets
  DataNode identifiers and `hash_namespace` values, not only MetaTable runtime
  registration.
- Centralized markets namespace resolution in `msm.settings.markets_namespace`
  so MetaTables, bootstrap attach/register flows, and DataNodes use the same
  environment/default rule.
- Added shared markets identifier resolution: the default namespace keeps bare
  identifiers such as `Asset`, while non-default namespaces prefix identifiers
  as `<namespace>.<identifier>`.
- Exposed registered MetaTable handles and DataNode class handles on the
  `msm.create_schemas(...)` runtime instead of accepting broad labels on startup.
- Added `models=[...]` support to `msm.create_schemas(...)` so narrow workflows
  can register only the required markets MetaTables.
- Added `runtime.table("Asset")` / `MarketsMetaTableHandle` for single-table
  service calls without passing the full repository context.
- Added an ADR for making `AssetIndexedDataNode` configurations declare
  canonical foreign keys to the `Asset` MetaTable.
- Added an ADR for splitting SQLAlchemy MetaTable declarations such as
  `AssetTable` from user-facing Pydantic API row models such as `Asset`.
- Added an ADR for the first asset extension: currency spot pair assets with
  normalized asset types and relational base/quote asset references.
- Added an ADR for `future` assets, `IndexTable`, and index-underlying future
  contract details.
- Added an ADR for pricing-owned current asset pricing details, moving
  pricing-detail DataNodes into `msm_pricing`, and the `msm_pricing` runtime
  package boundary cleanup.
- Added `msm_pricing.data_nodes.pricing_details` as the canonical home for the
  `AssetPricingDetail` DataNode and its configuration.
- Added `AssetCurrentPricingDetailsTable` under `msm_pricing.models` for the
  current one-to-one priceable definition attached to a canonical asset.
- Added `msm_pricing.meta_tables.pricing_sqlalchemy_models()` so pricing
  MetaTable registration can discover `AssetTable` before pricing extension
  tables.
- Added `msm_pricing.meta_tables.register_pricing_meta_tables()` to register the
  pricing MetaTable graph while resolving the core asset-table dependency.
- Added `msm_pricing.api` current-pricing-detail row helpers plus
  `InstrumentModel.attach_to_asset(...)` and `Instrument.load_from_asset(...)`
  for asset-first pricing workflows.
- Added pricing-owned `IndexConventionDetailsTable` and `CurveTable` MetaTables
  plus a stamped `DiscountCurvesNode` keyed by `curve_unique_identifier` instead
  of asset identity.
- Added `msm_pricing.api.IndexConventionDetails` and `msm_pricing.api.Curve`
  row APIs for registering pricing index conventions and curve identities
  through the pricing MetaTable runtime.
- Added UID-based pricing resolvers so bonds and swaps materialize QuantLib
  indices and curves from `IndexTable.uid`, `IndexConventionDetails`, and
  `CurveTable` instead of raw index-name strings.
- Added rich configuration-owned discovery metadata for `DiscountCurvesNode`
  describing its row grain, Curve MetaTable identity link, compressed curve
  payload, and pricing use.
- Added an index-stamped `FixingRatesNode` helper with hashable observation
  frequency configuration so pricing fixings reference `IndexTable` identity
  instead of asset identity.
- Moved compressed curve serialization helpers into
  `msm_pricing.data_nodes.curve_codec` and removed the obsolete
  `msm_pricing.interest_rates.etl.curve_codec` module.
- Removed the obsolete Constant-based
  `msm_pricing.interest_rates.etl.registry` builder registry; curve and fixing
  DataNodes now use `CurveTable.unique_identifier` and
  `IndexTable.unique_identifier` directly with runtime builder callables or
  subclass hooks.
- Removed the obsolete `msm_pricing.interest_rates` package and its
  `interest_rates.etl.nodes` compatibility path; pricing DataNodes are exported
  from `msm_pricing.data_nodes`.
- Removed the legacy `main_sequence_asset_id` field from `InstrumentModel` so
  serialized pricing instruments remain identity-free and asset linkage stays
  in pricing persistence.
- Removed stale serialized `*_index_name` pricing relationships from bond and
  swap payloads; persisted instruments now require backend index UUID fields
  such as `floating_rate_index_uid` and `float_leg_index_uid`.
- Added an ADR for `bond` assets, issuer reference data, and the planned
  one-to-one bond detail table.
- Implemented `IssuerTable`, `BondDetailsTable`, `msm.api.issuers.Issuer`, and
  `msm.api.assets.Bond` for registering bonds through the user-facing API.
- Added `examples/assets/us_treasury_bond_workflow.py` showing how CUSIP, FIGI,
  issuer, maturity, coupon, and tenor fields map to the current bond API.
- Added OpenFIGI helpers to register index rows from FIGI and create
  index-underlying futures from index/future FIGIs while keeping contract terms
  explicit.
- Added `examples/assets/derivatives/index_future_from_openfigi.py` for creating an
  index-underlying future from OpenFIGI FIGIs.
- Added `examples/assets/derivatives/crypto_future_without_figi.py` for creating
  a crypto perpetual future from local asset and index identifiers only.
- Documented the library-wide API style: users work with typed `msm.api` row
  objects, while schema code works with `msm.models.*Table` declarations.
- Added AssetSnapshot DataNode methods for validated frame construction and
  row binding before DataNode runs.
- Added a shared `StampedDataNode` frame/config base plus
  `IndexTimestampedDataNode` and `IndexDataNodeConfiguration` for timestamped
  facts keyed to `IndexTable.unique_identifier`.
- Added `examples/platform/bootstrap.py` as the home for the example MetaTable
  namespace and auto-registration environment constants.
- Documented the attach-first row API pattern, explicit schema preflight option,
  and example-scoped auto-registration flow.
- Documented the asset CRUD workflow in the asset knowledge docs and market
  workflow tutorial.
- Corrected the examples directory name to `examples/`.
- Added the `mainsequence.examples` MetaTable namespace bootstrap for examples
  that create platform resources.

### Changed

- Grouped asset-related SQLAlchemy model declarations under the
  `msm.models.assets` package while keeping aggregate `msm.models` table exports
  stable.
- Updated the local `apps/v1` startup flow so `MSM_AUTO_REGISTER_NAMESPACE`
  performs startup-time schema bootstrap against the real project/session
  data source instead of waiting for the first request to trigger row-level
  runtime resolution.
- Moved the `apps/v1` asset and asset-category catalog composition into
  `src/msm/services/asset_master_lists.py` so the FastAPI layer stays a thin
  resolver over reusable `src/` workflows.
- Moved detailed `AssetSnapshot` documentation from the asset identity overview
  into a dedicated Asset-Indexed DataNodes knowledge page covering
  `AssetIndexedDataNode`, canonical asset source-table foreign keys, namespace
  behavior, and `AssetSnapshot`.
- Updated `OpenFigiDetailsTable` to use `asset_uid` as the one-to-one
  primary-key/foreign-key asset detail identity instead of a separate detail
  `uid`.
- Moved the QuantLib-backed pricing runtime out of core `msm` into the
  separate `msm_pricing` import package, removed the `msm.pricing` path, and
  made QuantLib a `pricing` extra instead of a core dependency.
- Moved QuantLib-backed runtime helpers from `msm_pricing.models` to
  `msm_pricing.pricing_engine` so `msm_pricing.models` follows the same
  MetaTable-only convention as core `msm.models`.
- Moved FastAPI and Uvicorn out of core dependencies into the `public_api`
  optional extra used by the project-level `apps/v1` surface.
- Removed the obsolete asset reference-list MetaTable, row API, repository,
  service helpers, tests, and documentation page from the markets library.
- Removed duplicate runtime version constants; `msm.__version__` now reads the
  installed `ms-markets` package metadata generated from `pyproject.toml`.
- Removed `venue_specific_properties` from the `AssetSnapshot` DataNode schema;
  provider-specific payloads belong in provider detail tables such as
  `OpenFigiDetails`.
- Implemented the first ADR 0007 slice: `AssetSnapshot` and
  `AssetPricingDetail` now use `AssetIndexedDataNode` configuration and declare
  a canonical source-table FK from `unique_identifier` to
  `AssetTable.unique_identifier`.
- Removed the legacy asset-indexed DataNode compatibility aliases, shim module,
  and old table-contract class name; use `AssetIndexedDataNode`,
  `AssetIndexedDataNodeConfiguration`, and `DataNodeTableContract` directly.
- Updated OpenFIGI helpers to read `OPEN_FIGI_API_KEY` from Main Sequence
  Secrets by default and updated FIGI examples to call OpenFIGI instead of
  relying on hardcoded provider response payloads.
- Updated markets MetaTable models to inherit SDK `PlatformManagedMetaTable`
  naming through `MarketsMetaTableMixin` instead of hand-writing
  `__tablename__`.
- Removed the arbitrary `metadata_json` column and create/update/upsert payload
  from the core `Asset` MetaTable model.
- Updated asset service helpers to accept the registered asset table handle
  while keeping the full repository context available for multi-table workflows.
- Updated examples and asset notebooks so MetaTable row CRUD goes through
  `msm.api.*` with example-scoped auto-registration instead of explicit
  bootstrap in normal workflows.
- Removed redundant standalone `asset_snapshot_workflow.py` and
  `openfigi_asset_rows.py` examples now covered by `asset_crud_workflow.py`.
- Updated markets DataNodes to derive default published identifiers and
  `hash_namespace` values from the active markets namespace plus class-owned
  `__data_node_identifier__` values unless callers explicitly override them.
- Split AssetSnapshot node construction from snapshot row binding, made
  `time_index` a required per-row snapshot field, and added a backend duplicate
  check before persisting `(time_index, unique_identifier)` rows.
- Normalized DataNode datetime columns to `datetime64[ns, UTC]` so pandas
  microsecond inference from Python datetimes cannot fail SDK update validation.
- Replaced AssetSnapshot and AssetPricingDetail parallel dtype/label/description
  maps with configuration-owned `RecordDefinition` default factories.
- Moved markets DataNode hash-namespace defaulting into a shared wrapper used by
  asset-indexed, index-stamped, and canonical portfolio DataNode bases.
- Moved asset-indexed DataNode machinery from the root `msm` package into
  `msm.data_nodes.assets.asset_indexed` and kept index-stamped foreign-key
  helpers in `msm.data_nodes.indices`.
- Moved asset-scope adapter helpers from the root `msm` package into
  `msm.portfolios.asset_scope`.
- Moved the packaged console implementation from `msm.cli` into the top-level
  `cli` package while keeping the installed command name `msm`.
- Moved markets MetaTable registration and resolution helpers from
  `msm.meta_tables` into `msm.models.registration`.
- Removed legacy unsuffixed `msm.models.*` aliases such as `msm.models.Asset`;
  schema code must import `*Table` declarations and user-facing code must import
  row objects from `msm.api.*`.

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
