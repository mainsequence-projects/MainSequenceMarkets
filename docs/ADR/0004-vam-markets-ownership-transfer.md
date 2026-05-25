# 0004. VAM Markets Ownership Transfer

## Status

Accepted

## Context

The markets package has been moved out of `mainsequence-sdk` into this
independent project:

```text
MainSequenceMarkets/src/msm
```

The codebase is currently in a transition state. The `msm` package already has
the right new platform foundations:

- SQLAlchemy models under `src/msm/models`;
- MetaTable registration helpers under `src/msm/meta_tables.py`;
- repository execution helpers that compile SQLAlchemy/Core statements into
  platform `compiled-sql.v1` MetaTable operations;
- DataNode classes for market time-series data.

However, market-domain behavior is still split across three places:

- backend Django `vam.assets` still owns market models, serializers, viewsets,
  routes, and services;
- the old SDK/client-style Pydantic models under `src/msm/client/models` still
  call `/orm/api/assets/...` routes.

That is not the target architecture. The backend should stop hosting and
executing VAM market logic. The backend should provide generic platform
capabilities only: MetaTables, compiled SQL operation execution, DataNodes via
DynamicTableMetaData/DataNodeStorage, auth, labels, discovery, and command-center
surfaces.

Market ORM models, market table definitions, service logic, and workflow logic
belong in `ms-markets`.

## Decision

`ms-markets` becomes the owner of the complete markets runtime.

The ownership boundary is:

- `msm` owns all market domain SQLAlchemy models for relational/control-plane
  state.
- `msm` owns all market repositories and services.
- `msm` owns market DataNode schemas and helpers.
- `msm` owns market workflow logic such as account/fund holdings, target
  positions, asset catalog operations, portfolio storage initialization,
  rebalance metadata, signal metadata, orders, trades, and exposure
  calculations.
- `mainsequence` remains the platform SDK dependency used by `msm` for
  MetaTables, compiled SQL operations, DataNodes, DynamicTableMetaData, auth,
  labels, and generic platform APIs.
- Backend Django does not own VAM market logic after this transfer.

`msm` must not re-create the old backend ORM or DRF surface. The new runtime is
SQLAlchemy plus MetaTables for relational state and DataNodes plus
DynamicTableMetaData for time-indexed state.

## Relational State Versus DataNode State

This ADR does not migrate holdings or target-position histories into SQLAlchemy
models or MetaTables.

The boundary is:

- SQLAlchemy/MetaTables are for relational and control-plane market state:
  accounts, funds, portfolios, assets, categories, `AssetMasterList`, execution
  rows, metadata rows, and similar table-shaped domain records.
- DataNodes/DynamicTableMetaData are for time-indexed market state: account
  holdings, fund holdings, target positions, portfolio weights, signal weights,
  portfolio canonical data, prices, and other historical/timestamped frames.

Therefore:

- holdings tables are not `msm.models` SQLAlchemy classes;
- target-position tables are not `msm.models` SQLAlchemy classes;
- holdings and target-position tables are not registered by
  `register_markets_meta_tables(...)`;
- holdings and target-position writes do not use `compiled-sql.v1` MetaTable
  operations unless TS Manager later exposes a generic DataNode operation
  protocol for that purpose;
- their contracts remain DataNode/DynamicTableMetaData contracts owned by
  `msm`.

The transfer work for holdings and target positions is only to remove VAM
backend-specific helpers and make the existing DataNode contracts,
initialization, validation, and read/write orchestration backend-independent in
`msm`.

Relational repository and service execution remains platform-managed:

1. `msm` builds SQLAlchemy/Core statements.
2. `msm` compiles those statements into `compiled-sql.v1` operations.
3. TS Manager authorizes and executes those operations through registered
   MetaTables.

`msm` relational repositories and services must not accept SQLAlchemy `Session`,
`Engine`, or `Connection` execution arguments. If an application wants direct
database access, that is application code outside `msm` services.

## AssetMasterList

`AssetMasterList` must be a SQLAlchemy model in `msm`, not a Django model in the
backend.

The model belongs in the `src/msm/models` layer and must be registered as a
MetaTable like the rest of the markets relational model set.

Required semantics:

- `AssetMasterList` is a control-plane market table that names the selected
  canonical asset reference table.
- The selected asset table is identified by `reference_meta_table_uid`.
- `AssetMasterList` does not use a database-level foreign key to the backend
  `MetaTable` table. It stores the public platform UID and validates it through
  `msm` service calls and platform SDK MetaTable reads.
- Only one default master list should be allowed per access boundary represented
  by the platform table scope. If this cannot be represented portably in the
  physical table contract, `msm` services must enforce it.

Initial fields:

```text
uid
unique_identifier
name
description
reference_meta_table_uid
is_default
validation_version
metadata_json
```

The existing backend validation logic should move into `msm` services:

- resolve a requested master list or the default master list;
- validate that `reference_meta_table_uid` points to a registered MetaTable;
- validate that the referenced table exposes `unique_identifier`;
- validate that `unique_identifier` is unique or primary-key-like according to
  the MetaTable contract/introspection metadata.

## Transfer Scope

Move the backend `vam.assets` responsibilities into `msm` as library-owned
code, not as copied DRF code.

Backend responsibilities to transfer:

- `AssetMasterList` model and service logic;
- asset category and category membership logic;
- account creation/update/delete and storage binding logic;
- fund creation/update/delete and lookup logic;
- account holdings write/read logic;
- fund holdings write/read logic;
- account target-position write/read logic;
- holdings and target-position DataNode schema contracts;
- DynamicTableMetaData/DataNode source-table initialization contracts for
  time-indexed market tables;
- lookup-index and search-document requirements, generalized through TS Manager
  where backend support is still needed;
- portfolio storage source-table contracts;
- instruments configuration selection;
- order manager, target quantity, order, order event, trade, and execution-error
  persistence;
- summary payload builders where they remain useful as service helpers.

Do not transfer these as first-class runtime concepts:

- Django models;
- DRF serializers;
- DRF viewsets;
- Django permissions or queryset filtering;
- `/orm/api/assets/...` client calls;
- legacy TDAG table classes;
- legacy TDAG table updater classes;
- updater configurations;
- compatibility shims for removed imports.
- SQLAlchemy models or MetaTables for holdings, fund holdings, target
  positions, portfolio weights, signal weights, or other time-indexed DataNode
  tables.

## Target Package Shape

The package should converge on this structure:

```text
src/msm/
  models/
    asset_master_lists.py
    assets.py
    asset_categories.py
    accounts.py
    funds.py
    portfolios.py
    execution.py
    provider_details.py
    rebalancing.py
    signals.py
    instruments.py
  repositories/
    asset_master_lists.py
    assets.py
    asset_categories.py
    accounts.py
    funds.py
    portfolios.py
    execution.py
    provider_details.py
    rebalancing.py
    signals.py
    instruments.py
  services/
    asset_master_lists.py
    assets.py
    asset_categories.py
    accounts.py
    funds.py
    holdings.py
    target_positions.py
    portfolios.py
    portfolio_storage.py
    execution.py
    exposure.py
    instruments.py
  data_nodes/
    or domain-local DataNode modules under accounts/assets/portfolios
```

Existing DataNode modules may stay in their current domain folders if that keeps
the public API clearer. Relational table definitions must live in `models`, not
in removed legacy table modules or client DTO modules.

## Backend End State

The backend end state is:

- remove `vam.assets` as an installed domain app;
- remove `/orm/api/assets/` routes;
- remove VAM serializers, viewsets, custom schemas, and market-specific
  services;
- remove `vam.assets.pagination` as the global DRF pagination dependency;
- remove backend market constants endpoint `/orm/api/assets/api/constants`;
- keep only generic TS Manager and Command Center capabilities needed by
  `msm`.

Any backend feature still required by `msm` must be moved behind a generic
platform API before `vam.assets` is deleted. Examples:

- generic DynamicTableMetaData/DataNode source-table initialization;
- generic physical index creation from table contracts;
- generic table search-document registration/refresh;
- generic MetaTable contract validation and introspection.

## SDK End State

The old `mainsequence-sdk` must not own markets runtime code.

The SDK should:

- depend on no `msm` internals;
- expose platform primitives used by `msm`;
- keep `mainsequence` as the platform client package;
- remove old market endpoint mappings such as `assets/account`,
  `assets/asset`, `assets/virtualfund`, `assets/order`, and related VAM routes;
- remove lazy `MARKETS_CONSTANTS` loading from `/orm/api/assets/api/constants`;
- remove VAM wrapper methods from `DataNodeStorage` once `msm` uses generic
  DataNode initialization APIs.

Applications should import market functionality from `msm`, not from
`mainsequence.markets` or `mainsequence.client.models_vam`.

## Implementation Plan

### Phase 1: Complete The `msm` SQLAlchemy Model Set

- [x] Add `AssetMasterList` under `src/msm/models/asset_master_lists.py`.
- [x] Add `AssetMasterList` to `src/msm/models/__init__.py`.
- [x] Include `AssetMasterList` in `markets_sqlalchemy_models()` dependency
  order before models/services that need asset-master-list resolution.
- [x] Add indexes and uniqueness constraints for `AssetMasterList`, including
  `unique_identifier`, `reference_meta_table_uid`, and default-list lookup.
- [x] Confirm `AssetMasterList` uses `reference_meta_table_uid` as a platform
  UID value and does not declare a SQL foreign key to backend MetaTable storage.
- [x] Add any missing SQLAlchemy models still represented only in backend
  `vam.assets`, including calendars, account groups, account model portfolios,
  instruments configuration, orders, order events, trades, and execution errors
  where those responsibilities remain part of markets.
- [x] Ensure every relational model uses `MarketsMetaTableMixin`,
  `markets_table_name(...)`, UUID primary keys, SQLAlchemy `JSON` for JSON
  fields, and explicit SQLAlchemy indexes/foreign keys where portable.

### Phase 2: Complete MetaTable Registration

- [x] Update `register_markets_meta_tables(...)` to register the complete model
  set, including `AssetMasterList`.
- [x] Verify registration order satisfies all SQLAlchemy foreign-key target
  dependencies.
- [x] Add contract tests proving every `msm.models` SQLAlchemy model produces a
  valid MetaTable registration request.
- [x] Add tests for both `platform_managed` and `external_registered` request
  construction.
- [x] Keep `external_registered` as DDL ownership only; all `msm` repository
  execution must still use compiled MetaTable operations.

### Phase 3: Add Repositories For Every Market Table

- [x] Add `src/msm/repositories/asset_master_lists.py`.
- [x] Add create, get-by-uid, get-by-unique-identifier, get-default, search,
  update, and delete operation builders for `AssetMasterList`.
- [x] Add generic CRUD operation builders for any markets SQLAlchemy model that
  does not yet have a domain-specific repository module.
- [x] Add repositories for assets, asset categories, category memberships,
  provider details, execution tables, rebalancing metadata, signal metadata,
  instruments configuration, calendars, account groups, and account model
  portfolios.
- [x] Ensure repository functions build SQLAlchemy/Core statements and compile
  them into `compiled-sql.v1`.
- [x] Ensure repositories do not accept SQLAlchemy `Session`, `Engine`, or
  `Connection` parameters.
- [x] Add repository tests that assert compiled SQL payloads, declared MetaTable
  scope, access modes, parameters, and limits.

### Phase 4: Add Market Services

- [x] Add `src/msm/services/asset_master_lists.py`.
- [x] Move default master-list resolution into `msm`.
- [x] Move reference MetaTable validation into `msm`, including required
  `unique_identifier` column validation and uniqueness/primary-key validation.
- [x] Add asset catalog services for create/get/search/upsert assets.
- [x] Add asset category services for create/update/delete/search categories.
- [x] Add category membership services for append, remove, replace, and list
  memberships.
- [x] Add OpenFIGI/provider detail services for asset-linked provider metadata.
- [x] Add account and fund services over the SQLAlchemy/MetaTable repositories.
- [x] Add execution services for order manager, target quantity, order, order
  event, trade, and execution-error persistence.
- [x] Add portfolio metadata, rebalance metadata, and signal metadata services.
- [ ] Move summary payload helpers only when they remain useful as library-level
  return helpers; do not recreate DRF serializer behavior.

### Phase 5: Move Holdings And Target-Position Logic

- [x] Keep account holdings as DataNode/DynamicTableMetaData tables; do not add
  SQLAlchemy models or MetaTable registration for account holdings.
- [x] Keep fund holdings as DataNode/DynamicTableMetaData tables; do not add
  SQLAlchemy models or MetaTable registration for fund holdings.
- [x] Keep target positions as DataNode/DynamicTableMetaData tables; do not add
  SQLAlchemy models or MetaTable registration for target positions.
- [x] Move account holdings schema contracts into backend-independent `msm`
  DataNode/service code.
- [x] Move fund holdings schema contracts into backend-independent `msm`
  DataNode/service code.
- [x] Move target-position schema contracts into backend-independent `msm`
  DataNode/service code.
- [x] Add backend-independent account and fund holdings DataFrame builders that
  stamp `holdings_set_uid`, validate duplicate `unique_identifier` values, and
  attach the DynamicTable logical dtype contract before DataNode persistence.
- [x] Add backend-independent target-position DataFrame builders and validation
  helpers that enforce the one-exposure-shape rule.
- [ ] Replace backend account holdings write/read services with `msm` services
  that use DynamicTableMetaData/DataNodeStorage APIs.
- [ ] Replace backend fund holdings write/read services with `msm` services that
  use DynamicTableMetaData/DataNodeStorage APIs.
- [ ] Replace backend target-position write/read services with `msm` services.
- [ ] Preserve conflict checks for duplicate snapshot rows and overwrite
  behavior in `msm`.
- [ ] Preserve stable holdings-set and position-set UID generation semantics in
  `msm`.
- [ ] Add tests for holdings writes, overwrite behavior, latest snapshot reads,
  historical reads, and target-position reads using DataNode/DynamicTableMetaData
  contracts or mocked platform responses.

### Phase 6: Replace VAM DataNode Provisioning

- [x] Replace `DataNodeStorage.initialize_account_holdings_source_table(...)`
  usage with generic DynamicTableMetaData/DataNode source-table initialization.
- [x] Replace `DataNodeStorage.initialize_virtual_fund_holdings_source_table(...)`
  usage with generic initialization.
- [x] Replace `DataNodeStorage.initialize_portfolio_storage_source_tables(...)`
  usage with generic initialization or an `msm` orchestration helper that calls
  generic platform APIs.
- [x] Move portfolio storage source-table contracts into `msm`.
- [x] Confirm no DataNode table is added to `markets_sqlalchemy_models()` or
  `register_markets_meta_tables(...)`.
- [x] Identify lookup-index creation that still depends on backend VAM SQL:
  `msm` has no production lookup-index provisioning hooks after the DataNode
  move.
- [x] If lookup indexes are still required, define the needed generic TS Manager
  index contract before deleting backend VAM helpers: not required by `msm`
  Phase 6; any future lookup index support must be a generic TS Manager
  contract, not a markets-domain helper.
- [x] Identify table search-document refresh behavior that still depends on
  backend VAM services: `msm` has no production search-document provisioning
  hooks after the DataNode move.
- [x] If search documents are still required, define the needed generic TS
  Manager/Command Center API before deleting backend VAM helpers: not required
  by `msm` Phase 6; any future search-document support must be generic TS
  Manager/Command Center behavior.

### Phase 7: Remove Old `msm` Runtime Surfaces

- [x] Narrow the top-level `msm.portfolios` package import so it does not load
  legacy table modules or optional legacy utility dependencies.
- [x] Remove legacy account DTO and `/orm/api/assets/...` account-route usage
  from `AccountHoldings`; keep only DataNode frame-building helpers there.
- [x] Remove removed legacy table modules entirely.
- [x] Remove all imports and exports of legacy TDAG table classes and
  updater configurations from `src/msm`.
- [x] Remove `src/msm/client/models` from the production runtime path or narrow
  it to passive transitional DTOs that do not call `/orm/api/assets/...`:
  the package no longer exports market DTOs.
- [x] Remove all `BaseObjectOrm` market-domain persistence usage from `src/msm`.
- [x] Remove all `/orm/api/assets/...` calls from `src/msm`.
- [x] Remove lazy backend market constants usage from `src/msm`; replace needed
  constants with local library constants or explicit user configuration.
- [x] Update imports in portfolio, instruments, account, asset, and execution
  modules to use `msm.models`, `msm.repositories`, and `msm.services`.

### Phase 8: Update Docs And Examples

- [x] Add documentation for registering all `msm` SQLAlchemy models as
  MetaTables.
- [x] Add documentation for `AssetMasterList` and reference MetaTable validation.
- [x] Add examples for platform-managed market registration.
- [x] Add examples for external-registered market registration where users own
  DDL but `msm` still executes through MetaTable operations.
- [x] Add examples for asset/category workflows through `msm` services.
- [x] Add examples for account/fund/portfolio workflows through `msm` services
  and DataNodes.
- [x] Remove or replace docs that teach VAM backend routes, legacy tables, or
  old SDK market clients.

### Phase 9: Coordinate Backend Removal

- [x] In the server repository, remove `/orm/api/assets/` routes after `msm`
  replacement services exist.
- [x] Remove `vam.assets` from installed apps after migrations and imports allow
  it.
- [x] Replace `vam.assets.pagination.CustomLimitOffsetPagination` as the global
  DRF pagination dependency.
- [x] Remove VAM serializers, viewsets, custom schemas, services, admin, tasks,
  and tests that only support removed market routes.
- [x] Move any still-needed platform behavior behind generic TS Manager or
  Command Center APIs before deleting the VAM implementation.
- [x] Update backend docs to state that markets logic is owned by `ms-markets`
  and backend Django only provides generic platform primitives.

### Phase 10: Coordinate SDK Cleanup

- [x] In `mainsequence-sdk`, remove old `mainsequence.markets` runtime code if
  any remains.
- [x] Remove old market endpoint mappings from `BaseObjectOrm`.
- [x] Remove `MARKETS_CONSTANTS` loading from `/orm/api/assets/api/constants`.
- [x] Remove VAM wrapper methods from `DataNodeStorage` after `msm` no longer
  uses them.
- [x] Ensure `mainsequence-sdk` exposes only the generic platform primitives
  needed by `msm`.

## Verification

The transfer is complete when:

- legacy TDAG table runtime markers have no production references in `src/msm`;
- `rg "/orm/api/assets|MARKETS_CONSTANTS|models_vam|BaseObjectOrm" src/msm`
  returns no production runtime references;
- every `msm.models` SQLAlchemy model can produce a valid MetaTable contract;
- `register_markets_meta_tables(...)` registers all markets relational tables in
  dependency order;
- account holdings, fund holdings, target positions, portfolio weights, signal
  weights, and other historical/timestamped tables are covered by
  DataNode/DynamicTableMetaData tests and are not present in
  `markets_sqlalchemy_models()`;
- repository tests assert `compiled-sql.v1` payloads instead of direct database
  execution;
- DataNode tests initialize source-table contracts through generic platform
  APIs, not VAM wrapper routes;
- backend tests no longer need `vam.assets` for market workflows.

## Consequences

This is a breaking transfer.

Old backend routes and old SDK market clients are not compatibility surfaces.
They should be removed after the equivalent `msm` services exist.

The benefit is a clean boundary:

- `msm` is the market domain library;
- `mainsequence` is the platform SDK;
- TS Manager is the governed execution and table/data-node control plane;
- backend Django no longer hosts VAM-specific market business logic.
