
# 0017. Storage-First DataNode Architecture Migration

## Status

Completed. Stages 0–7 are complete: the import surface is restored, all 16
storage classes are declared, the custom base layer is re-architected, column
dtypes are single-sourced through the MetaTable, every concrete node uses its
registered `storage_table`, DataNode storage is wired into the catalog bootstrap
registries in FK order, the catalog path routes time-index storage through
`PlatformTimeIndexMetaData.register(...)`, runtime source-table provisioning
fallbacks are retired, dependency metadata targets SDK `4.1.5`, and the
test/example/doc surface is migrated to the storage-first contract. Offline
verification passes against SDK `4.1.5`: `369 passed, 4 skipped`.

This ADR supersedes the source-table foreign-key approach from
[ADR 0007](0007-market-data-node-asset-foreign-keys.md): asset/curve foreign
keys move from DataNode-side `SourceTableForeignKey` declarations to SQLAlchemy
`ForeignKey` columns on the storage class.

It extends the catalog bootstrap from
[ADR 0015](0015-catalog-based-metatable-bootstrap.md) to cover DataNode storage
tables, which ADR 0015 explicitly left out of scope.

It does not change the `*Table` vs `msm.api.*` split owned by
[ADR 0008](0008-metatable-table-and-api-model-split.md).

## Context

The Main Sequence SDK changed the DataNode contract. A DataNode is no longer the
canonical storage definition. Storage is now a registered
`PlatformTimeIndexMetaData` SQLAlchemy model that is declared first, registered
through `PlatformTimeIndexMetaData.register(...)`, and then passed into the
DataNode constructor as `storage_table`.

The reference for the target architecture is
`mainsequence-sdk/examples/data_nodes/simple_data_nodes.py`. The canonical flow
is:

1. declare a `PlatformTimeIndexMetaData` storage class (namespace, identifier,
   time index, identity index, columns, foreign keys);
2. register that storage class through `PlatformTimeIndexMetaData.register(...)`;
3. construct the DataNode with `config=...` and
   `storage_table=StorageClass`;
4. return a DataFrame from `update()` that matches the storage contract.

The DataNode constructor signature confirmed in the installed SDK is:

```python
DataNode.__init__(
    self,
    config: BaseConfiguration,
    storage_table: type[PlatformTimeIndexMetaData],
    *,
    hash_namespace: str | None = None,
)
```

### Why this is urgent, not optional

The installed SDK is `4.1.5`. The repository's DataNode layer was written against
`4.0.x` and imports modules that **no longer exist** in the installed package.
Verified against the project `.venv`:

| Old import (still in repo) | Status in installed SDK | New location |
| --- | --- | --- |
| `mainsequence.tdag` | removed (`ModuleNotFoundError`) | `mainsequence.meta_tables` |
| `mainsequence.tdag.data_nodes` | removed | `mainsequence.meta_tables.data_nodes` |
| `mainsequence.tdag.meta_tables` | removed | `mainsequence.meta_tables` |
| `mainsequence.client.models_tdag` | removed | `mainsequence.client` |
| `SourceTableForeignKey` | removed entirely | SQLAlchemy `ForeignKey` on storage class |

Symbols that simply moved and must be re-pointed:

- `DataNode`, `DataNodeConfiguration`, `APIDataNode`, `hash_namespace`,
  `DataNodeMetaData`, `RecordDefinition` → `mainsequence.meta_tables.data_nodes`
  (also re-exported from `mainsequence.meta_tables`).
- `PlatformTimeIndexMetaData`, `PlatformManagedMetaTable`,
  `register_external_sqlalchemy_model`,
  `external_registered_registration_request_from_sqlalchemy_model`,
  `register_platform_managed_sqlalchemy_model`,
  `build_compiled_sql_v1_operation` → `mainsequence.meta_tables`.
- `UpdateStatistics`, `ColumnMetaData`, `TableMetaData` →
  `mainsequence.client`.
- `MetaTable`, `MetaTableRegistrationRequest` → `mainsequence.client`
  (`mainsequence.client.models_metatables` still resolves).
- `UniqueIdentifierRangeMap` → exact new path **not yet located**; resolved in
  Stage 0.

The net effect: `import msm.data_nodes` and `import msm_pricing.data_nodes`
currently fail under the installed SDK. Any DataNode-touching workflow, example,
or test is broken until migrated.

### What is already on the new pattern

The **models layer** (`src/msm/models/**`, e.g. `AssetTable`, `CurveTable`,
`IssuerTable`, `IndexTable`) is already SQLAlchemy-declarative via
`MarketsMetaTableMixin` / `MarketsBase` and is registered through the ADR 0015
catalog bootstrap. Only its registration glue (`src/msm/models/registration.py`)
imports from the removed `mainsequence.tdag.meta_tables` and needs its import
path re-pointed to `mainsequence.meta_tables`. The SQLAlchemy declaration style
is correct and does not need to change.

This is the model to follow for DataNode storage: DataNode output tables become
`PlatformTimeIndexMetaData` declarations registered through the same catalog.

## Gap Inventory

The migration is not a set of import swaps. The repository encodes the *schema,
identity, and foreign-key surface inside DataNode configuration*, and the new
architecture moves that surface onto storage classes. Concrete gaps:

1. **Broken imports.** Every DataNode module imports `mainsequence.tdag*` or
   `mainsequence.client.models_tdag`. `src/msm/models/registration.py` imports
   the removed `mainsequence.tdag.meta_tables`.

2. **No storage classes exist for DataNode outputs.** There is no
   `PlatformTimeIndexMetaData` class for discount curves, index fixings, pricing
   details, account/fund holdings, orders/trades/events/errors, asset snapshots,
   portfolio/signal weights, or interpolated/external prices. Their schemas live
   today as `RecordDefinition` lists and as the dataclass
   `DataNodeTableContract` in `src/msm/data_nodes/utils/contracts.py`.

3. **Schema/identity surface lives in config.** `StampedDataNodeConfiguration`,
   `CurveDataNodeConfiguration`, `IndexDataNodeConfiguration`,
   `AssetDataNodeConfiguration` carry `records`, `index_names`,
   `time_index_name`, `node_metadata`, and `foreign_keys`. These are
   storage-contract concerns under the new model and must move to the storage
   class.

4. **DataNode constructors do not accept `storage_table`.** The custom base
   layer (`StampedDataNode`, `AssetIndexedDataNode`, `CurveTimestampedDataNode`,
   `IndexTimestampedDataNode`, `AssetTimestampedDataNode`, `HoldingsDataNode`,
   `ExecutionDataNode`, `PortfolioCanonicalDataNode`) builds storage from
   config-side records instead of accepting a registered storage class.

5. **Foreign keys use the removed `SourceTableForeignKey`.** Helpers
   `asset_unique_identifier_foreign_key` / `asset_indexed_foreign_keys`
   (`assets/asset_indexed.py`) and `curve_unique_identifier_foreign_key` /
   `curve_indexed_foreign_keys` (`data_nodes/curves.py`) must become SDK
   `MetaTableForeignKey(TargetModel, column=...)` columns on the storage class
   (ADR 0007 superseded; ADR 0019 defines the canonical FK helper).

6. **Removed hash markers.** `test_node` (2 files), `update_only` (5 files), and
   `runtime_only` / `ignore_from_storage_hash` (3 files) are no longer supported.
   `test_node` → `hash_namespace(...)`. Hash opt-out → `hash_excluded` for
   descriptive-only fields; otherwise the field stays update-scoped.

7. **`DataNodeTableContract` duplicates the storage contract.** It defines
   holdings/positions schemas independently from any MetaTable and is consumed by
   the holdings/execution nodes; it must be reconciled into the storage classes.

8. **Consumers depend on the old surface.** `src/msm_pricing/data_interface`,
   bootstrap/catalog paths, `apps/v1`, examples, and ~9 test modules import or
   build these nodes and configs.

### Migration surface

Base/framework classes to re-architect:

- `src/msm/data_nodes/utils/stamped.py` — `StampedDataNode`,
  `StampedDataNodeConfiguration`, `StampedFrameMixin`
- `src/msm/data_nodes/utils/contracts.py` — `DataNodeTableContract` + table
  contracts
- `src/msm/data_nodes/assets/asset_indexed.py` — `AssetIndexedDataNode`, FK
  helpers, asset-scope/update-statistics narrowing
- `src/msm/data_nodes/assets/snapshots.py` — `AssetTimestampedDataNode`,
  `AssetSnapshot`
- `src/msm/data_nodes/indices/timestamped.py` — `IndexTimestampedDataNode`
- `src/msm/portfolios/data_nodes/base.py` — `PortfolioCanonicalDataNode`,
  `AssetScopedPortfolioCanonicalDataNode`

Concrete nodes to migrate:

- Pricing: `DiscountCurvesNode`, `FixingRatesNode`, `AssetPricingDetail`
- Core: `AccountHoldings`, `VirtualFundHoldings`, `Orders`, `OrderEvents`,
  `Trades`, `ExecutionErrors`, `AssetSnapshot`
- Portfolios: `PortfolioWeights`, `SignalWeights`, `PortfoliosDataNode`,
  `InterpolatedPrices`, `ExternalPrices`, portfolio identity

## Decision

Adopt the storage-first DataNode architecture across `msm` and `msm_pricing`.

### 1. Storage classes are the schema contract

For every DataNode output, declare a `PlatformTimeIndexMetaData` SQLAlchemy class
that owns `__metatable_namespace__`, `__metatable_identifier__`,
`__time_index_name__`, `__index_names__`, mapped columns/dtypes, foreign keys,
description, and labels. The DataFrame returned by `update()` must match this
class. `RecordDefinition`, `DataNodeMetaData`, and `DataNodeTableContract` are
retired as the canonical schema surface.

### 2. DataNode is update logic only

DataNode constructors accept `(config, storage_table, *, hash_namespace=None)`
and forward `storage_table` to `super().__init__`. The custom base classes keep
their behavioral value (asset-scope narrowing, update-statistics scoping,
incremental update helpers) but stop owning the schema/identity surface and stop
constructing storage from config records.

### 3. Configuration is update-scoped only

`DataNodeConfiguration` subclasses keep only fields that affect update identity,
output values, dependency selection, or updater scope. Dependency storage-table
references are carried as `type[PlatformTimeIndexMetaData]` config fields (hashed
by the registered `TimeIndexMetaData.uid`). Descriptive-only fields use
`Field(..., json_schema_extra={"hash_excluded": True})`. The removed markers
`update_only`, `runtime_only`, `ignore_from_storage_hash`, and
`_ARGS_IGNORE_IN_STORAGE_HASH` are deleted.

### 4. Foreign keys move to the storage class

Asset/curve/account identity foreign keys become SDK `MetaTableForeignKey`
columns on the storage class, pointed at the target MetaTable authoring model
class. The SDK resolves registered target `MetaTable.uid` values during
registration. The `SourceTableForeignKey` helper functions are removed.

### 5. `hash_namespace` replaces `test_node`

Test and isolated-experiment runs use `hash_namespace(...)` (context manager) or
the `hash_namespace="..."` constructor argument. `test_node=True` is removed
everywhere.

### 6. DataNode storage registers through the catalog

DataNode storage classes register through the ADR 0015 catalog bootstrap, in
dependency order after their FK target MetaTables, so DataNode tables are
attach-or-create and process-idempotent like domain MetaTables. This closes the
ADR 0015 non-goal.

`PlatformTimeIndexMetaData.register(...)` is the only lifecycle path for
storage-backed DataNodes. Downstream code must not add a second path that
manually binds by UID, reconstructs generic `MetaTable` placeholders, or calls
`initialize_source_table`.

### 7. Keep the boundary the skill defines

Match `.agents/skills/mainsequence/data_publishing/data_nodes/SKILL.md`: storage
contract work and update-process work stay separate; storage registration does
not happen inside `DataNode`/`PersistManager`; first validation runs on a shared
backend use an explicit `hash_namespace(...)`.

## Success Criteria

- `import msm.data_nodes`, `import msm_pricing.data_nodes`, and
  `import msm.portfolios.data_nodes` succeed under the installed SDK.
- No repository module imports `mainsequence.tdag*` or
  `mainsequence.client.models_tdag`.
- Every concrete DataNode has a registered `PlatformTimeIndexMetaData`
  storage class and a constructor that requires `storage_table`.
- No `RecordDefinition`/`DataNodeMetaData`/`DataNodeTableContract` schema surface,
  no `SourceTableForeignKey`, no `test_node`, no removed hash markers remain.
- Column dtypes are declared only on the storage classes: no
  `*_COLUMN_DTYPES_MAP` constant, no `column_dtypes_map` configuration field, and
  no hand-rolled dtype-token vocabulary exists. Validators derive tokens from the
  MetaTable via the SDK's `dtype_codec.sqlalchemy_type_to_token`.
- DataNode storage tables register through the catalog bootstrap in FK order.
- The DataNode test suite, the pricing data interface, `apps/v1`, and the
  examples run against the new surface.

## Implementation Tasks

### Stage 0: SDK surface confirmation — DONE

- [x] Mapped every symbol still imported from a removed module to its new home
  (table below). `UniqueIdentifierRangeMap` and its neighbours are in
  `mainsequence.client.models_metatables`.
- [x] Runtime APIs used by the base layer are **unchanged**: `DataNode.run`,
  `get_df_between_dates`, `get_last_observation`, `local_persist_manager`,
  `update_statistics`, `get_offset_start`, `_get_data_node_configuration`,
  `_set_update_statistics`.
- [x] `PlatformTimeIndexMetaData` exposes `register`,
  `build_registration_request`, `get_meta_table`, `get_meta_table_uid`,
  `get_time_index_metadata`, `get_storage_hash`, `resolve_foreign_key_targets`;
  `MetaTableForeignKey(TargetModel, column=...)` is the FK authoring API and
  `register(...)` is the storage lifecycle entrypoint.
- [x] ~~Pin/record the target SDK version in `pyproject.toml` / `uv.lock`~~ —
  skipped by maintainer decision.
- [x] ~~Throwaway smoke script mirroring `simple_data_nodes.py`~~ — skipped by
  maintainer decision.

#### Stage 0 symbol mapping

Verified against the project `.venv` (SDK `4.1.5`):

| Symbol(s) | Old (removed) import | New home |
| --- | --- | --- |
| `DataNode`, `DataNodeConfiguration`, `APIDataNode`, `RecordDefinition`, `DataNodeMetaData`, `hash_namespace` | `mainsequence.tdag.data_nodes` | `mainsequence.meta_tables.data_nodes` (also re-exported from `mainsequence.meta_tables`) |
| `string_freq_to_time_delta`, `string_frequency_to_minutes` | `mainsequence.tdag.data_nodes.utils` | `mainsequence.meta_tables.data_nodes.utils` |
| `PlatformManagedMetaTable`, `POSTGRES_IDENTIFIER_MAX_LENGTH`, `metatable_tablename`, `metatable_configured_tablename`, `slugify_identifier`, `compile_sqlalchemy_statement`, `register_external_sqlalchemy_model`, `external_registered_registration_request_from_sqlalchemy_model` | `mainsequence.tdag.meta_tables` | `mainsequence.meta_tables` |
| `UniqueIdentifierRangeMap`, `UpdateStatistics`, `ColumnMetaData`, `TableMetaData`, `LOGICAL_COLUMN_DTYPES_ATTR` | `mainsequence.client.models_tdag` | `mainsequence.client.models_metatables` |
| `Artifact` | `mainsequence.client.models_tdag` | `mainsequence.client` |
| `SourceTableForeignKey` | `mainsequence.tdag.data_nodes` | **removed** — model FKs as SDK `MetaTableForeignKey(TargetModel, column=...)` on the storage class (Decision §4, ADR 0019) |
| `DataNodeStorage` | `mainsequence.client.models_tdag` | **no exported drop-in** — runtime source-table provisioning is superseded by storage-class registration |

### Stage 1: Re-point already-correct models layer — DONE

- [x] Re-pointed `mainsequence.tdag.meta_tables` → `mainsequence.meta_tables` in
  the four models/runtime-chain files: `src/msm/base.py`,
  `src/msm/models/registration.py`, `src/msm/maintenance/catalog.py`,
  `src/msm/repositories/base.py`.
- [x] Verified the chain imports cleanly under the installed SDK: `msm.base`,
  `msm.models`, `msm.models.registration`, `msm.repositories.base`,
  `msm.maintenance.catalog`, `msm.bootstrap`, and `msm` (with `start_engine`
  present). `msm/__init__.py` does not eagerly import `data_nodes`. Verification
  is import/resolution level only; live platform registration was not exercised
  (needs a backend connection).
- Deferred to later stages (data-node-coupled, not models-layer): three files
  outside `data_nodes` still import old paths but depend on the unmigrated
  data-node layer, so they move with it —
  `src/msm/services/holdings.py` and `src/msm/services/target_positions.py`
  (import `DataNodeTableContract` + table contracts from `msm.data_nodes.utils`,
  plus `LOGICAL_COLUMN_DTYPES_ATTR`) in Stage 3; `src/msm/portfolios/models.py`
  (imports `mainsequence.tdag.data_nodes.build_operations`) in Stage 4.

### Stage 2: Storage contracts for DataNode outputs — DONE

- [x] Defined all 16 `PlatformTimeIndexMetaData` storage classes across three
  declaration-only modules (co-located with the Stage 4 nodes; no `__init__.py`
  touched): `src/msm_pricing/data_nodes/storage.py` (`DiscountCurvesStorage`,
  `IndexFixingsStorage`, `AssetPricingDetailsStorage`);
  `src/msm/data_nodes/storage.py` (`AssetSnapshotsStorage`,
  `AccountHoldingsStorage`, `FundHoldingsStorage`, `TargetPositionsStorage`,
  `OrdersStorage`, `OrderEventsStorage`, `TradesStorage`,
  `ExecutionErrorsStorage`); `src/msm/portfolios/data_nodes/storage.py`
  (`PortfolioWeightsStorage`, `SignalWeightsStorage`, `PortfoliosStorage`,
  `InterpolatedPricesStorage`, `ExternalPricesStorage`).
- [x] Ported column names/dtypes/descriptions from the legacy `RecordDefinition`
  lists, `DataNodeTableContract` entries, execution/portfolio dtype maps, and the
  prices node outputs onto SQLAlchemy `mapped_column(..., info={"label", "description"})`.
  Index columns are `nullable=False`; data columns `nullable=True`. The two
  reserved names map onto safe Python attributes via a positional column name —
  `ExecutionErrorsStorage.error_metadata` → `"metadata"`, `PortfoliosStorage.return_`
  → `"return"`. Interpolated/external price columns had no legacy `RecordDefinition`
  so their descriptions are net-new.
- [x] FK columns (Decision §4; legacy only declared canonical FKs on
  curve/index/fixings/asset-snapshot nodes, plus holdings gain account/fund
  identity FKs): `DiscountCurvesStorage.curve_unique_identifier` → `Curve`,
  `IndexFixingsStorage.unique_identifier` → `Index`,
  `AssetPricingDetailsStorage.unique_identifier` / `AssetSnapshotsStorage.unique_identifier`
  → `Asset`, `AccountHoldingsStorage.account_uid` → `Account.uid`,
  `AccountHoldingsStorage.unique_identifier` → `Asset.unique_identifier`,
  `FundHoldingsStorage.fund_uid` → `Fund.uid`,
  `FundHoldingsStorage.unique_identifier` → `Asset.unique_identifier`
  (all `ondelete="RESTRICT"`). The
  other 10 outputs carry no FK. Convention: `String(255)` only on FK string
  columns (to match the target `unique_identifier`); plain `String` otherwise.
- [x] Set `__index_names__`/`__time_index_name__` per class from the legacy
  `index_names`/`unique_constraint` (execution tables key on the domain time
  column — `order_time`/`event_time`/`trade_time`/`time_recorded`). Every class
  sets `__metatable_extra_hash_components__={"storage_name": ...}` so the
  shape-derived physical name does not collide. Verified declaration-only:
  building all 16 `.__table__`s yields 16 distinct tables with FK targets
  resolved, label/description projected, and the Stage 1 import surface intact.

### Stage 3: Re-architect the custom base layer — DONE (import surface)

Scope executed: make every base-layer module import cleanly under SDK 4.1.5 and
the storage-first constructor (`__init__(self, config, storage_table, *,
hash_namespace=None)`), re-source eager constants/identity from the storage
classes, drop dead re-exports, and trim the import-blocking config fields. The
foundation classes were rewritten in full; the remaining method-body rewrites
(record-list / `node_metadata`-driven validation and metadata) are carried into
Stage 4 alongside the concrete-node migration.

- [x] Rewrote `StampedDataNode` / `StampedFrameMixin` (`utils/stamped.py`) to
  accept and forward `storage_table`; `normalize_stamped_frame()` now validates
  columns/index/dtypes against the storage contract (`__table__.columns`,
  `__index_names__`, `__time_index_name__`) instead of a config `records` list.
- [x] Rewrote `AssetIndexedDataNode` (`assets/asset_indexed.py`) to accept and
  forward `storage_table`, source identity dimensions from
  `storage_table.__index_names__`, validate the asset-index contract, and keep
  asset-scope / update-statistics narrowing; deleted the legacy FK helper functions.
- [x] Removed `DataNodeTableContract`: deleted `utils/contracts.py`, dropped every
  live import, and `LOGICAL_COLUMN_DTYPES_ATTR` is fully gone.
  `services/holdings.py` and `services/target_positions.py` import cleanly.
  (Residual stringized annotations / body calls in `holdings.py` are
  deferred-broken until Stage 4.)
- [x] Base/intermediate timestamped node classes import cleanly on the new SDK:
  `CurveTimestampedDataNode`, `IndexTimestampedDataNode`, `AssetTimestampedDataNode`,
  `HoldingsDataNode`, `ExecutionDataNode`, `PortfolioCanonicalDataNode`,
  `AssetScopedPortfolioCanonicalDataNode`.
- [x] Trimmed the import-blocking eager config fields
  (`records: list[RecordDefinition]`, `node_metadata: DataNodeMetaData`) from every
  `*DataNodeConfiguration`; dropped dead re-exports (e.g. `portfolios/data_nodes/__init__.py`).
- [x] Verified: 23/23 base-layer modules import in a fresh subprocess (project + SDK
  pyc cleared) and `ruff --select F401` is clean across the base layer.

### Stage 3.5: Purge deprecated SDK concepts — DONE

The deprecated `RecordDefinition` / `DataNodeMetaData` / `node_metadata` /
`DataNodeTableContract` surface is removed from SDK 4.1.5, so every remaining
reference was runtime-dead (import-clean only under stringized annotations).
This pass purged them and re-sourced each validator's column dtype map from the
storage class, without starting the concrete-node `storage_table` wiring.

> **Superseded in part by Stage 3.6 and Stage 3.7.** Two dtype claims below no longer hold:
> that `storage_column_dtypes_map()` maps each column's SQLAlchemy `python_type`
> to "the existing dtype tokens", and that the Layer-B validators "carry a real
> `column_dtypes_map` field". Stage 3.6 deleted that `python_type`→token
> vocabulary (tokens now come straight from the SDK's `sqlalchemy_type_to_token`)
> and removed the `column_dtypes_map` configuration field. Stage 3.7 then removed
> concrete `_required_column_dtypes_map()` methods so runtime validation derives
> from the DataNode instance's bound `storage_table`.

- [x] Added `data_nodes/utils/storage_schema.py`:
  `storage_column_dtypes_map()` / `storage_index_names()` /
  `storage_time_index_name()` map each storage `__table__` column's
  SQLAlchemy `python_type` to the existing dtype tokens (verified
  byte-for-byte against each validator's prior coercion vocabulary).
- [x] Layer-B validators (`accounts.py`, `execution.py`, portfolios
  `base.py` / `signal_weights.py` / `portfolio_weights.py` / `portfolios.py`)
  were moved off `RecordDefinition`; deleted `_record_definitions_from_dtype_map`
  / `_merge_records` / `_validate_required_records`. Later stages removed the
  temporary `column_dtypes_map` configuration field and concrete
  `_required_column_dtypes_map()` overrides.
- [x] Deleted the `*_record()` / `*_records()` helper functions and their
  `__all__` / package-`__init__` exports across `snapshots.py`,
  `pricing_details.py`, `curves.py`, `index_fixings.py`.
- [x] Removed `get_table_metadata()` / `get_column_metadata()` (read
  `config.node_metadata`) from `curves.py` and `index_fixings.py`; dropped the
  now-unused `ColumnMetaData` / `TableMetaData` / `DataFrequency` imports.
- [x] Rewired `services/holdings.py` and `services/target_positions.py` off the
  deleted `*_TABLE_CONTRACT` onto the storage classes
  (`AccountHoldingsStorage` / `FundHoldingsStorage` / `TargetPositionsStorage`)
  via `storage_column_dtypes_map`; deleted the dead `*_source_table_kwargs`
  helpers and their `services/__init__.py` exports.
- [x] Deleted the now-orphaned `*_COLUMN_LABELS` / `*_COLUMN_DESCRIPTIONS`
  dicts from `portfolios/data_nodes/constants.py` (the column labels/descriptions
  live on the storage-class `info=` dicts, the single source of truth).
- [x] Verified: 21 touched modules import in a fresh subprocess (project pyc
  cleared); `ruff check` clean; repo-wide grep finds no `RecordDefinition` /
  `DataNodeMetaData` / `node_metadata` / `DataNodeTableContract` /
  `get_table_metadata` / `get_column_metadata` / `.records` /
  `LOGICAL_COLUMN_DTYPES_ATTR` outside historical ADR prose.
- Still deferred to Stage 4 (co-located with concrete-node migration): align the
  Layer-A leaf-node `validate_frame(*, storage_table)` call sites with the
  foundation signature and convert descriptive fields to `hash_excluded`.

### Stage 3.6: Single-source column dtypes through the MetaTable — DONE

Stage 3.5 left two dtype sources in the tree: a hand-rolled `python_type`→token
vocabulary inside `storage_schema.py`, and a `column_dtypes_map` field carried on
the Layer-B configurations. Both are removed here so the storage class (the
MetaTable) is the single source of column dtypes, derived through the SDK rather
than any local token list.

- [x] Rewrote `data_nodes/utils/storage_schema.py` to derive tokens straight from
  the MetaTable: `storage_column_dtypes_map()` returns
  `{column.name: sqlalchemy_type_to_token(column.type, remote=True) ...}` over
  `storage_table.__table__.columns`. Deleted the invented `_PYTHON_TYPE_TO_DTYPE`
  map and the `_column_dtype_token` shim.
- [x] Rewrote holdings nullability handling to read
  `column.nullable` from the storage MetaTable via `storage_column_nullable_map()`;
  deleted the local `NULLABLE_HOLDINGS_COLUMNS` schema mirror.
- [x] Removed holdings time-index and index-name constants such as
  `ACCOUNT_HOLDINGS_INDEX_NAMES`; holdings nodes now read
  `__time_index_name__` and `__index_names__` directly from their storage
  MetaTable classes.
- [x] Removed residual `time_index_name` / `index_names` fields from holdings,
  execution, and canonical portfolio DataNode configurations. Validators and
  storage-contract checks now read those values from the bound `storage_table`.
- [x] Deleted all 7 `*_COLUMN_DTYPES_MAP` module constants — execution
  (`EXECUTION_ERRORS`, `ORDER_EVENTS`, `ORDERS`, `TRADES`) and portfolios
  (`PORTFOLIO_WEIGHTS`, `SIGNAL_WEIGHTS`, `PORTFOLIOS`) — and removed their
  package re-exports (`data_nodes/__init__.py`, `portfolios/__init__.py`,
  `portfolios/data_nodes/__init__.py`).
- [x] Removed the `column_dtypes_map` configuration field from
  `HoldingsDataNodeConfiguration`, `ExecutionDataNodeConfiguration`,
  `PortfolioCanonicalDataNodeConfiguration`, and `SignalWeightsConfiguration` (the
  true second source). Stage 3.7 removes the temporary concrete
  `_required_column_dtypes_map()` methods; classmethod validation paths use
  `_column_dtypes_map_for_storage(...)`, and runtime validation uses the DataNode
  instance's bound `storage_table`.
- [x] Repointed every coercion branch onto `dtype_codec` constants
  (`dc.TIMESTAMP_TZ` / `dc.FLOAT64` / `dc.STRING` / `dc.BOOL` / `dc.INT64` /
  `dc.JSONB` / `dc.UUID_TOKEN`) instead of invented string literals. Only the
  datetime token changes value under the SDK projection
  (`"datetime64[ns, UTC]"` → `'timestamp with time zone'`); every other token
  already matched. Pandas runtime casts (`.astype("datetime64[ns, UTC]")`,
  `.astype("string")`) and the `DATETIME64_NS_UTC` constant in `utils/time.py`
  are legitimate pandas API and are kept.
- [x] Deleted placeholder-row helpers from `utils/stamped.py` and the dead
  consumer aliases in `assets/snapshots.py`. DataNodes do not fabricate rows to
  shape storage; storage registration is a MetaTable/catalog responsibility.
- [x] `_validate_storage_contract` keeps the *remote* read of the platform
  source-config `column_dtypes_map` (platform metadata, not a local declaration);
  only the local side switches to the instance-bound storage map.
- [x] Verified against SDK `4.1.5`: repo-wide grep finds no `*_COLUMN_DTYPES_MAP`
  constant, no `column_dtypes_map` configuration field, and no hand-rolled token
  vocabulary in `src` (remaining `column_dtypes_map` occurrences are the derived
  method, threaded params, and the remote-read contract); `ruff check` is clean
  (no F401 regressions); and coercion round-trips pass for the holdings,
  execution, and portfolio node families.

### Stage 3.7: Runtime dtype validation uses bound storage — DONE

Stage 3.6 still left a wrong boundary: concrete DataNode classes carried
`_required_column_dtypes_map()` methods that hardcoded their default storage
class. That was still a second local declaration and ignored the `storage_table`
bound to a constructed DataNode instance.

- [x] Removed concrete `_required_column_dtypes_map()` overrides from holdings,
  execution, and portfolio DataNodes.
- [x] Added shared `_column_dtypes_map_for_storage(...)` helpers for
  classmethod validation paths where no DataNode instance exists.
- [x] Added `_bound_column_dtypes_map()` and rewired `update()` plus storage
  contract validation to use `self.storage_table`.
- [x] Removed instance fallback frames; frame-inserting DataNodes now require
  real rows before `update()` and fail instead of manufacturing placeholders.
- [x] Removed production `build_mock_frame` and holdings-specific
  `build_mock_*_frame` aliases; callers should use explicit
  domain build helpers or `validate_frame(...)` with real rows.
- [x] Updated tests so they assert the removed concrete method is absent and
  dtype maps derive from storage classes explicitly.

### Stage 4: Concrete node migration — DONE

Every concrete node uses its registered storage class through a
`_required_storage_table()` classmethod. The two foundation constructors —
`StampedFrameMixin.__init__` and `AssetIndexedDataNode.__init__` — default
`storage_table` to `self._required_storage_table()` before forwarding to the SDK
`DataNode.__init__`, so every leaf chain (stamped, asset-indexed, holdings,
execution, portfolio-canonical, and the custom inits in
`DiscountCurvesNode` / `FixingRatesNode` / `SignalWeights`) reaches the SDK with
the correct storage class. The stamped-family validator (`validate_frame`) also
defaults `storage_table` to `cls._required_storage_table()`.

- [x] Pricing: `DiscountCurvesNode` → `DiscountCurvesStorage`, `FixingRatesNode`
  → `IndexFixingsStorage`, `AssetPricingDetail` → `AssetPricingDetailsStorage`.
  Repointed the stamped-family `validate_frame(..., config=...)` call sites in
  `curves.py` / `index_fixings.py` onto `validate_frame(..., storage_table=self.storage_table)`.
- [x] Core: `AccountHoldings` → `AccountHoldingsStorage`, `VirtualFundHoldings`
  → `FundHoldingsStorage`, `Orders` / `OrderEvents` / `Trades` /
  `ExecutionErrors` → their `*Storage`, `AssetSnapshot` → `AssetSnapshotsStorage`.
  `AssetSnapshot.build_frame` / `validate_frame` call sites moved off the dropped
  `config=` kwarg onto the foundation `storage_table` signature.
- [x] Portfolios: `PortfolioWeights` / `SignalWeights` / `PortfoliosDataNode` →
  their `*Storage`. `InterpolatedPrices` / `ExternalPrices` (`contrib/prices`)
  had their deferred `mainsequence.tdag*` / `models_tdag` imports migrated to
  `mainsequence.meta_tables*` / `mainsequence.client` and now use
  `InterpolatedPricesStorage` / `ExternalPricesStorage`. `portfolio identity`
  (`portfolio_identity.py`) is function-only — no DataNode to wire.
- [x] Removed the dead `test_node` handling from `utils/namespaces.py` and
  `portfolios/data_nodes/base.py` (the SDK marker is gone; `hash_namespace(...)`
  is the only path). Remaining `test_node=` call sites live in tests/examples
  (Stage 6).
- [x] Confirmed time-index dtype using real validated frames: the first index
  level is `datetime64[ns, UTC]`.

Verified against SDK `4.1.5`: all 13 backend-registrable nodes resolve their
storage class; `ruff check` is clean; the three node packages import. Full
construction is gated by the SDK `storage_table` setter
(`get_time_index_metadata()` must be non-`None`) — every node reaches exactly
that registration gate, which proves `storage_table` is forwarded correctly
through all MRO chains; satisfying it is Stage 5 (catalog registration).
`contrib/prices` import-verifies only where its declared `pandas-market-calendars`
dependency is installed (absent from the current venv), but its migrated SDK
imports resolve and it is lint-clean.

### Stage 5: Registration and consumers — DONE

DataNode storage now registers through the same ADR 0015 catalog bootstrap as
domain MetaTables: the 13 msm storage classes are appended to
`markets_sqlalchemy_models()` and the 3 pricing storage classes to
`pricing_sqlalchemy_models()`, each after their FK target MetaTables, so
`start_engine()` / `create_pricing_schemas()` register them in dependency order.
Catalog rows keep identifier-keyed backend references. Runtime row operations
read operation-scope UIDs from the bound model classes. FK declarations are
model-keyed `MetaTableForeignKey(...)` columns, so the markets runtime no longer
carries SQLAlchemy table-name target maps.

- [x] Registered DataNode storage through the catalog: extended both model
  registries in FK order. Storage classes are imported **lazily inside** the
  registry functions (`_markets_data_node_storage_models()` /
  `_pricing_data_node_storage_models()`) to avoid an import cycle — the storage
  modules import their FK-target domain tables from `msm.models`. Verified:
  markets = 41 models (13 storage), pricing = 10 (3 storage), every FK target
  precedes its dependant, all physical table names unique.
- [x] Consumers/bootstrap: fixed a pre-existing SDK-drift break —
  `msm/repositories/base.py` imported `compile_sqlalchemy_statement` from
  `mainsequence.meta_tables`, which 4.1.5 only exposes at
  `mainsequence.meta_tables.compiled_sql.v1`; that had been silently blocking the
  whole catalog/`start_engine`/pricing chain. Migrated
  `src/msm_pricing/data_interface/data_interface.py` and the four
  `portfolios/contrib/signals/*` modules off the removed `mainsequence.tdag*` /
  `models_tdag` imports. `src/msm/maintenance/catalog.py` and both `bootstrap.py`
  modules needed no change (they operate on the registry list and now pick up the
  storage classes automatically).
- [x] `apps/v1` builds/reads none of these DataNodes directly (only a
  `getAssetPricingDetails` operation-id string matched); it uses the
  repository/service layer. No change required.
- [x] `src/msm/data_nodes/__init__.py` lazy-export map carries no retired
  `*_RECORDS` / `*_TABLE_CONTRACT` / `RecordDefinition` entries (already clean).

Verified against SDK `4.1.5`: repo-wide grep finds **zero** `mainsequence.tdag` /
`models_tdag` imports in `src`; the full bootstrap/registry/data_nodes import
chain imports. Actual platform registration remains backend-gated, but offline
registration request construction and catalog bootstrap behavior are covered by
tests.

### Stage 6: Tests, examples, docs — DONE

- [x] Migrated the affected test modules to the storage-first contract: the 8
  modules that asserted removed concepts (`test_contracts`,
  `test_portfolio_contracts`, `test_asset_indexed_data_nodes`,
  `test_index_stamped_data_nodes`, `test_asset_snapshots`, `test_curves`,
  `test_index_fixings`, `test_package_structure`) now assert
  `_required_storage_table()` / `_column_dtypes_map_for_storage(<Storage>)`,
  absence of concrete `_required_column_dtypes_map()` methods, bootstrap-frame
  `datetime64[ns, UTC]`, registry membership, FK targets, and the
  construction-gating contract;
  `test_data_interface` and the two `models` tests were re-pointed off
  `mainsequence.tdag*`; `test_meta_tables` / `test_metatable_models` now expect
  the storage classes in the registries. Repository compiled-SQL tests now assert
  SDK `4.1.5` remote temporal parameter serialization. Genuinely backend-only cases (live
  registration, row I/O, `update()`) are `@pytest.mark.skip`-ped with a reason
  and replaced by offline gating assertions. Full suite: **369 passed, 4
  skipped**.
- [x] Updated `examples/**`: re-pointed the removed `mainsequence.tdag.meta_tables`
  import and replaced `config.node_metadata.identifier` with the node's
  `_default_identifier()` across the holdings/asset/currency/bond-pricing
  workflows. Concrete DataNodes no longer declare `__data_node_identifier__` or
  duplicated descriptions; `_default_identifier()` and `_default_description()`
  derive from each node's storage class. After Stage 5, `start_engine()`
  registers the storage classes, so examples that bootstrap then construct nodes
  need no manual `storage_table` plumbing.
- [x] Updated `docs/knowledge`: rewrote the `asset_indexed_data_nodes.md` FK code
  example to a storage-first `PlatformTimeIndexMetaData` class +
  `_required_storage_table()`, and corrected `indices/index.md` /
  `accounts/index.md` (`RecordDefinition` → storage class). The data_nodes
  `SKILL.md` is SDK-owned guidance (referenced, not edited).
- [x] Updated `CHANGELOG.md` with the ADR 0017 storage-first migration entry.

Stage 6 verification also surfaced and fixed two registration-correctness gaps
that only appear once requests build for the storage classes: the markets
register/build helpers (`models/registration.py`) and the catalog
(`maintenance/catalog.py`) are now kind-aware — they omit `introspect` /
`open_for_everyone` for `PlatformTimeIndexMetaData` storage classes (which the
SDK rejects for that base) via `_platform_registration_kwargs(...)`; and all six
FK-bearing storage classes now declare explicit `name=markets_fk_name(...)` FK
names (the SDK requires named MetaTable foreign keys).

### Stage 7: Cleanup and verification — DONE

- [x] Removed the retired hash markers that SDK 4.1.5 now rejects in
  `serialize_pydantic_model`: deleted every
  `json_schema_extra={"update_only": True}` (configuration fields are
  update-scoped by default) and converted every
  `json_schema_extra={"runtime_only": True}` to `{"hash_excluded": True}` across
  `assets/asset_indexed.py`, `data_nodes/curves.py`, `data_nodes/index_fixings.py`,
  `contrib/prices/data_nodes.py`, portfolios `base.py`, and `portfolios/models.py`.
  These were latent bugs that raise the moment a config is hashed. The old
  contract dataclass (`DataNodeTableContract`) was already removed in Stage 3.
- [x] Grep-gate: zero `mainsequence.tdag` / `models_tdag` / `RecordDefinition` /
  `DataNodeMetaData` / `SourceTableForeignKey` / `test_node=` / `update_only` /
  `runtime_only` / `ignore_from_storage_hash` / `_ARGS_IGNORE_IN_STORAGE_HASH` /
  `LOGICAL_COLUMN_DTYPES_ATTR` / `*_COLUMN_DTYPES_MAP` references remain in `src` /
  `tests` / `apps` / `examples` (the single `SourceTableForeignKey` hit is a test
  docstring recording the helper's removal).
- [x] Changed-file lint + offline test run: targeted `ruff check` is clean for
  the edited modules/tests. The full suite is **369 passed, 4 skipped**. The
  repo-wide `ruff check` still reports the pre-existing F403/F405 star-import
  baseline plus one untouched E731.
- [x] Retired the runtime source-table provisioning fallbacks. Holdings and
  portfolio readiness now rely on registered storage metadata and the DataNode
  bootstrap/run path; no `initialize_source_table` fallback remains in `src` or
  `tests`.

## Consequences

The schema/identity/FK surface concentrates on registered storage classes, which
matches the SDK contract and the existing models layer, and makes DataNode
storage participate in the same catalog lifecycle as domain MetaTables. DataNode
classes shrink to update logic plus dependency wiring.

The cost is real: this touches the entire DataNode layer, its custom base
classes, every consumer, and the test/example/doc surface. It cannot be a pure
import rename because schema responsibility relocates from config to storage. The
work should be staged so each stage leaves the tree importable, ideally
node-family by node-family behind the shared base-class rewrite.

Because the repository does not import under the installed SDK today, the project
is effectively blocked on this migration; sequencing Stage 0–3 first restores a
working import surface before the bulk node migration.

## Risks

- **Storage hash / identity drift.** Moving schema to storage classes can change
  storage hashes; existing platform tables may need the ADR 0015 pre-catalog
  import path or a documented repair, not silent re-registration.
- **Hidden behavior in the base layer.** Asset-scope narrowing and
  update-statistics scoping in `AssetIndexedDataNode` are subtle; preserve them
  under test rather than rewriting from scratch.
- **FK target resolution.** `MetaTableForeignKey` target models must be
  available in the registration graph. Parent tables are still listed before
  dependants so recursive SDK registration and catalog binding resolve stable
  target `MetaTable.uid` values.

## Non-Goals

- Not a schema migration engine; contract drift is detected and reported per
  ADR 0015, not auto-migrated.
- Does not change the `*Table` vs `msm.api.*` split (ADR 0008).
- Does not change portfolio/signal business semantics; only their DataNode
  storage and construction contract.
- Does not redesign the catalog table; it reuses ADR 0015's catalog.
