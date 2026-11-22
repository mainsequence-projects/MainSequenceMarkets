# 0060. Producers Publish, Markets Reads Only Its Own Tables

## Status

Accepted (2026-11-19). The owner decided the rule (decision 1), that each published row is
stored once, in Markets' tables (decision 2), that ms-markets ships the primitives and
recipes a producer needs (decisions 3, 5 and 6), and that a skill teaches producers the
pattern (decision 10).

Implemented (2026-11-20), released in 4.2.0: decisions 1 to 11. The names below are
final; the signatures are under [Implementation Notes](#implementation-notes), which also
record where the implementation departs from the text above and the "Not Verified" items
it settled.

- It supersedes decision 5 of
  [ADR 0047](0047-markets-api-application-boundary.md) (contract instances read through a
  Markets catalog) and withdraws the grant of its decision 4 (`include` hydration of a
  provider's sidecar). Decisions 1 to 3 of ADR 0047 stand, and this ADR implements the
  `managed_by` field its decision 4 names.
- It replaces the request of
  [issue #98](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/98):
  Markets does not read a provider's table as the caller, because it does not read it at all.
- It changes the delete notes of [ADR 0049](0049-portfolio-lifecycle-and-account-history.md)
  and [ADR 0050](0050-account-deletion.md) where they count rows in another application's
  table.
- [Execution Engine ADR 0001](execution_engine/0001-execution-engine-architecture.md)
  (proposed) already records orders and
  trades this way: a recorder writes Markets' tables
  through the API.

## Context

### What ADR 0047 decision 5 built

A producer (any application that computes signals or portfolios) keeps its own *contract
instances* of `SignalWeightsTS`, `PortfolioWeightsTS` and `PortfoliosTS`, binds the engine
to them with `output_table=`, and registers their table uids in a Markets catalog
(`PortfolioDatasetAvailabilityTable`, `SignalMetadata.meta_table_uid`). Markets then reads
those tables as its own workload User:

- registration and reconciliation look the tables up, check them against the contract and
  count their rows;
- the read routes (`GET /portfolio/values/`, `/portfolio/weights/`,
  `/portfolio/{uid}/signals_weights/` and the per-portfolio forms) read them by uid;
- `include=` on the by-uid lookups reads any sidecar table whose uid the caller names;
- the portfolio delete counts the portfolio's rows in them and refuses when it cannot.

### Why that is the wrong direction

- **The core depends on its extensions.** Markets works only while each producer grants its
  workload `data_viewer`. MetaTables keeps a grant to another repository with people (its
  ADR 0029), so a person repeats it in every Environment, and a missing grant fails the
  producer's own registration.
- **Markets is a confused deputy.** Anyone who may call a read route reads the producer's
  table with Markets' grant. Two routes take the table uid from the caller.
- **Deletes reason about rows Markets does not own.** A table Markets cannot read blocks the
  delete.
- **The platform offers no way out.** Issue #98 asked for Markets to read as the caller.
  Checked on 2026-11-19 against `mainsequence` 9.0.40 and MetaTables 0.1.71: an application
  cannot call another application for its caller, a workload is never a requester, and
  MetaTables refuses requester calls on the routes these reads use. It would also multiply
  the grants: every reader would need one on every producer.
- **The pattern spreads.** ms-markets is the base other libraries build on. A base that
  reaches into its dependents teaches every library above it to do the same.

### What the engine reads back

Each engine node continues a run from rows already written. With the three series stored only
in Markets, these reads come from Markets:

| Node | Reads of published series |
| --- | --- |
| `SignalWeights` and its subclasses | its own progress per signal and asset, its last observation, interpolation windows |
| `PortfolioRebalance` | the signal-weights window and the last weights before it |
| `PortfolioWeights` | its own last row per portfolio (the seed of `price_before`) |
| `PortfoliosUpdater` | the weights window and seed, its own last `close` |

Progress comes today from MetaTables' update record of the bound output table
(`update_statistics.index_progress`). Rebalance state, calendar events, the event ledger and
prices are read from tables the producer keeps.

### Markets already has the pattern

`AccountHoldingsSnapshots.publish`, `AssetSnapshots.publish`, `registerAccount` and
`addAccountTargetPositions` take rows from an application and write Markets' own tables, in
one bounded, idempotent call. Portfolios are the part that diverged: no operation writes a
signal-weights, portfolio-weights or portfolio-values row except an updater bound to a table.

### What a producer writes by hand today

Every producer repeats the same routines around the engine: validate and publish weights and
create the signal's metadata on first publication; refuse an observation at or before the
last one; read a signal's first and last observation and its latest observations; read a
portfolio's value history and its weights as of a time; build and run the node chain in
order; register and reconcile after each run; delete its series in the order the foreign
keys demand; move history between tables. None of it is specific to the producer.

## Decision

### 1. Markets reads and writes only its own tables (owner)

Markets touches only tables that its own migrations create. No route, row operation,
service, Job or command of ms-markets takes a table uid, name or namespace from a caller or
from a registry row and reads, counts, checks or deletes what it names.

Data crosses the boundary of ms-markets in two ways, and no third:

- **Publish.** An application sends rows to a Markets operation. Markets stores them in its
  own table and serves them. The rows are Markets' from then on.
- **Keep.** An application keeps data in its own tables and serves or shares it itself.
  Markets holds nothing about it.

An endpoint belongs to Markets only if it would exist with no producer but Markets itself.
Publish and read operations pass: they serve any producer, Markets' own Jobs included. A
catalog of someone else's tables, a check of their shape or a count of their rows does not.

ms-markets names no dependent anywhere: not in code, configuration, documentation or tests.

### 2. A published row is stored once, in Markets' tables (owner)

`SignalWeightsStorage`, `PortfolioWeightsStorage` and `PortfoliosStorage` are the only store
of signal weights, portfolio weights and portfolio values of a registered signal or
portfolio. A producer has no table for them and keeps no copy.

A producer keeps, in its own namespace, what only it needs: prices, engine state (rebalance
state, calendar events, event ledger), and its own tables.

Publishing shares the rows with everyone who may read Markets. A producer that must not
share a portfolio does not register it in Markets.

### 3. Series operations are the primitive

Each published series gets a row class in `msm_portfolios.api`, dispatched like every other
row class: compiled SQL on the core table under the `runtime` backend, and
`POST /api/v1/rows/{resource}/{operation}/` under `remote`. Proposed names:
`SignalWeightsSeries` (`signal-weights`), `PortfolioWeightsSeries` (`portfolio-weights`) and
`PortfolioValuesSeries` (`portfolio-values`).

| Operation | What it does |
| --- | --- |
| `publish(key, rows)` | Writes rows of one signal or portfolio in one transaction. A row equal to the stored one is skipped; a different row for a stored key refuses the call and writes nothing. Bounded per call; the answer counts written and skipped rows. |
| `window(keys, start, end, columns)` | Rows of several keys in a time range, paged. |
| `last(keys, at, by)` | The last row at or before `at`, per key and optionally per asset. |
| `bounds(keys)` | First time, last time and row count per key. |
| `assets(key)` | Every asset a signal or portfolio has ever had a row for. |
| `delete_after(key, time)` | Deletes one key's rows after a time, so a producer can restate them. |

- `publish` on signal weights keeps today's rules of `ApplicationWeights.publish`: times are
  timezone-aware, weights are finite numbers, assets are registered, an asset dropped since
  the last observation is written at 0, and an observation at or before the last stored one
  is refused. The rules run in Markets, so every producer gets them.
- The existing read routes keep their paths and answers and read the core tables only.
- `publish` and `delete_after` are registry writes: `registry_write` records who made them.

### 4. Only a row's manager publishes to it

`SignalMetadataTable` and `PortfolioTable` gain `managed_by`: the application that created
the row, recorded from the acting identity of the create call. `publish`, `delete_after` and
the row's delete are refused with 403 for any other caller. An Organization admin may
reassign it.

A row created before this ADR has no manager and accepts no publish until a person assigns
one (decision 9).

### 5. The engine writes and reads published series through those operations

- `SignalWeights` and its subclasses, `PortfolioWeights` and `PortfoliosUpdater` write with
  `publish` and read with `window`, `last` and `bounds`. `output_table=` on the signal nodes
  and on `PortfoliosUpdater`, and `weights_output_table=`, are removed, with no alias.
- A node's progress is the series itself (`bounds`, `last`), not an update record of a bound
  table. Running the same window twice writes nothing the second time.
- Private state keeps its tables: `rebalance_output_table=`, the calendar-events
  `output_table=` and the event-ledger table stay, built by the factories of decision 7.
- The same code runs inside the Markets deployment under the `runtime` backend, so Markets
  is one more producer and has no path of its own.

### 6. Recipes: what a producer reuses instead of writing

ms-markets ships these as functions in `msm_portfolios.recipes` (proposed), built only on
decisions 3 and 5. Each works under both backends.

| Recipe | What it does | Routine it replaces in a producer |
| --- | --- | --- |
| `publish_signal_weights` | Creates the signal's metadata on its first publication, publishes the observations, answers the count, the assets and the first and last time. | Normalizing observations, the not-after-last guard, the metadata upsert, binding the signal to a table. |
| `signal_history` | First and last observation of many signals in one call; the latest N observations as a time by asset matrix. | Hand-compiled SQL over its signal-weights table. |
| `portfolio_history` | A portfolio's values newest first, with the total count. | Hand-compiled SQL over its values table. |
| `weights_as_of` | Each portfolio's latest weights at or before a time, for several portfolios. | Hand-compiled SQL over its weights table. |
| `portfolio_preflight` | Why a portfolio cannot run yet, for example a signal with no observation. | Its own read of the signal's bounds before each run. |
| `run_portfolio` | Runs one portfolio's chain in order (prices, calendar events, rebalance, weights, values) from the signal's first observation, creates or updates the `Portfolio` row, publishes, and answers what was written and whether a first rebalance happened. | Building the node graph, ordering the runs, scoping the signal's progress, registering and reconciling afterwards. |
| `end_signal` | Deletes a signal's weights and its metadata in one Markets call. | Deleting its observations, then unbinding and deleting the metadata. |
| `delete_private_series` | Deletes a producer's private rows of given portfolios, calendars or accounts in the order their keys demand, before the registry delete. | Its own ordered deletes. |

The producer supplies what is its own: the price source, the private state tables, the
strategy and calendar configuration, and its eligibility rules (which assets or owners it
accepts) before it calls a recipe.

### 7. Private contract instances stay, and Markets never looks at them

`configured_portfolio_rebalance_state_storage`, `configured_portfolio_calendar_events_storage`,
`configured_portfolio_event_ledger_storage` and `configured_time_index_instance` stay: a
producer builds its private state tables with them, in its own namespace, migrated by its own
provider. `configured_signal_weights_storage`, `configured_portfolio_weights_storage` and
`configured_portfolios_storage` are removed with the instances they built.

Amended (2026-11-22, [issue #95](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/95)):
the four require the producer's namespace, storage app and base, so none builds in
Markets' by omission. An interpolated-price table is an instance of
`configured_time_index_instance` like the others, keyed by its configuration, and
`InterpolatedPrices` takes it as `output_table=`.

A private table may reference a registry row with a physical foreign key and declares its
delete action. The key points from the dependent to the core and is the only coupling
between them. Since
[#108](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/108) that holds
in the dependent's metadata too: the key passes the core's column object and no core table
is copied there, so the dependent's migrations change only its own tables.
Markets does not discover, count or name such a table:

- a registry delete deletes Markets' own rows and lets the database apply every key;
- a `RESTRICT` key that refuses answers 409 with the database's message;
- the application that owns the referencing rows deletes them first (`delete_private_series`).

### 8. What is removed

Removed everywhere, with no alias, flag or compatibility path:

- `PortfolioDatasetAvailabilityTable` and `SignalMetadataTable.meta_table_uid`, by a
  revision;
- `PortfolioDatasets`, `msm_portfolios.services.portfolio_datasets`, and the routes
  `registerPortfolioDatasets`, `reconcilePortfolioDatasets` and `getPortfolioDatasets`;
- the `TimeIndexTableRef` path of `msm_portfolios.services.portfolio_reads`;
- `provider_owned_table_uid`, `PROVIDER_TABLE_DELETE_GUIDANCE`,
  `PortfolioDatasetOwnershipError`, `SignalDatasetOwnershipError` and `retained_datasets`;
- the foreign-table checks of `msm_portfolios.services.portfolio_deletion`
  (`ForeignPortfolioTable`, `_catalogued_instances`, `_count_foreign_rows`);
- `apps/v1/services/includes.py`, the `include` parameter and the `includes` field of the
  four by-uid lookups. A consumer reads a sidecar from the application that owns it;
- `PortfolioSeriesMove` and `SignalSeriesMove`, which end by registering a catalog row.
  `copy_time_index_rows` and `TableSeriesMove` stay: an operator copies rows between two
  tables with the operator's own access, and Markets takes no part.

### 9. Existing history and existing rows move on demand

Nothing here runs by itself. A person runs each step when they choose:

- `msm series publish` (proposed) reads a producer's instance with the operator's own access
  and publishes its rows through decision 3, key by key, then compares `bounds` with the
  source. It changes nothing in the source.
- `msm registry assign-manager` (proposed) sets `managed_by` on rows created before this ADR.
- The producer drops its instance tables in a later revision of its own, after the publish
  is verified.

### 10. A skill teaches producers the pattern (owner)

ms-markets ships a skill, `.agents/skills/ms_markets/platform/producer_boundary/SKILL.md`
(proposed path), in the wheel with the others. An agent or a person building an application
on ms-markets reads it before they design how the application meets Markets. It holds:

- the rule of decision 1 and the two ways data crosses, with the test "would Markets need to
  read my table for this to work?" If yes, the design is wrong;
- how to choose, per dataset: publish it (a series ms-markets defines for a registry row, read
  the same way across producers) or keep it private;
- what a producer supplies and what it reuses: the recipes of decision 6, one worked example
  from weights to a published portfolio, and where its own rules go (before the recipe);
- how to build private state tables with the factories of decision 7, their foreign keys, and
  the delete order;
- what a producer never does: grant Markets a role on its tables, register a table with
  Markets, send Markets a table uid, keep a namespace for Markets to read, or keep a copy of a
  published series;
- a template for the producer's own boundary ADR, so each application records the same
  things: what it does today, which series it publishes, which tables stay private, where each
  of its reads comes from afterwards, its delete order, the business rules that do not change,
  and its rollout in each Environment;
- a checklist to verify the result: no grant to Markets exists, no table uid leaves the
  application, and a new Environment needs no person's step for Markets.

The skill names no application. The existing skills that describe instances and grants
(`portfolios/portfolio_workflow`, `platform/metatable_migrations`,
`accounts/account_workflow`) are corrected with it.

### 11. The rule is documented and tested

- `docs/concepts.md` states decision 1 as a rule of the library.
- The pages that describe the catalog are rewritten with the implementation:
  `docs/knowledge/msm_portfolios/portfolios/index.md`, `docs/knowledge/msm/client/index.md`,
  `docs/fast_api/v1/portfolio.md`, `portfolio_signal_metadata.md`, `accounts.md`,
  `assets.md`, `indexes.md`, `rows.md`, and the grants table of `docs/releasing.md`.
- One test fails the build when code under `apps/v1` or a library service resolves a
  MetaTables table by anything but one of ms-markets' own model classes.

## What changes for a producer

| Step | Before | After |
| --- | --- | --- |
| Tables it migrates | Instances of the three series, plus private state | Private state only |
| Publishing weights | `ApplicationWeights.publish` on its instance, metadata upsert, `register_signal` | `publish_signal_weights` |
| Running a portfolio | Node graph bound with `output_table=`, then `register` and `reconcile` | `run_portfolio` |
| Reading its own history | SQL over its instances | `signal_history`, `portfolio_history`, `weights_as_of` |
| Access it gives Markets | `data_viewer` on its instances, by a person, per Environment | None |
| Deleting a portfolio | Its three series and its state, then the portfolio | Its private state, then the portfolio; Markets deletes the series |
| Ending a signal | Its observations, the catalog binding, the metadata | `end_signal` |

## Not Decided Here

These read tables Markets does not own and break decision 1 until each is decided. The
direction is the same: the rows are published, or Markets takes no part.

- **Index values.** `configured_index_values_storage` builds a producer's table, and the
  Index dataset routes, `reconcile_dataset_availability` and the Index delete impact find and
  read it.
- **Formula sources.** An Index formula pins source tables by uid
  ([ADR 0037](0037-index-formula-and-custom-calculation-framework.md)); the preview routes
  read whatever uid a caller sends.
- **Pricing market-data sets.** A set binds curves and fixings to a storage table by uid
  ([ADR 0035](0035-pricing-curve-identity-and-market-data-curve-bindings.md)); the pricing
  routes read it and the curve delete counts its rows.
- **Related tables.** `list_related_meta_tables` lists, and for an Index counts, tables of
  every namespace Markets can see.

Also open:

- Whether rebalance state, calendar events and the event ledger get a publish operation.
  They stay private until a Markets route needs them.
- Orders and trades: the recorder of the execution engine ADR is their publish path.
- What replaces the update pointers on `PortfolioTable` (`portfolio_table_update_uid`,
  `portfolio_weights_table_update_uid`, `signal_weights_table_update_uid`). They name
  MetaTables update records of a bound table, which a publishing node does not have.
- Visibility of a published portfolio per Team. Today every reader of Markets sees it.

## Rejected Alternatives

### Markets reads a producer's table as the caller (issue #98)

It needs a platform call that does not exist, cannot carry a workload, and gives each reader
a grant on each producer. The core would still know its dependents' tables.

### Readers read the producer's table themselves

Markets would hold only a pointer. Every library above ms-markets would fan out across
producers and need a grant from each, and no single place would serve a portfolio.

### Each producer serves its series from its own API

Every producer would deploy the same routes, upgrade in step to keep them identical, and
run a second access policy beside MetaTables' grants.

### Keep the instance and also publish

The rows would be stored twice, and the producer's copy would be a second source of truth.

### Give producers a write role on the core tables

A role on a table covers every row of it, so one producer could change another's rows, and
the grant is again a person's step in each Environment.

## Consequences

- No grant, namespace or command exists for the sake of Markets reading a producer. A
  producer needs only what it already has: access to the Markets API.
- One place serves every registered portfolio, whoever computed it. A library above
  ms-markets reads it with one call and one grant.
- A producer's run depends on the Markets API for its reads and writes of the three series.
  A run that stops is resumed from the series, and a repeated publish writes nothing.
- Published rows are visible to every reader of Markets.
- MetaTables records the Markets workload as the writer of a published row. The producer is
  in Markets' registry-write record and in `managed_by`.
- Producers stop writing the routines of decision 6. A change to them ships once.
- The engine nodes of the three series no longer extend an updater bound to a table. That is
  the largest change of this ADR.
- The work of ADR 0047 decision 5 is reversed: the catalog, the contract check, the
  reconciliation and the catalog-aware deletes.

## Not Verified

- The cost of a run whose series reads and writes go through the API, and of publishing a
  long history. No measurement was made.
- That `bounds` and `last` can replace every use of `update_statistics` in the signal nodes,
  including the per-asset progress `_signal_asset_start_date` reads.
- How Markets names the managing application of a workload caller. MetaTables resolves a
  workload's branch through the platform; Markets has no such code today.
- That no consumer depends on `include=` or on the dataset catalog routes. Their callers
  outside this repository were not searched.

## Implementation Notes

Implemented on 2026-11-20. Revisions `0032_registry_row_managers` (adds `managed_by` to
`Portfolio` and `SignalMetadata`) and `0033_drop_portfolio_dataset_catalog` (drops
`PortfolioDatasetAvailability` and `SignalMetadata.meta_table_uid`).

### Signatures

Series row classes, `msm_portfolios.api` (`src/msm_portfolios/api/series.py`); the SQL is
in `src/msm_portfolios/services/series.py`. A `key` is a `signal_uid` or a
`Portfolio.unique_identifier`.

| Operation | `SignalWeightsSeries` and `PortfolioWeightsSeries` | `PortfolioValuesSeries` |
| --- | --- | --- |
| `publish` | `(key, rows) -> SeriesPublication` | same |
| `window` | `(keys, start=None, end=None, columns=None, assets=None, limit=5000, offset=0, newest_first=False) -> SeriesRows` | `(keys, start=None, end=None, columns=None, limit=5000, offset=0, newest_first=False) -> SeriesRows` |
| `last` | `(keys, at=None, by="key", inclusive=True, assets=None) -> SeriesRows`, `by` is `"key"` or `"asset"` | `(keys, at=None, inclusive=True) -> SeriesRows` |
| `bounds` | `(keys) -> list[SeriesBounds]` | same |
| `assets` | `(key) -> list[str]` | same (the assets of the portfolio's weights) |
| `delete_after` | `(key, time) -> SeriesDeletion` | same |

- `rows` are mappings with `time_index` (timezone-aware) and the table's columns
  (`asset_identifier` and `signal_weight`; the weights' or values' value columns). At most
  `PUBLISH_MAX_ROWS` (10,000) per call; `window` pages hold at most 9,000 rows and a
  `last` answer as many (`READ_MAX_ROWS`); `SeriesRows.next_offset` pages a window.
- `SeriesPublication(key, written, skipped, first_time, last_time, row_count)`,
  `SeriesBounds(key, first_time, last_time, row_count)`, `SeriesDeletion(key, after,
  deleted)`, `SeriesRows(series, rows, next_offset)` with `.frame()`.
- Managers: `Portfolio.assign_manager(uid, managed_by)` and
  `SignalMetadata.assign_manager(uid, managed_by)`; `SignalMetadata.delete(uid)` and
  `SignalMetadata.end(signal_uid)` delete a signal's weights and its row in one
  transaction.

Recipes, `msm_portfolios.recipes` (`src/msm_portfolios/recipes.py`):

- `publish_signal_weights(signal_uid, observations, *, description=None) -> SignalPublication`
  with `observations` a `{datetime: {asset: weight}}` mapping;
  `SignalPublication(signal_uid, written, skipped, assets, first_time, last_time,
  row_count, created_metadata)`.
- `signal_history(signal_uids, *, latest=0) -> SignalHistory(bounds, latest)`.
- `portfolio_history(portfolio_identifier, *, limit=100, offset=0) ->
  PortfolioHistory(portfolio_identifier, count, values, next_offset)`.
- `weights_as_of(portfolio_identifiers, at=None) -> pandas.DataFrame`.
- `portfolio_preflight(portfolio_configuration, *, portfolio_identifier=None) ->
  PortfolioPreflight(ready, reasons, signal_uid, signal_first_time, signal_last_time)`.
- `run_portfolio(portfolio_configuration, *, rebalance_output_table=None, namespace=None,
  portfolio_resolver=None, portfolio_description=None) -> PortfolioRun(portfolio,
  weights, values, first_rebalance)`.
- `end_signal(signal_uid) -> dict`.
- `delete_private_series(tables, *, portfolios=(), calendars=(), accounts=()) ->
  dict[str, int]`.

Operator commands (`src/msm_cli/main.py`). `msm_cli` imports only `msm`, so both run
through core and no command names the portfolio package:

- `msm series publish module:callable [--execute] [--json]`. The callable returns
  `msm_portfolios.series_history.SeriesHistoryPublish(source, series, keys=(), label="")`
  objects. `msm.storage_copies.run_series_publishes` calls each object's
  `run(dry_run=...)` and builds the report, as `run_series_moves` does for moves.
- `msm registry assign-manager --manager <principal> [--portfolio ID]... [--signal UID]...
  [--unmanaged] [--attach module:callable] [--execute] [--json]` runs
  `msm.api.managers.assign_managers`. A row class with a manager registers itself with
  `register_managed_rows` when its package is imported: `Portfolio` in `msm`,
  `SignalMetadata` in `msm_portfolios`. `--attach` names a callable that attaches the
  operator's runtime and imports the packages whose rows are assigned; signals need it.

Both default to a dry run.

### Departures from the text above

- `PortfolioValuesSeries` has no asset column: its `window` and `last` take no `assets`
  or `by`, and its `assets(key)` answers the assets of the portfolio's weights, so all
  three classes offer the six operations. `window` gains `newest_first`, which
  `portfolio_history` and `signal_history` need.
- The engine nodes publish only rows after the key's last stored time
  (`PublishedSeriesNode.publish_frame`, `src/msm_portfolios/series_nodes.py`), as the
  update runner filtered by the latest value before. With decision 3's signal rule this
  means a signal that adds an asset can no longer write that asset's history before the
  signal's last observation; per-asset progress used to allow it. Every signal is now
  held to the signal rules, so a computed signal's `NaN` weight is refused.
- `PortfolioRebalance.dependencies()` no longer names the signal (a published series is
  read, not run); `PortfolioWeights.run()` runs the signal node, then the rebalance. A
  ledger portfolio (`PortfolioEngine`) runs its signal first; `run_portfolio` refuses it.
- `PortfolioAnalyticsConfiguration` loses `portfolio_values_instance`: analytics reads the
  published values, so its update hash changes.
- The nodes no longer fill `Portfolio.*_table_update_uid` (their replacement is not
  decided here); `PortfoliosUpdater` records the signal on the row. The signal-weights
  frame route reads by `Portfolio.signal_uid` and no longer requires
  `signal_weights_table_update_uid`.
- The portfolio delete preflight still passes MetaTables' delete impact of the
  `Portfolio` table through; Markets reads none of the tables it lists. A `RESTRICT`
  refusal is answered 409 with the database's message. A bulk delete and the account
  delete with portfolios report a portfolio the caller does not manage instead of
  deleting it.
- Pricing is out of scope: `provider_owned_table_uid` and `PROVIDER_TABLE_DELETE_GUIDANCE`
  moved unchanged from `msm.storage_instances` into `src/msm_pricing/api/curves.py`, their
  only remaining user.
- `msm.storage_copies.run_series_moves` runs moves in the given order (reversed for a
  rollback), and `finish_move` lost its catalog steps, since only the removed moves used
  them.
- The architecture test (`tests/msm_portfolios/imports/test_markets_reads_only_its_own_tables.py`)
  checks `apps/v1` and the portfolio library's `services`, `api`, `repositories` and
  `recipes`. The Index dataset, formula-source, pricing and related-table code that the
  section above leaves undecided lives in `msm` and `msm_pricing` and is outside it, as
  are the engine nodes and operator commands, which run with a producer's or operator's
  own access.

### Not Verified, settled or confirmed

- Settled: `bounds` and `last` replace `update_statistics` in the three nodes. The
  signal's progress is `SignalWeightsSeries.bounds`, and the per-asset progress of
  `_signal_asset_start_date` is `last(by="asset")`
  (`src/msm_portfolios/time_index/signals/weights.py`); the limit is the one above.
- Settled, with a caveat: Markets names a workload caller's application by its code
  repository branch, as MetaTables does (`metatables.api.backend.integrations.
  platform_principals.workload_branch`). `apps/v1/identity.caller_principal` reads the
  caller's User with `User.get_by_uid` inside `reads_as_caller()`, through a subclass that
  declares `code_repository_branch_uid`; the SDK's `User` (mainsequence 9.0.40) does not
  declare that field, so this relies on the platform returning it on workload rows, as
  MetaTables does. A person, or a workload without a branch, is `user:<uid>`; a requester
  is `user:<requester uid>`. A request without a caller assertion (an API in local mode)
  cannot read as the caller, so its caller is `user:<uid>` with no read (#101); 4.2.0
  answered `500` there instead. A local API writes to a local MetaTables, so that
  principal never meets a hosted `branch:` one, and no local caller is an Organization
  admin, so `msm registry assign-manager` assigns managers locally. The hosted read
  was not run against a live platform. Outside a Markets API
  request (the `runtime` backend in a script or Job) no manager is bound: nothing is
  checked, and a row created that way has no manager until one is assigned.
- Still not verified: the cost of a run through the API and of publishing a long history
  (no measurement), and whether any consumer outside this repository uses `include=` or the
  catalog routes.
