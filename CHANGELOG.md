# Changelog

All notable changes to this project should be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows versioned releases.

## [Unreleased]

### Changed

- Added reusable `command_center` helpers for ms-markets Command Center
  tabular frames and Asset Monitor workspace documents, plus the
  `apps/v1` `getAssetMonitorFrame` reference endpoint.
- Added project-local namespace defaults for ms-markets extension models through
  `__metatable_namespace__` plus `__markets_base_identifier__`, while keeping
  `MSM_AUTO_REGISTER_NAMESPACE` as the test/example override.
- Added `msm_pricing.api.add_many_pricing_details(...)` and
  `AssetPricingDetails.add_many(...)` for chunked bulk persistence of
  asset/instrument pricing details.
- Changed pricing-detail batch writes to set per-operation SDK `max_rows`
  limits from the submitted chunk size instead of carrying a local response
  pagination loop.
- Removed the obsolete pricing schema-creation bootstrap entrypoint; pricing
  startup now uses the attach-only `msm_pricing.bootstrap.attach_pricing_schemas(...)`
  API.
- Removed the unused `msm_pricing.streamlit` helper package and the
  `pricing-streamlit` optional extra.
- Added ADR 0033 to document the pricing valuation-position boundary and the
  planned replacement for the legacy in-memory `Position` surface.
- Added ADR 0035 to document the target pricing curve identity model, curve
  building details, and market-data-set curve binding layer.
- Added ADR 0036 to document the prepared pricing valuation context target,
  including the requirement that portfolio/scenario valuation use bulk
  SQLAlchemy-backed resolution instead of hiding per-line backend lookup loops
  behind a public API, and that prepared instruments are copied or wrapped
  rather than mutating caller-owned instrument objects.
- Implemented `PricingValuationContext` with a public `PreparedInstrument`
  wrapper, frozen `PricingValuationContextSpec` input contract, fixed
  prepared-instrument universe, package-level exports, context-aware
  `ValuationPosition` methods, `price_scenario(...)`, set-based row API helpers
  for pricing market-data bindings, index rows, index convention details, curve
  bindings, curves, and curve-building details, bulk curve/fixing observation
  reads, context-owned QuantLib curve handles/indexes, hot-loop resolver
  injection for prepared floating-rate bond pricing, and a runnable mock
  curve/fixing valuation-context example.
- Implemented ADR 0035 phase-one pricing curve infrastructure with
  `CurveBuildingDetails`, `PricingMarketDataSetCurveBinding`, nullable legacy
  `Curve.index_uid`, resolver cutover to explicit curve bindings, and Alembic
  revision `0007`.
- Replaced the legacy in-memory `msm_pricing.Position` export with
  `ValuationLine` and `ValuationPosition` for explicit instrument-plus-units
  valuation.
- Added `msm_pricing.api.load_instruments_from_assets(...)` for chunked
  current-instrument loading from asset rows, and documented the account and
  portfolio normalization boundary for valuation baskets.
- Added `MSDataInterface.get_latest_discount_curve(...)` for explicit latest
  discount-curve lookup by curve identity without using the global
  `USE_LAST_OBSERVATION_MS_INSTRUMENT` fallback.
- Added `DiscountCurvesStorage.key_nodes` and row `metadata_json` columns, with
  `key_nodes` treated as producer-owned JSON construction provenance at
  publisher/API boundaries and compressed text at rest.
- Added the optional `msm_pricing.data_nodes.CurveKeyNode` helper as the
  recommended key-node shape, including raw quote fields and yield-native
  `yield` serialization for discount-curve producers.
- Added `DiscountCurvesNode.normalize_key_nodes(...)` and
  `set_key_nodes_validator(...)` so curve DataNode producers can enforce
  source-specific key-node provenance schemas without tightening the shared
  storage contract.
- Tightened `DiscountCurvesStorage.curve` to a required non-null payload and
  made discount-curve builders reject missing, null, or empty curve mappings.
- Added observation-level discount-curve reads carrying `nodes`, `key_nodes`,
  and `metadata_json`, and exposed those provenance fields in the pricing curve
  API response.
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
- Added the `apps/v1` target-allocation candidate search endpoint for account
  target-position assignment, returning one paginated asset and portfolio
  candidate list backed by a compiled MetaTable read.
- Added the `apps/v1` account target-position write endpoint, deriving parent
  allocation rows from the account uid and replacing target-position snapshots
  through one scoped MetaTable upsert operation.
- Tightened account target-position validation so portfolio target rows cannot
  use `single_asset_quantity`.
- Tightened `PortfoliosDataNode.run(update_pointers=True)` so portfolio pointer
  updates use explicit DataNodeUpdate UIDs, preserve the existing executed
  weights pointer when no new weights are produced, and no longer cache a hidden
  `PortfolioWeights` helper on the portfolio node.
- Changed portfolio update-window calculation so the start date comes from this
  portfolio's own `PortfoliosStorage.portfolio_identifier`, and valuation-source
  coverage is applied only after reading the actual signal frame.
- Added the `apps/v1` pricing curve registry list endpoint backed by
  `msm_pricing.api.Curve` and the shared limit-offset pagination envelope.
- Added the `apps/v1` index delete-impact preflight endpoint so clients can
  inspect restrictive dependencies, cascade effects, and SET NULL effects
  before calling the individual index delete route.
- Added the FastAPI v1 reusable delete-impact contract and migrated the index
  preflight route to the shared `DeleteImpactResponse` serializer before
  additional delete routes copy the index-specific shape.
- Added the FastAPI v1 curve-selection reverse lookup endpoint for pricing
  curves, removed the curve list `index_uid` filter, and changed index
  delete-impact to count `PricingMarketDataSetCurveBinding` index selectors.
- Clarified missing discount-curve API errors so a curve with registry and
  market-data binding but no published `DiscountCurvesStorage` observations is
  reported as missing data, not a generic latest-observation lookup failure.
- Changed pricing curve construction to honor
  `CurveBuildingDetails.interpolation_method` with native QuantLib curve
  constructors and reject deprecated methods such as `log_linear_zero` and
  `MonotonicLogCubicDiscountCurve`.
- Promoted virtual-fund allocation strategy to the first-class
  `VirtualFundHoldingsStorage.allocation_strategy` column; low-level explicit
  publications write `explicit`, and planner-applied rows write the allocation
  policy mode.
- Refactored portfolio construction to consume an explicit
  `valuation_source_instance` instead of having `PortfoliosDataNode` construct
  `InterpolatedPrices` from portfolio `AssetsConfiguration`/`PricesConfiguration`,
  and updated the equal-weight portfolio example to show the explicit source
  valuations -> interpolation when needed -> signal -> portfolio dependency
  graph.
- Replaced deprecated builder terminology with portfolio construction wording
  across README, portfolio docs, ADRs, and internal portfolio logger helper
  names.
- Changed core portfolio storage identity so portfolio weights, values, FastAPI
  latest-weight reads, delete cleanup, and account virtual-fund expansion use
  `PortfolioTable.unique_identifier` as `portfolio_identifier`; optional
  `published_index_uid` remains publication metadata only.
- Added nullable `PortfolioTable.signal_uid` as a foreign-key pointer to
  `SignalMetadataTable.signal_uid`; portfolio workflow pointer updates now
  persist the resolved signal UID, and portfolio signal-weight API reads use
  that first-class pointer instead of inferring from shared storage.
- Changed portfolio core construction to consume
  `valuation_source_instance` plus arbitrary `valuation_column: str`, replacing
  the OHLC-bound `price_source_instance` and `PriceTypeNames` price-column
  contract while keeping bar-specific helpers in contributed price workflows.
- Added core portfolio group MetaTables, typed row helpers, FastAPI v1 routes,
  docs, examples, and tests for many-to-many portfolio classification through
  `PortfolioGroupTable` and `PortfolioGroupMembershipTable`.
- Extended the full account portfolio example to assign the generated target
  sleeve portfolio to an example `PortfolioGroup` through the public portfolio
  group API.
- Changed portfolio execution to raise a clear calendar materialization error
  when the rebalance calendar has no sessions for the requested update range,
  instead of reporting a misleading empty portfolio-weight no-op.
- Changed `msm copy-msm-skills` to delegate its filesystem copy mechanics to
  the Main Sequence SDK scaffold-skill helper while keeping the same public
  command UX. Successful copies now write `.agents/skills/ms_markets/PINNED_FROM.txt`.

### Fixed

- Fixed the `apps/v1` asset-category detail endpoint so
  `response_format=frontend_detail` returns membership-backed detail metadata,
  including `number_of_assets` and the nested asset-list `categories__uid`
  filter, instead of a bare `AssetCategory` row.
- Fixed category-filtered asset lists so `categories__uid` resolves membership
  asset UIDs directly instead of filtering only the first scanned asset page.
- Fixed portfolio value row normalization so `PortfoliosDataNode` resolves a
  real portfolio identifier instead of stringifying its `_unique_identifier`
  method, and declared the `PortfoliosStorage.portfolio_identifier` foreign key
  to `PortfolioTable.unique_identifier`.
- Reworked pricing-details writes so user-facing instrument attachment upserts
  `AssetPricingDetailsStorage`; calls without `pricing_details_date` use `now()`
  and update `AssetCurrentPricingDetailsTable`, while calls with an explicit
  date upsert only that timestamped snapshot.
- Clarified account and portfolio example console output with section titles,
  corrected portfolio workflow step numbering, and cleaner virtual-fund
  allocation frame rendering.
- Fixed account virtual-fund planning for portfolio targets so portfolio
  sleeves expand from the latest `PortfolioWeightsStorage` snapshot at or
  before valuation time instead of requiring exact timestamp equality.
- Normalized `InterpolatedPrices.update()` output time indexes and timestamp
  columns back to `datetime64[ns, UTC]` so backend-read microsecond timestamps
  do not fail SDK DataNode update validation.
- Fixed the equal-weight portfolio schema-preparation workflow so it derives the
  dynamic revision from the active migration namespace and runs the dynamic
  provider upgrade before `--run-after`, even when a stale metadata row already
  exists for the configured interpolation table.
- Fixed `PortfoliosDataNode` forced reruns when the latest stored portfolio
  value is already ahead of usable valuation-source coverage; the portfolio
  update now returns no new rows before calling calendar scheduling with a
  reversed date range.
- Fixed `ImmediateSignal` so portfolio valuation sources only need the
  configured valuation column; missing `volume` now produces nullable
  portfolio-weight volume fields instead of failing the rebalance calculation.
- Fixed `msm_pricing.api.add_pricing_details(...)` so omitting
  `pricing_details_date` delegates the no-date current-update behavior to
  `AssetPricingDetails.add(...)` instead of pre-filling a timestamp too early.
- Fixed explicit-date pricing detail writes so current pricing details are
  updated when no current row exists, when the new date is newer than current,
  or when the same timestamp is being replaced.
- Fixed portfolio update-window selection so source valuation coverage is
  evaluated only for assets required by the portfolio, instead of taking the
  oldest progress timestamp across every asset in a large upstream valuation
  table.
- Fixed portfolio update-window selection for `APIDataNode` valuation sources
  by loading the API source table update statistics before required asset
  progress is evaluated.
- Made portfolio update-window selection strict when no required asset scope can
  be determined, instead of falling back to table-wide source progress.
- Fixed portfolio output progress lookup so a shared `PortfoliosStorage`
  table-wide max from another `portfolio_identifier` cannot move the current
  portfolio's update start date.
- Fixed contributed portfolio signal cursors so shared `SignalWeightsStorage`
  progress from another `signal_uid` cannot move the current signal's source
  window.

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
  TimeIndexMetaTable UID, source cadence, upsample frequency, and interpolation
  rule.
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
