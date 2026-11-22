# Changelog

All notable changes to this project should be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows versioned releases.

## [Unreleased]

Breaking release 5.0.0. It finishes
[ADR 0048](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0048-time-index-vocabulary-rename/):
the pre-3.0 names that 4.0.0 was to remove, and the pre-3.0 UID columns, are gone
([#107](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/107)). It also
stops copying Markets tables into producers' metadata
([#108](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/108)), and
Markets' namespace and table names can no longer be overridden: a sandbox is a separate
database ([#109](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/109)).
Read "Upgrading" at the end of this entry.

### Changed

- **Fewer MetaTables round trips behind an account's target and holdings**
  ([#94](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/94)). Each
  MetaTables request is a round trip, so these requests now join in one select what
  they read one table at a time. Their answers are unchanged.
  - `GET /api/v1/account/{account_uid}/target-positions/`: one request, was five (six
    when the target names assets): the account, its snapshot, the snapshot's rows and
    their portfolios and assets.
  - `POST /api/v1/account/{account_uid}/add-target-positions/`: three, was eight (nine
    when the target names assets): the account with its stored target allocation, the
    write, and the snapshot read back in one select.
  - `GET /api/v1/account/{account_uid}/holdings/`: one, was three.
  - `GET /api/v1/account/{account_uid}/holdings/by-fund/`: two, was seven: the account
    with its holdings set and that set's rows, then its virtual funds with what each
    holds from the set.

  The selects are in `msm.repositories.account_snapshot_reads`.
- **An account delete no longer reads whole tables.** Its foreign keys and its
  per-account lookups had no index to use, so the time grew with every account's
  history. `tests/msm/repositories/test_postgresql_account_delete_volume.py` deletes one
  of 10 accounts that each hold 1,000 holdings sets of 20 positions, their allocations,
  100 target snapshots and 1,000 orders with their trades and events. On PostgreSQL its
  transaction took 54.6 s, 53.2 s of it checking keys once per deleted holdings set, and
  the caller waited 56.8 s, near MetaTables' 60 s deadline. It now takes 0.9 to 1.6 s,
  and the caller waits about 3 to 5 s, most of it MetaTables rebuilding the statistics of
  the seven time-index tables the transaction changed:
  - **Alembic revision 0034** adds 13 non-unique indexes: holdings by
    `(account_uid, time_index)` and `holdings_set_uid`; allocation lines by
    `(account_uid, time_index)`, `holdings_set_uid` and `virtual_fund_uid`;
    virtual-fund holdings by `(virtual_fund_uid, source_account_holdings_set_uid)`,
    `source_account_holdings_set_uid` and `virtual_fund_holdings_set_uid`; orders by
    `(account_identifier, order_time)`, `order_manager_identifier` and
    `order_identifier`; trades by `(account_identifier, trade_time)`; order events by
    `(order_identifier, event_time)`. On a TimescaleDB hypertable each is built chunk by
    chunk, as revision 0031 builds its own.
  - **The transaction has a statement only for the tables the read found rows in**
    (order events whenever the account has orders), so an account with holdings alone
    sends 3 statements instead of 14 and locks 2 time-index tables instead of 7:
    MetaTables rebuilds the statistics of each time-index table a write locks.
    Rows written after the read are still caught by their foreign keys: a `CASCADE`
    key deletes them, a `RESTRICT` key refuses the delete and nothing is deleted.
  - Events of an order identifier another account also uses are found with
    `NOT EXISTS` through the order identifier index, not by reading every other
    account's orders.
- **Breaking:** `msm.repositories.account_deletion.account_delete_statements`,
  `build_delete_account_operation` and `delete_account` (also exported from
  `msm.repositories`), and `msm_portfolios.repositories.account_portfolio_deletion`'s
  `account_with_portfolios_delete_statements` and
  `build_delete_account_with_portfolios_operation`, take `row_counts`, the counts
  `read_account_delete` answers.
- **Breaking: the examples write only to MetaTables' local SQLite runtime**
  ([#109](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/109)). Each
  one that writes, and each example migration provider, selects the local API
  (`configure_local_client()`) before it imports client models. It refuses before its first
  write unless the runtime reports `local_mode` and the SQLite dialect, or when the process
  sends Markets row operations to the Markets API.
- **Breaking: `GET /api/v1/settings/`** no longer answers `runtime.namespace_source` or
  `runtime.auto_register_enabled`, which could only answer `default` and `false`. The
  namespace assumption's `source` is `msm.settings`.

### Removed

- **The pre-3.0 import paths and class names (ADR 0048).** `msm.data_nodes`,
  `msm_portfolios.data_nodes`, `msm_pricing.data_nodes` and
  `msm_portfolios.contrib.prices.data_nodes`, with every submodule, are gone, and so are
  the `*DataNode`, `*DataNodeConfiguration`, `TargetPositionsDataNodeConfiguration`,
  `DiscountCurvesNode` and `FixingRatesNode` names, also from `msm_portfolios`. Import from
  `msm.time_index`, `msm_portfolios.time_index`, `msm_pricing.time_index` and
  `msm_portfolios.contrib.prices.updaters`. `msm._deprecated_imports` is gone.
  `msm.identity` stays, so signal, portfolio and strategy identities do not change.
- **The pre-3.0 UID field names.** Rows no longer carry `holdings_data_node_uid`,
  `source_data_node_uid`, `portfolio_weights_data_node_uid`,
  `signal_weights_data_node_uid`, `portfolio_data_node_uid` or `data_node_uid`, and no HTTP
  response repeats a field under one of them. Payloads, HTTP requests and row writes refuse
  them like any unknown field, and the account and portfolio repository builders no
  longer take them as keyword arguments.
- `PricingMarketDataConfiguration.data_node_uids` and `direct_data_node_uid_for`,
  `PricingMarketDataSetBinding.resolve_data_node_uid`, the `data_node=` argument of
  `VirtualFund.allocate_from_account_holdings_set` and
  `msm.settings.markets_data_node_identifier`. Use `storage_table_uids`,
  `direct_storage_table_uid_for`, `resolve_storage_table_uid`, `updater=` and
  `markets_identifier`.
- **The pre-3.0 UID columns.** Alembic revision 0035 copies each `*_data_node_uid` column
  into the column that replaced it in 3.0.0, makes `storage_table_uid` NOT NULL on
  pricing market-data bindings and drops the six pre-3.0 columns and the `data_node_uid`
  index. Every release since 3.0.0 wrote both columns and read the pre-3.0 one; ms-markets
  now maps only the current one, and `msm.repositories.crud.mirror_renamed_columns`,
  `renamed_column_value`, `renamed_keyword`, `READ_PRE_3_0_COLUMNS` and each model's
  `__renamed_columns__` are gone.
- `msm rename-preflight` and `msm_cli.rename_preflight`, the 3.0 upgrade scanner.
- **Breaking: `MSM_AUTO_REGISTER_NAMESPACE`**
  ([#109](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/109)). It
  renamed Markets' tables for a sandbox in a shared database, could not migrate the schema
  it named, and overrode the namespace a producer declares. ms-markets reads no environment
  for a namespace: `msm.settings.markets_namespace()` answers its argument or
  `mainsequence.markets`. `MSM_AUTO_REGISTER_NAMESPACE_ENV`,
  `markets_auto_register_namespace` and `markets_configured_namespace` are gone, also from
  `msm.base`, with the table-name and version-table suffix and
  `msm_migrations/versions/mainsequence_examples`.
- **Breaking: the override of Markets' own namespace**
  ([#109](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/109)):
  `msm.bootstrap.configure_metatable_namespace`, the `namespace=` argument of
  `start_engine`, `attach_schemas` and `attach_pricing_schemas`, and the `namespace` of
  `MarketsRuntime`, `PricingRuntime`, `MarketsRepositoryContext` and
  `MarketsMetaTableHandle`. It kept the physical tables, so it isolated nothing: writes
  went to Markets' own tables, a migration run with it moved those tables to the other
  namespace in the catalog, and Markets row calls stopped reaching a selected Markets API.
  The `namespace=` of the storage factories and `hash_namespace`, with its `namespace=`
  alias on updaters, are unchanged. The owner decided this on 2026-11-22; it settles what
  the issue lists as its open decision.
- **Breaking:** `msm.storage_instances.markets_reference_table`, which put a Markets table
  into a producer's metadata as a key-only stand-in
  ([#108](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/108)). A key
  to Markets passes the column object instead.

### Fixed

- **A producer's autogenerated migration changes only the producer's tables**
  ([#108](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/108)). The
  instance factories put a key-only copy of each Markets table an instance references into
  the producer's metadata. With `target_metadata=Base.metadata`, as the
  `metatable_migrations` skill shows, the producer's revision then dropped those tables'
  other columns, their indexes and their foreign keys: 24 of 29 operations for one
  interpolated-price and one rebalance-state instance on 4.2.4.
  `configured_time_index_instance`, `configured_contract_instance_storage` and its three
  portfolio factories, `configured_index_values_storage` and
  `configured_interpolated_prices_storage` now point the keys at Markets' own columns and
  add only the instance's table to that metadata. The extension-owned Index example does
  the same instead of copying the Index table. Tables, names, identifiers, storage
  identities and keys are unchanged, so existing tables need no revision.
- **The extension guidance puts a project's tables on the project's own base**
  ([#108](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/108)). Three
  skills, three knowledge pages, tutorial 5 and the custom asset-details example still
  declared them on `MarketsBase`, while the `metatable_migrations` skill targets the
  project's own base. A project following both could not migrate its tables: its upgrade
  failed, or, with no other table on its base, autogenerate wrote a revision that drops
  every table in the database. Targeting `MarketsBase.metadata` instead drops what a newer
  Markets deployment added. All of them now declare the tables on the project's own base
  and key them to Markets by column object, and the skill template's table carries a
  Markets mixin, so
  `msm.start_engine` accepts it. The Index frequency example, which could not autogenerate
  and pointed into Markets' own revisions, has its own namespace, storage app, base and
  migration provider.
- **`msm.start_engine` resolves row classes and keys on a project's own base.** A row
  class over a table on that base was refused, and so was a table keyed to another table
  of that base unless both were listed.
- **The target read and holdings by fund answer the latest snapshot of a long history.**
  Both picked the latest from the first 500 rows of an unordered read, so an account with
  more than 500 target snapshots, or more than 500 holdings sets (one per sync), could be
  answered an older one. The select now chooses it.
- **A target position carries its portfolio's reference whatever the number of
  portfolios.** The reference came from the first 500 portfolios read; a position naming
  another had no `portfolio` and answered its uid as `unique_identifier`.

### Upgrading

- **Move every project that uses accounts, account holdings sets, portfolios or pricing
  market-data bindings to 5.0.0 together with the Markets deployment.** Once its
  `migrate-markets` Job has applied revision 0035 in an Environment, a project on an older
  release fails there on those tables: every release before 5.0.0 reads and writes the
  dropped columns.
- **Replace every pre-3.0 name first.** An old import now raises `ModuleNotFoundError` or
  `ImportError`, and an old field is refused. [Upgrading To 3.0](https://mainsequence-projects.github.io/MainSequenceMarkets/upgrading-to-3/)
  lists each name and its replacement. `getattr(obj, "<old name>", default)` raises
  nothing: it returns the default.
- **Key a producer's own tables to Markets by column object.** On a producer's own base,
  `ForeignKey("ms_markets__asset.uid")` resolved only through a copy of the Markets table
  in that metadata, which the factories no longer make: it now raises
  `NoReferencedTableError`. Use `ForeignKey(AssetTable.__table__.c.uid)` and target that
  base's own metadata.
- **Replace calls of `markets_reference_table`.** A provider module that imports it fails
  to import on 5.0.0. Either target the provider's own base's metadata, as above, or keep
  copying: give `metadata_for_models` the Markets models the provider's keys lead to,
  transitively, and keep the include hook that excludes them. A provider that already
  copies that way keeps working.
- **Move a project's hand-written tables from `MarketsBase` to the project's own base.**
  They need no schema change: names, identifiers, keys and MetaTable uids stay, and the
  next revision is empty. Four things move together: the models, declared on a base whose
  `MetaData` uses `sqlalchemy_naming_convention()` (without it indexes are dropped and
  created); their keys to Markets, passed as column objects; the provider's
  `target_metadata`; and the `base=` given to `build_metatable_model_registry`, which
  silently leaves out models of another base. `msm.start_engine` still accepts models that
  have not moved.
- **Move every sandbox to a separate database before upgrading.** A process that set
  `MSM_AUTO_REGISTER_NAMESPACE` now addresses Markets' real table names, so it reads and
  writes the real tables of whichever database it selects. Use MetaTables' local SQLite
  runtime or another separate database, and see
  [Namespaces and sandboxes](https://mainsequence-projects.github.io/MainSequenceMarkets/concepts/#namespaces-and-sandboxes).
  Suffixed tables and catalog rows an older release left are not touched.
- **Declare a producer's namespace directly.** A module that imports
  `markets_configured_namespace` or `markets_auto_register_namespace` fails to import, so
  a migration provider that does fails its migration Job. Replace
  `markets_configured_namespace("my-provider")` with `"my-provider"` and delete
  `suffix=markets_auto_register_namespace()`. Where the variable was unset, table names,
  identifiers, migration histories and update identities stay the same.
- **Remove `namespace=` from engine startup** and from calls that build a
  `MarketsRepositoryContext` or a `MarketsMetaTableHandle`; they refuse it as an unknown
  argument. Code that read `runtime.namespace` or `context.namespace` uses
  `msm.settings.markets_namespace()` where it needs Markets' namespace.
- **Never apply a producer revision that changes an `ms_markets__` table Markets owns.**
  One autogenerated with an earlier release may hold such drops: delete it and generate it
  again.

## [4.2.3] - 2026-11-21

### Changed

- **Every test that stands in for `msm.bootstrap.resolve_runtime` resolves the models it
  receives** with `resolve_markets_meta_table_models`, as the real runtime does, through
  `tests/support/markets_runtime.serve_runtime`. Before, most stand-ins ignored their
  models, so a row class whose tables the runtime cannot resolve passed every test and
  failed in a deployed API, as the series did in 4.2.0
  ([#103](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/103)).
  `tests/identity/test_runtime_tables_resolve.py` resolves the `__required_tables__` of
  every row class in `msm`, `msm_portfolios` and `msm_pricing`, and every
  `resolve_runtime(models=...)` in their source that writes its models out, whether a
  test reaches it or not.

### Fixed

- **The calendar-link tests no longer fail after the remote-backend bulk test on the same
  worker** ([#105](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/105)).
  `test_bulk_count_and_ordering_run_remotely` replaced `msm.repositories.crud.search_model`
  for the whole test, and `msm.services.asset_calendars`, first imported during it, kept
  the stub for the rest of the process. Each stub now covers only the call that reads it.

## [4.2.2] - 2026-11-20

### Changed

- **CI runs the test suite in parallel** with pytest-xdist (`-n auto --dist worksteal`),
  now in the `dev` extra (#99). Each worker migrates its own SQLite templates, and the
  PostgreSQL fixtures use one database per worker. The dynamic migration provider test
  of the equal-weight example moved to `tests/msm_migrations`: run first in a process, it
  built the Markets migration provider under the example namespace, and every later SQLite
  database in that process lacked the Markets tables. The testing page describes parallel
  runs, `-n 4` for local scoped runs included.

### Fixed

- **The three published series work through a Markets API and after `start_engine`**
  ([#103](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/103)).
  Since 4.2.0, every `SignalWeightsSeries`, `PortfolioWeightsSeries` and
  `PortfolioValuesSeries` operation, and `SignalMetadata.delete` and `end`, failed with
  `ValueError: Unknown markets MetaTable model 'PortfolioWeightsStorage'` (or
  `SignalWeightsStorage`, `PortfoliosStorage`). They named their storage tables by
  string, and the runtime resolves names only for the tables of `msm`. They now name
  the table classes, as every other row class does. The tests resolve each operation's
  tables as the runtime does, instead of skipping that step.

## [4.2.1] - 2026-11-20

### Added

- **`MarketsClient.delete_portfolio(uid)` and `MarketsClient.bulk_delete_portfolios(uids)`**
  call `DELETE /api/v1/portfolio/{uid}/` and `POST /api/v1/portfolio/bulk-delete/`, in place
  of the refused `Portfolio.delete`. They return `PortfolioDeleteResponse` and
  `PortfolioBulkDeleteResponse`, which moved from the API app's schemas into
  `msm.api.portfolios`. `delete_portfolio` raises `LookupError` for a missing portfolio;
  both raise `MarketsConflictError` when a reference refuses the delete, and
  `bulk_delete_portfolios` also when a selected portfolio is missing.

### Changed

- **`import msm` loads only the package's constants and version** (157 modules instead
  of 1,531). `msm.start_engine` is imported on first use, and with it MetaTables,
  SQLAlchemy, pandas and the Main Sequence SDK; `msm.start_engine(...)` and
  `from msm import start_engine` work as before. The SDK now sets up its logging when
  `start_engine` or a Markets model is first imported, not at `import msm`.
- The test suite checks each behaviour once (see the testing page): duplicated
  PostgreSQL, SQLite and app tests are removed, the calendar re-sync Job tests check the
  Job's wiring, and only `tests/apps` loads the SDK's server modules (#99).

### Fixed

- **A statement MetaTables rejects as invalid answers `500`, not `502`**
  ([#87](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/87)). When
  MetaTables refuses a statement the Markets API compiled, with
  `compiled_sql_database_error` or a code of its checks before the statement runs
  (`invalid_sql`, `empty_sql`, `invalid_sql_parameters`, ...), the fault is the Markets
  API's and a retry fails the same way. The API answers `500` with `error_type`
  `InvalidStatementError`, a `detail` that says so and keeps MetaTables' reason, and
  `upstream_status`; `msm.client` raises the new `MarketsInvalidStatementError`
  (`MarketsApiError`, not retryable) for it. MetaTables gives no SQLSTATE, so a
  statement that breaks a constraint answers `500` too. Other refusals (permissions, a
  missing table, a conflict) still answer `502` and failures `503`, as
  `MarketsUpstreamError`.
- **A Markets API in local mode records and checks managers again**
  ([#101](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/101)). In
  4.2.0 it answered `500` to every operation that needs the acting manager: creating or
  upserting a portfolio or signal, `publish`, `delete_after`, deleting a portfolio or
  signal, and `assign_manager`. A local request carries no caller assertion, and
  `caller_principal` read the caller's User row as the caller, which the SDK allows only
  with one. A caller without an assertion is now `user:<uid>`, with no directory read.
  On a hosted request, a failed read of the caller still raises.

## [4.2.0] - 2026-11-20

This release breaks every producer of signals and portfolios
([ADR 0060](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0060-producers-publish-markets-reads-only-its-own-tables/)).

### Added

- `SignalWeightsSeries` (`signal-weights`), `PortfolioWeightsSeries` (`portfolio-weights`)
  and `PortfolioValuesSeries` (`portfolio-values`) in `msm_portfolios.api`, with `publish`,
  `window`, `last`, `bounds`, `assets` and `delete_after`, under the `runtime` backend and
  as `POST /api/v1/rows/{resource}/{operation}/`. `publish` writes one key's rows in one
  transaction: an equal row is skipped and a different one refuses the call. Signal
  weights keep `ApplicationWeights`' rules, now enforced by Markets for every signal.
- `msm_portfolios.recipes`: `publish_signal_weights`, `signal_history`,
  `portfolio_history`, `weights_as_of`, `portfolio_preflight`, `run_portfolio`,
  `end_signal` and `delete_private_series`.
- `Portfolio.managed_by` and `SignalMetadata.managed_by` (revision 0032): the principal of
  the call that created the row, `branch:<uid>` for a workload of a code repository branch
  and `user:<uid>` otherwise. Through the Markets API only the manager publishes to a row,
  restates it or deletes it (403 otherwise); `assign_manager` is for Organization admins.
  Rows created before have no manager and accept no publish until one is assigned.
- `msm series publish` publishes the history held in an application's own table, key by
  key, and compares the bounds; `msm registry assign-manager` assigns managers. Both
  default to a dry run. The `msm` command imports only `msm`: the publishes come from an
  operator callable, and `--attach module:callable` loads the package that serves signals.
- `SignalMetadata.delete(uid)` and `SignalMetadata.end(signal_uid)` delete a signal's
  weights and its row in one transaction.
- The skill `platform/producer_boundary` teaches producers the boundary.

### Changed

- **Breaking: Markets reads and writes only its own tables.** `SignalWeights` and its
  subclasses, `PortfolioWeights` and `PortfoliosUpdater` are no longer
  `TimeIndexTableUpdater`s: they publish through the series and take no `output_table=`
  (`PortfoliosUpdater` and `PortfolioWeights` keep `rebalance_output_table=`). Their
  progress is the published series. `PortfoliosUpdater.run` no longer takes
  `override_update_stats` and no longer fills the `*_table_update_uid` pointers of the
  `Portfolio` row.
- **Breaking:** `PortfolioRebalance` no longer runs the signal; `PortfolioWeights` runs it.
  `PortfolioAnalyticsConfiguration` loses `portfolio_values_instance` and reads the
  published values, so its update hash changes.
- **Breaking:** the portfolio delete no longer reads other applications' tables; a
  `RESTRICT` key that refuses it is answered 409 with the database's message. The signal
  delete is one transaction.
- `GET /api/v1/portfolio/{uid}/signals_weights/` reads by `Portfolio.signal_uid` alone.
- **Requires MetaTables 0.1.71 or later.** `mainsequence-metatable>=0.1.71,<0.2` (was
  `>=0.1.66`), for two of its fixes:
  - **0.1.69 rebuilds a table's update statistics after a compiled-SQL write.** The
    portfolio and account deletes are statement lists of plain deletes. MetaTables rebuilds
    the stored update statistics of each time-index table such a write changes, so a
    portfolio, or an account's orders, trades and order events, written again under a
    deleted one's identifier do not resume from its last time index
    ([MetaTables#117](https://github.com/mainsequence-projects/MetaTables/issues/117)).
  - **0.1.71 binds SQLite statements by position.** SQLite numbers each named parameter by
    searching the names before it, so preparing a statement took time quadratic in its
    values. On SQLite, `bulk_upsert_model` sends 7,000 `Asset` rows in two batches, and
    the first batch's statements bind up to 26,212 values. Its three-statement transaction
    needed 15.6 s of CPU and ran past MetaTables' 15 s deadline; with 0.1.71 it takes
    0.08 s ([issue 97](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/97),
    [MetaTables#121](https://github.com/mainsequence-projects/MetaTables/issues/121)).

  The lock and `requirements.txt`, which hosted images install, select 0.1.71; no other
  locked package changes.
- **The six other portfolio datasets have an index that leads with the portfolio**
  (Alembic revision 0031). `PortfoliosStorage`, `PortfolioRebalanceStateStorage`,
  `PortfolioAnalyticsStorage`, `PortfolioEventLedgerStorage`, `PortfolioStateStorage` and
  `PortfolioCashFlowsStorage` gain `(portfolio_identifier, time_index)`, the index revision
  0026 gave `PortfolioWeightsStorage`
  ([issue 96](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/96)).
  Counting, reading and deleting one portfolio's rows reads that portfolio's rows instead
  of the whole table, and so does the `RESTRICT` check when a portfolio row is deleted.
  Apply the migration. On an ordinary table it builds the index in the upgrade's
  transaction, during which writes to the table wait (2 to 3 s for tables of 6.3 million
  rows). On a TimescaleDB DataSource, where these tables are hypertables, it builds each
  index one chunk per transaction (`timescaledb.transaction_per_chunk`), outside the
  upgrade's transaction, so it holds a few locks at a time whatever the number of chunks:
  on 8,030 chunks across the six tables, at PostgreSQL's default
  `max_locks_per_transaction = 64`, it took 32 s and held at most 22 locks, where one
  transaction ran out of shared memory. An upgrade stopped part way can be run again: it
  finishes or rebuilds what it left. Dropping a hypertable's index, which the downgrade and
  the upgrade after an interrupted build do, takes about two locks per chunk of that table
  in one transaction, because TimescaleDB 2.22 opens every chunk to drop it (4,010 locks
  for 2,005 chunks). Instances built with
  `configured_portfolio_rebalance_state_storage` and
  `configured_portfolio_event_ledger_storage` declare the same index; **a provider adds it
  to its existing instances in a revision of its own**.

### Removed

- **Breaking: `Portfolio.delete`.** It raises `MarketsOperationUnsupported` under both
  backends and deletes nothing, and `POST /api/v1/rows/portfolio/delete/` answers `501`
  with the same text. Through `msm.client` it ran the portfolio routes' delete; under the
  runtime backend it deleted only the portfolio row, none of its seven datasets, and the
  first `RESTRICT` key from any of them refused it. Core `msm` cannot run the full delete,
  which lives in `msm_portfolios`
  ([ADR 0019](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0019-msm-portfolios-package-boundary/)).
  Delete a portfolio through `DELETE /api/v1/portfolio/{uid}/` or
  `POST /api/v1/portfolio/bulk-delete/`
  ([ADR 0049](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0049-portfolio-lifecycle-and-account-history/)).
- **`msm.services.delete_portfolio`, `msm.repositories.delete_portfolio` and
  `msm.repositories.build_delete_portfolio_operation`**, unused one-row portfolio deletes.
- **Breaking:** `PortfolioDatasetAvailabilityTable` and `SignalMetadata.meta_table_uid`
  (revision 0033), `PortfolioDatasets`, `msm_portfolios.services.portfolio_datasets`, the
  routes `registerPortfolioDatasets`, `getPortfolioDatasets` and
  `reconcilePortfolioDatasets`, the catalog reads of `msm_portfolios.services.portfolio_reads`,
  `PortfolioDatasetOwnershipError`, `SignalDatasetOwnershipError`, `retained_datasets`,
  the foreign-table checks of the portfolio delete, `include=` and `includes` on the
  account, asset, portfolio and Index by-uid lookups, `PortfolioSeriesMove`,
  `SignalSeriesMove`, `configured_signal_weights_storage`,
  `configured_portfolio_weights_storage` and `configured_portfolios_storage`.
  `msm.storage_instances` no longer exports `provider_owned_table_uid` or
  `PROVIDER_TABLE_DELETE_GUIDANCE`.

### Fixed

- **Breaking: a portfolio is deleted with all its datasets in one transaction, or not at
  all.** `DELETE /api/v1/portfolio/{uid}/`, `POST /api/v1/portfolio/bulk-delete/` and the
  remote `POST /api/v1/rows/portfolio/delete/` deleted the portfolio's weights and values
  with two `delete_after_date` requests and then the portfolio row. A `RESTRICT` key from
  its rebalance state, analytics, event ledger, state or cash flows, or from another
  application's instance, then refused the row with a `409` that the preflight had not
  predicted, and the portfolio survived without its weights and values
  ([issue 93](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/93)). The
  delete now removes the portfolio's rows in all seven datasets and then the row as one
  MetaTables statement list, in one transaction; the last statement is guarded, so a
  portfolio that vanished in between answers `404` and one renamed in between `409`.
  The counting read and the transaction run with MetaTables' longest deadline, 60 s,
  instead of its 15 s default: deleting a portfolio with ten years of daily weights on
  500 assets took 12 to 19 s on PostgreSQL 16 on a busy workstation.
  - Before anything is sent, it is refused while virtual funds or account target rows
    name the portfolio (ADR 0049), or while a table of another application whose
    `RESTRICT` key references the portfolio holds rows of it or cannot be checked. Those
    tables come from MetaTables' delete impact and from the catalog's instances; each gets
    one read-only count. Markets never deletes their rows: they used to stay in place,
    listed in `retained_datasets`, and now refuse the delete, as for curves (issue 59).
  - The `409` names the table and key that refused, or carries the database's message,
    which on PostgreSQL names the constraint.
  - `POST /api/v1/portfolio/bulk-delete/preflight/` runs the same checks, with one read
    for the whole selection, and returns `portfolios`: each portfolio's `row_counts` per
    dataset and its `blockers`.
  - Responses: `deleted_rows`, the rows per dataset, replaces `deleted_weights_count`,
    `deleted_values_count` and `retained_datasets`, and the response names the deleted
    portfolio's `uid` and `unique_identifier`. The bulk delete returns `deleted`, one entry
    per portfolio, and `failed[].detail` instead of `failed[].reason`, as the account bulk
    delete does. Each portfolio is deleted in its own transaction.
  - The Markets API binds the five other dataset tables at startup.
- **Breaking: an account delete sends MetaTables one read and one transaction, and can
  delete the account's portfolios with it.** Deleting an account through the Markets API
  took minutes: each step was its own MetaTables request, about 2 s per statement and
  about 14 s for each delete impact, and the delete read the account, counted its rows
  and asked for the impact
  ([issue 91](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/91),
  [ADR 0050](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0050-account-deletion/)).
  - One read answers whether the account exists, its rows per table and the rows of
    other accounts that block it; one transaction deletes it. The delete no longer asks
    MetaTables for its impact: only `POST /api/v1/account/bulk-delete/preflight/` does,
    and `POST /api/v1/account/bulk-delete/` asks at most once, in its preflight. The
    read and the transaction run with MetaTables' longest deadline, 60 s.
  - `delete_portfolios`, off by default, as a query parameter of
    `DELETE /api/v1/account/{uid}/` and as an option of the account bulk-delete action,
    which its discovery now advertises: the same transaction also deletes, with all
    their data, the portfolios that the account's virtual funds or target rows name and
    nothing else uses. A portfolio stays when another account's virtual fund or target
    rows name it, or when its catalog places its values or weights in another
    application's table. When another application's table holds a portfolio's rows
    under a `RESTRICT` key, the transaction deletes nothing and a second one deletes the
    account alone. The response lists `deleted_portfolios`, with their `deleted_rows`
    per dataset, and `kept_portfolios`, with the `reason`; the preflight lists
    `accounts[].portfolios` and `accounts[].kept_portfolios`, and a warning for each.
  - In Python, `msm_portfolios.services.delete_account_with_portfolios`,
    `bulk_delete_accounts_with_portfolios` and their preflights
    (`preflight_account_delete_with_portfolios`,
    `preflight_bulk_delete_accounts_with_portfolios`) do the same with a runtime's
    context; `Account.delete` and `Account.bulk_delete` delete the account alone. The
    portfolio package owns this delete: core `msm` does not import it (ADR 0019), so it
    composes the account read and statements `msm.repositories.account_deletion`
    exposes with its own.
  - Breaking: the responses of `DELETE /api/v1/account/{uid}/` and
    `POST /api/v1/account/bulk-delete/`, and of `Account.delete` and
    `Account.bulk_delete`, no longer carry `other_namespace_cascades`; the preflight
    still reports it with `other_namespace_restricts`. A `409` carries the database's
    message without the list of tables from the impact.
  - Breaking for library code: `msm.repositories.account_deletion.read_account_delete`
    and `build_read_account_delete_operation` replace `count_account_delete_rows` and
    `build_count_account_delete_rows_operation`.
  - `msm.services.table_impact.delete_rows_impact` reuses MetaTables' answer for the same
    table for five minutes (`IMPACT_CACHE_SECONDS`), for every bulk-delete preflight;
    `clear_delete_rows_impact_cache` forgets it.
  - `msm.api.http.build_bulk_delete_action` takes `options`, `explicit_uuid_selection`
    accepts the options an action declares, and `bulk_action_option_values` reads them;
    an undeclared option or a value of the wrong type answers `400`.
- **A portfolio delete's counting read no longer reads whole tables, and the bulk delete
  counts its selection once.** The read counted each dataset with a subquery per selected
  portfolio, and six of the seven dataset tables had no index that leads with
  `portfolio_identifier`, so each count read its table in full, once per portfolio; the
  account delete's read with `delete_portfolios` did the same, and
  `POST /api/v1/portfolio/bulk-delete/` ran the read twice
  ([issue 96](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/96)).
  - Revision 0031 gives those six tables the index (see Changed), so each count reads only
    its portfolio's rows. For five portfolios of 2,520 days on 500 assets the read took
    0.43 s instead of 1.51 s, and for a portfolio with 0.4 % of the rows 9 ms instead of
    0.27 s (PostgreSQL 17, pages in memory; ADR 0049's issue 96 note has the rest).
  - `POST /api/v1/portfolio/bulk-delete/` counts its selection once: it deletes by its
    preflight's plan (`msm_portfolios.services.plan_portfolio_deletes`, which returns a
    `PortfolioDeletePlan`, and `bulk_delete_portfolio_records(..., plan=...)`). A
    portfolio referenced after that read is still refused by its guarded statement or by
    a `RESTRICT` key.


## [4.1.0] - 2026-11-19

### Changed

- **Breaking: a trade happens only at a price observed at the trade's time.** A rebalance
  was recorded at the signal's own time, weekends, nights and holidays included, and no
  strategy checked that a price was observed when it traded ([issue 89](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/89), [ADR 0058](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0058-trade-at-the-next-observed-price/)). Prices are
  stamped at the moment they were observed. For every rebalance strategy:
  - the earliest moment is the strategy's moment (the signal for `ImmediateSignal`, the
    selected open or close for `CalendarEventSignal`) while the portfolio's calendar is in
    session (`market_open <= t <= market_close`), otherwise the calendar's next
    `market_open`; on `CRYPTO_24_7` every moment is in session;
  - each asset trades at the first row of the portfolio's `valuation_source_instance` at or
    after the earliest moment, strictly after the signal that set its target, and inside a
    session (`market_open < time_index <= market_close`; a bar stamped at an open is not),
    at that row's `valuation_column`;
  - rows with `interpolated=True` are never a trade price, and `open`, `high`, `low` and
    `vwap` are refused as fill columns: a fill price is a close or a mark;
  - assets fill independently, the unfilled part is cash, a newer target replaces the target
    of assets not filled yet, and a missing price makes the trade wait instead of raising.

  Strategies with their own bars (`TimeWeighted`, `VolumeParticipation`,
  `LiquidityConstrained`, `TrailingAverageDailyVolumeParticipation`) keep trading at them
  under the same conditions: a bar trades only toward a signal observed strictly before it,
  and an asset moves only at its own observed bar.
- **Breaking: every portfolio gets a new identity.** `RebalanceStrategyBase` has a
  hash-bearing `fill_rule` (`"next_observed_price"`), so every portfolio configuration hash
  and strategy revision changes. Retire existing portfolios and keep them as history; do not
  delete them. There is no optional or legacy mode.
- **Breaking: every `ImmediateSignal` needs the portfolio's calendar.**
  `calendar_events_instance` and `calendar_identifier` are required, and `session_label`
  defaults to `"regular"`; `CalendarEventSignal` inherits them. The calendar dependency must
  publish both `market_open` and `market_close`: one configured or published with one event
  type is refused, also for a `CalendarEventSignal`. `PortfoliosUpdater` refuses an
  `ImmediateSignal` whose `calendar_identifier` is not the portfolio's `calendar_uid`
  (ADR 0056).
- **Breaking: the position ledger books the fills the rebalance recorded.** `PortfolioEngine`
  depends on `PortfolioRebalance` and books exactly its fills: time, asset and price. It no
  longer builds its own schedule or requires its own mark for a fill. A rebalance fixes every
  asset's share count once, at its decision: target weight x NAV / price, with the NAV and
  the prices last observed strictly before its earliest moment, however old; each asset
  fills that count at its own next observed price, and the weight it reaches comes from the
  fill. Strategies with their own bars are sized at each fill.
  `PortfolioEngineConfiguration.signal_weights_instance`
  is replaced by `portfolio_rebalance_instance`, and
  `PortfolioEngine.calculate_backtest` takes `rebalance_state` instead of
  `signal_observations` and `rebalance_inputs`. A new target that repeats an asset's weight
  still fills, and the ledger resizes the position at that fill; it no longer re-sizes
  positions at events where the rebalance recorded nothing. Each fill carries its price's
  time (`AssetExecution.price_time_index`) and is booked at that time; a price observed at
  another time is refused.
- **Breaking: a held asset is valued at its last observed price, however old.** In the
  ledger and in the weights path, an observation older than `maximum_staleness` is used and
  marked stale instead of failing the run; only a held asset with no observed price at all
  raises. FX rates follow the same rule. In the ledger a stale price or rate carries
  `"stale": "true"` in `valuation_references`, is listed in
  `ValuationResult.stale_sources`, and is named in the `valuation_summary` row's
  `extension_payload`. In the weights path the portfolio value row has the new
  `valuation_stale` column set, and a warning names the holdings. Refusing a stale price
  stays an option of the valuation policy: `ValuationAlignmentPolicy.fail_on_missing_values`
  now defaults to `False`, and `MarketPriceValuationModel.fail_on_missing_values` is new.
  `TargetWeightExecutionModel.maximum_staleness` is removed.
- **Breaking: `PortfoliosStorage` has a `valuation_stale` column** (Alembic revision 0029,
  nullable). Apply the migration. A provider with its own `PortfoliosTS` instances adds the
  column in a revision of its own; dataset registration refuses an instance without it.
- **Breaking: the execution choices are a policy; its defaults are the owner's decisions.**
  `ImmediateSignal.execution_policy` (`ExecutionPolicy`, inherited by `CalendarEventSignal`)
  is hash-bearing: `sizing` (`"at_decision"`), `negative_cash` (`"not_allowed"`, or
  `"fraction_of_nav"`, or `"fixed_amount"` for a portfolio with a ledger) with its
  `negative_cash_limit`, `sells_before_buys` (`True`), `cash_shortfall_allocation` (`"pro_rata"`),
  `uncovered_buys` (`"cut_and_cancel"`) and `calendar_gating` (`"portfolio_calendar"`).
  `PortfolioRebalance` runs it on a book of shares and cash: sells at an instant pay its
  buys; a buy cash cannot cover fills what it can and waits for the rebalance's pending
  sells; once none is pending its remainder is cancelled with the reason
  `insufficient_cash`; buys short of cash at one instant fill the same fraction. The facts
  (observed price strictly after the signal, at or after the earliest moment, in session)
  are not settings. A fixed amount is refused without `accounting_configuration`.
- **Breaking: the portfolio's currency and FX source are on the build configuration**
  ([ADR 0059](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0059-portfolio-currency-fx-and-drifting-weights/)).
  `PortfolioBuildConfiguration.valuation_asset_identifier` is required and replaces
  `PortfolioAccountingConfiguration.valuation_asset_identifier`;
  `PortfolioEngine.calculate_backtest` takes it as an argument. The optional
  `fx_source_instance` is the portfolio's one FX source, read by `PortfolioRebalance`, the
  ledger and the weights path; `MarketPriceValuationModel.fx_source` is removed. With an FX
  source the valuation source must have `price_asset_identifier`; without one, a price
  quoted in another currency is refused. Prices are converted at the last observed rate,
  and the ledger counts cash in every currency in the portfolio's currency.
- **Breaking: weights drift in the weights-only path.** `PortfoliosUpdater` values a
  portfolio whose strategy records a rebalance book from its shares and cash, so weights
  drift with prices between rebalances instead of returning to target at every price.
  `PortfolioWeightsStorage` has `held_shares` and `book_cash` columns (Alembic revision
  0030, nullable); apply the migration. A provider with its own `PortfolioWeightsTS`
  instances adds them in a revision of its own. Weights without a book (and the strategies
  with their own bars, until issue 90) are valued from constant weights.
- **`PortfolioRebalance` reads the portfolio's valuation source** for strategies without
  bars of its own, and declares it as the `valuation_source` dependency. For those
  strategies it writes a rebalance-state row only when an asset's order steps, at the
  price's time, with `event_source` `"valuation_source"`: `complete`, `partial`, or
  `cancelled` (a cancellation that filled nothing has no price). `weight_after` is the
  weight the fill reached, and `strategy_state` records the decision, the order and the
  book's shares and cash, from which the next run resumes. There are no `pending` or
  `superseded` rows. The state before a window is the latest row of every asset, read
  through the update statistics. It values the book with all the source's rows, its last
  row before the window included.
- **The ledger books the filled part of its own order.** Each recorded fill trades the same
  fraction of the ledger's open order as of the book's, rounded down to the lot step, and a
  cancellation is recorded as execution progress with its reason. The ledger cuts only its
  own shortfalls (lot rounding, execution costs, lifecycle cash): buys settled in the
  valuation currency share what is left down to the policy's limit, pro rata, and the
  progress record carries `ledger_cut`. `PortfolioWeights` and `recorded_fills` keep
  `cancelled` rows, which can carry a partial fill.
- **A waiting asset looks for its price from its own earliest moment.** A slow asset's bar
  that arrives after another asset's later fill was recorded is still its next observed
  price, so `PortfolioRebalance` reads prices from the newest recorded rebalance's earliest
  moment rather than from the window start. There is no completeness watermark, and a
  signal's `time_index` is used as the moment it was known. A fill recorded this way is
  earlier than rows already written: `PortfolioWeights` does not project it, and the
  position ledger's replay refuses the changed history.
- **A signal stamped at the last fill time is no longer lost.** An incremental window starts
  1 ns after its last row, and the seed reads dropped that nanosecond. They now select rows
  at or before its microsecond floor, and a moment at the last fill time is selected again.
- **An update that cannot be written is refused before it is sent.** `update_model` raises
  `ValueError` naming the table and the row when its values name no column, or set a
  `NOT NULL` column to `NULL`. The rows route and the calendar, portfolio-group and
  asset-category `PATCH` routes answer it with `400`; it reached the database as invalid SQL
  and came back as `502` before.
- **An explicit `null` in an update payload clears the column.** `Row.update` payloads and
  the `PATCH` routes send only the fields a caller set; a field set to `null` was ignored
  before and now clears a nullable column. `PATCH /asset-category/{uid}/` with
  `"description": null` now clears the description, as its schema documents, and
  `"display_name": null` answers `400` instead of storing the text `None`.
- **The repository update helpers state what `None` means.** `build_update_asset_category_operation`
  and `build_update_portfolio_group_operation` take the fields to write as keywords and write
  `None` as `NULL`. The account-group, asset, portfolio-metadata, signal-metadata and
  rebalance-strategy-metadata helpers leave a field passed as `None` unchanged; a call that
  leaves every field unchanged raises `ValueError`.

### Added

- **Reading the state in force before a window.**
  `RebalanceStrategyBase.dependency_seed_coordinates(name)` names coordinates whose latest
  row strictly before the dependency window is read too, by `read_rebalance_input`.
  `ImmediateSignal` uses it for the latest open and close, so an incremental run that starts
  mid-session knows the market is open.
- **`earliest_moment`, `in_session`, `observed_prices`, `valuation_prices`,
  `require_observed_price_column`, `ExecutionPolicy` and `PriceConversion`** in
  `msm_portfolios.rebalance_strategy`, and `recorded_fills` in
  `msm_portfolios.time_index.portfolios.accounting`.
- **[ADR 0058](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0058-trade-at-the-next-observed-price/)**
  records the rule. It amends ADR 0040's immediate mode and extends ADR 0056, decision 7.

### Removed

- **Breaking:** `RebalanceStrategyBase.build_accounting_schedule`,
  `RebalanceStrategyBase.simulate_accounting_event` (replaced by
  `simulate_recorded_fills`), `RebalanceStrategyBase.target_selection_mode`, and
  `AccountingRebalanceEvent`.

### Fixed

- **`portfolio-datasets/unregister_signal` answered `502` for every bound signal.**
  `update_model` dropped each `None` it was given, so clearing
  `SignalMetadata.meta_table_uid` compiled to `UPDATE … SET WHERE …`, which PostgreSQL
  refused. `unregister_portfolio_datasets` failed the same way when it unbound a signal.
  `update_model` now writes exactly the values it is given: `None` sets the column to SQL
  `NULL`, JSON columns included
  ([issue 87](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/87)).

## [4.0.1] - 2026-11-17

### Added

- **One call links many assets to their trading calendar.**
  `AssetCalendar.link_many(asset_identifiers, calendar_identifier="NYSE")` names assets by
  `unique_identifier` and the calendar by `calendar_identifier` or `calendar_uid`, and writes
  the links in one transaction. It returns what happened to each identifier: `linked`,
  `moved`, `unchanged`, `kept` (with `relink=False`) and `unknown`. An identifier no asset
  has is reported, not refused. Linking was one `AssetCalendar.upsert` for each asset, or
  `upsert_many` rows built from asset uids
  ([ADR 0057](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0057-asset-calendar-links-in-bulk-and-at-registration/)).
- **A registration may name the asset's trading calendar.** Every payload that writes an
  asset takes an optional `calendar_identifier` or `calendar_uid`: `Asset.create`,
  `Asset.upsert`, `Asset.upsert_many`, `CurrencySpot.upsert` and `upsert_many`,
  `Bond.upsert`, `Future.upsert` and `upsert_many`. A payload that names a calendar links
  its asset, moving it from another calendar; one that names none leaves the link as it is.
  The links of a call are written after its assets, in one transaction. A call that names
  no calendar reads and writes nothing more than before.
- **An account registration links assets in its one transaction.** An asset of
  `AccountRegistrationRequest.assets` may carry `calendar_identifier`. An asset with no
  trading calendar is linked in the registration's transaction; an asset that has one
  keeps it, so a connector's sync does not undo a link someone moved. A calendar that does
  not exist refuses the registration before anything is written. `written` gains
  `asset_calendars`.
- **`AssetCalendar.unlinked_assets(asset_type=None, limit=500, offset=0)`** lists the assets
  that have no trading calendar: the ones a price update refuses.
- **`AssetCalendar.delete` works under the remote backend.** The class defines its own
  `delete`, which removes the link of one asset. It answered `501` before.

### Changed

- **Deleting a calendar in use is refused with a reason.** A calendar that is the trading
  calendar of an asset, or the calendar of a portfolio, is not deleted:
  `DELETE /api/v1/calendar/{uid}/` answers `409` with the number of assets and portfolios
  that hold it, and the remote row call raises `MarketsConflictError`. The database refused
  the delete before, and the caller saw its error.

## [4.0.0] - 2026-11-17

This release changes how calendars are stored
([ADR 0055](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0055-calendars-as-rules-and-exceptions/)). It removes three tables,
their row classes and sixteen routes, and changes the arguments of
`Calendar.create_from_pandas_calendar`. Read "Upgrading" at the end of this entry.

It also links each asset to a stored calendar
([ADR 0056](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0056-asset-trading-calendar-link/)). Price bars are computed from
that calendar and no longer from a calendar name typed into the asset scope. **After the
upgrade no price update runs until its assets are linked.**

### Changed

- **A calendar is stored as session rules and exceptions, not as one row per date.**
  `CalendarSessionRule` is the regular week of a session from a date on: the weekdays it
  runs and its local open and close. `CalendarException` is one dated departure from it:
  `CLOSED`, `EARLY_CLOSE`, `LATE_OPEN` or `OPEN`. Dates and sessions are computed from them.
  NYSE from 2017-12-02 to 2027-11-18 was 3,639 date rows and 2,503 session rows; it is 1 rule
  and 116 exceptions. Local times are stored as `HH:MM:SS` text in the calendar's timezone and
  become UTC instants when they are read, so a change of daylight-saving law no longer leaves
  stored sessions wrong.
- **`Calendar.create_from_pandas_calendar` writes a calendar once, to the last date the
  library can answer for.** Its first two arguments are the library's calendar and the name
  of the stored one: `Calendar.create_from_pandas_calendar("NYSE", "CustomNYSE")`. The stored
  name defaults to the library's. It no longer takes `valid_to` or `materialize`, and
  `valid_from` is optional and defaults to 1990-01-01. The range ends where the library's
  holiday rules end, 2200-12-31 for most calendars; a calendar with no holidays, such as
  `24/7`, has no last date. Nobody extends a calendar as time passes. The header, the rules
  and the exceptions are written in one transaction, so a calendar cannot claim a range its
  rows do not cover.
- **Calling it again writes only what changed, and keeps a user's rows.** The adapter
  compares what the installed library says with what is stored, deletes the exceptions the
  library no longer has and inserts the ones it learned. Exceptions with `source="user"` are
  never read or written by it.
- **`Calendar.valid_from` and `Calendar.valid_to` are enforced.** A read of dates or sessions
  outside them raises `CalendarRangeError`. Before, nothing compared a requested date with
  the range, and a calendar whose rows had run out produced no session and no error. Both
  columns are now nullable; a null bound is not checked.
- **`PortfolioCalendarEvents` fails when its window ends after the calendar's `valid_to`**,
  where it published nothing. Its first run starts at the calendar's `valid_from` when that
  is later than the updater's own start.
- **A stored calendar is found by its `unique_identifier` only.**
  `resolve_rebalance_calendar` no longer looks a calendar up by `source_identifier` when the
  first lookup finds none: several stored calendars can come from one library calendar.
- **`PersistedCalendarSchedule.schedule` is one computed read.** It no longer reads sessions
  in two-year windows.
- **`is_weekend` follows the calendar's own week.** It is true on a weekday no session rule
  runs on. It was Saturday and Sunday for every calendar, so a 24/7 calendar reported a
  weekend it does not have.
- **`GET /calendar/{uid}/dates/` and `GET /calendar/{uid}/sessions/` return a computed
  window.** `start_date` and `end_date` are required; a request without them answers `422`.
  A window outside the calendar's range answers `400` with the range in the message.
  `limit`, `offset` and the flag filters work as before. The items have no `uid`.

### Added

- **`AssetCalendar` links an asset to its trading calendar.** It is a one-to-one detail table
  of `Asset`, with a row class of the same name:
  `AssetCalendar.upsert(asset_uid=..., calendar_uid=...)`. The linked `Calendar` decides
  which price bars the asset has. A calendar cannot be deleted while an asset is linked to
  it; deleting an asset removes its link.
- **`resolve_asset_schedules`** in `msm_portfolios.services.calendars` returns the stored
  calendar of each asset as a schedule, in three reads for any number of assets.
- **`CalendarSessionRule` and `CalendarException` row classes**, with
  `/calendar/{uid}/rules/` and `/calendar/{uid}/exceptions/` routes: list, create,
  bulk-upsert, get, update and delete. Both row classes can be deleted under the remote
  backend. An exception written through them has `source="user"`.
  A date that has any `user` exception is computed from its `user` exceptions alone, so a
  correction made by hand wins for its date and survives the adapter. To cancel a closure the
  library has, write an `OPEN` exception for that date.
- **`Calendar.sessions`, `Calendar.dates` and `Calendar.is_business_day`** compute a
  calendar's sessions and business days for a window, under the runtime and the remote
  backend.
- **`jobs/resync_calendars.py`, an admin Job that writes stored calendars again from the
  installed library.** A person runs it; no step of the deployment does, it has no schedule,
  and the Markets API never writes a calendar again by itself. `--dry-run` prints what would
  change and writes nothing. The Job is declared in
  `.mainsequence/workflows/ms-markets-api.yaml` as `resync-calendars`; its workload User needs
  `data_writer` on `mainsequence.markets` (see "Calendar re-sync Job" in `docs/releasing.md`).
- **A packaged calendar skill for projects that build on ms-markets.**
  `.agents/skills/ms_markets/calendars/calendar_workflow/SKILL.md`, copied with
  `msm copy-msm-skills`, has the rules for getting, reading and correcting a calendar, the
  Markets API routes, and a table for moving code off the per-date rows.
- **The library's holiday names.** A closure the library has a holiday rule for carries the
  rule's name, such as `Thanksgiving`. An ad-hoc closure has none.
- **`msm.api.remote.MarketsUpstreamError`.** `msm.client` raises it when the Markets API
  answers `502` or `503` with `error_type` `UpstreamApiError`. It is a `MarketsApiError`, its
  message is the reason the upstream API gave, and `retryable` is `True` for `503`.

### Removed

- **`with_max_rows` in `msm.repositories.account_registration`.** It is in
  `msm.repositories.base` and takes a repository context or a table handle.
- **The default `24/7` calendar of an asset, and every calendar name in an asset scope.**
  `asset_calendar`, `DEFAULT_MARKET_CALENDAR` and `FULL_CALENDAR` are gone. A scope mapping
  with a `calendar` key is refused with a `TypeError`.
- **`PandasMarketCalendarSchedule`, `AlwaysOpenCalendarSchedule` and
  `resolve_legacy_rebalance_calendar`.** Nothing called them. `pandas_market_calendars` is
  now imported by the calendar adapter only.
- **`CalendarDate`, `CalendarSession` and `CalendarEvent`**: the tables, the row classes and
  their payloads, the repositories, and the create, bulk-upsert, get, update and delete
  routes of dates and sessions and all six `/calendar/{uid}/events/` routes. Nothing in
  ms-markets wrote or read `CalendarEvent`. No alias is kept.
- **`build_pandas_market_calendar_materialization`,
  `build_always_open_calendar_materialization`, `materialize_calendar_rows` and
  `CalendarMaterializationRows`.** A 24/7 calendar is
  `Calendar.create_from_pandas_calendar("24/7", "CRYPTO_24_7")`: one rule and no exception.

### Fixed

- **A hand correction to a calendar changed a portfolio's rebalance dates and not the bars
  of its assets.** `InterpolatedPrices` asked `pandas_market_calendars` for a calendar name
  read off the asset scope, with `24/7` when there was none. It now computes its sessions
  from the stored calendar each asset is linked to, so bars and rebalance dates follow the
  same rows.
- **Daily bars of a 24/7 asset were written a day late.** The price updater closed a 24/7 day
  at 23:59 UTC, so a bar observed at midnight was carried to 23:59 of the following day and
  flagged `interpolated`. A 24/7 day now closes at the next midnight, as the stored calendar
  says, and the bar stays at its time of observation.
- **The first daily bar was dropped and one was invented after the last.** Sessions were
  chosen by the dates of the first and last source bar, which is one session late when a
  session closes at midnight. They are now chosen by the instant they close, and no bar is
  written after the last source bar.
- **Minute bars could not be interpolated from a calendar name.** The intraday path read
  `.name` from a string, and upsampling passed an object where a name was expected. Both now
  take computed sessions. Whether a calendar has trading halts is computed from its sessions,
  not read off the name `24/7`.
- **Creating or extending a calendar with a long range answered `500`.** The API sent one
  row per day of the range in a single statement, which MetaTables refused once it passed
  1,000,000 characters, after the `Calendar` row had already been written. A calendar is now
  about 12 exception rows a year, written in one transaction with its header
  ([issue 83](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/83)).
- **A bulk upsert of a long list was refused, and nothing was written.** `bulk_upsert_model`
  compiled every row into one statement, and MetaTables refuses a statement of more than
  1,000,000 characters: about 5,500 `Asset` rows or 2,300 `CalendarException` rows. It now
  sends the rows in as many statements as the limits need, so `upsert_many` of every row
  class and the calendar bulk-upsert routes take a list of any length. Each statement is
  its own transaction: when one fails, the rows of the statements before it stay written,
  and calling again with the same list finishes the write
  ([issue 84](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/84)).
- **A bulk upsert of more than 1,000 rows did not return every row.** MetaTables returns at
  most `max_rows` rows of a statement, 1,000 unless the context says otherwise, and writes
  the rest without returning them. On SQLite the call raised `KeyError` and wrote nothing.
  Each statement now asks for as many rows as it writes.
- **A refused or failed MetaTables call answered `500` with no body.** Every route now
  answers `502` when MetaTables, or another API the deployment calls, refused the call and
  `503` when it failed or could not be reached, with `error_type` `UpstreamApiError`, the
  status it answered with and the reason it gave
  ([issue 84](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/84)).

### Upgrading

- **Link every asset that has price bars to a calendar, or its price update fails.** Revision
  0028 creates `AssetCalendar` and writes no rows: nothing stored says which calendar an
  asset trades on, and an asset is not linked to a calendar nobody chose. `InterpolatedPrices`
  now resolves the calendar of every asset in its scope before it reads a bar. When an asset
  has no link, the whole run fails and the error names each such asset. Link it with
  `AssetCalendar.upsert(asset_uid=..., calendar_uid=...)` and run again. An asset that trades
  around the clock is linked to a stored 24/7 calendar.
- **`time_index` is the time of observation.** A price source stamps each bar at its end: a
  daily bar at its session close, with the open in `open_time`. A bar stamped at its open is
  not handled. A source that receives vendor bars labelled by their start shifts them to
  the close itself.
- **New daily bars of a 24/7 asset are stamped at midnight; the stored ones are at 23:59.**
  Stored bars are not rewritten. To make a table uniform, rebuild it from its source.
- **A `CalendarEventSignal` must use the calendar of its portfolio.** `PortfoliosUpdater`
  refuses to run when the strategy's `calendar_identifier` is not the `unique_identifier` of
  `Portfolio.calendar_uid`, and names both calendars. Before, nothing compared them.
- **Revision 0027 converts every stored calendar from its own rows**, not from the library:
  the regular week becomes a rule, each stored date that differs becomes an exception, and
  `valid_from` and `valid_to` become the first and last stored date. It computes each
  converted calendar back and stops, before dropping anything, if a session differs from the
  stored one. Rows in `CalendarEvent` are deleted with the table. A calendar whose `timezone`
  is not an IANA name is converted in UTC and its `timezone` becomes `UTC`.
- **After the release, run the `resync-calendars` Job once**, with `--dry-run` first. A
  converted calendar still ends where its stored rows ended, and a read past that date now
  fails. The Job takes each adapter calendar to the library's range and hours. If a calendar
  was stored with hours that differ from the library's, the Job changes its sessions, and
  with them the rebalance times of the portfolios on it: that is why a person decides.
- **A calendar that was not written from pandas-market-calendars cannot be written from it
  under the same name.** `create_from_pandas_calendar("24/7", "CRYPTO_24_7")` is refused when
  `CRYPTO_24_7` was written with the removed always-open helper: writing it from the library
  would replace its rules. Delete that calendar first, or use another name.
- **In code that uses ms-markets:**
  - `CalendarSession.filter(...)` and `CalendarDate.filter(...)` become
    `Calendar.sessions(calendar_uid, start, end)` and `Calendar.dates(calendar_uid, start, end)`.
  - `Calendar.create_from_pandas_calendar(source_identifier=..., unique_identifier=...,
    display_name=..., valid_from=..., valid_to=...)` drops `valid_to` and `materialize`. A
    caller that called it to move `valid_to` forward stops calling it.
  - `msm.start_engine(models=[...])` lists `CalendarSessionRule` and `CalendarException`
    in place of `CalendarDate`, `CalendarSession` and `CalendarEvent`.
  - A calendar referenced by its `source_identifier` is referenced by its
    `unique_identifier`.
  - `{"asset_identifier": "...", "calendar": "NYSE"}` in an `asset_list` becomes
    `"..."` or `{"asset_identifier": "..."}`, and the asset gets an `AssetCalendar` link.
  - `IntradayTrendConfig(calendar="NYSE")` becomes
    `IntradayTrendConfig(calendar_identifier="NYSE")`, the `unique_identifier` of a stored
    calendar. The signal's hash changes.
  - `msm.start_engine(models=[...])` lists `AssetCalendar` where price updates run.

## [3.8.3] - 2026-11-17

### Fixed

- **The Markets API answered `500` on `calendar/create_from_pandas_calendar`.** The route
  imports `pandas-market-calendars`, which was only in the `portfolios` extra, and the API's
  image installs `requirements.txt`, which carries no extras. It is now a dependency of
  ms-markets, so `pip install ms-markets` installs it and the `portfolios` extra no longer
  lists it. A packaging test walks the modules the API and the migration Job can reach,
  imports inside functions included, and fails when one imports a package `requirements.txt`
  does not pin
  ([issue 81](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/81)).

## [3.8.2] - 2026-11-17

### Changed

- **Requires MetaTables 0.1.66 or later, where a table can be in several namespaces.**
  `mainsequence-metatable>=0.1.66,<0.2`. That client and the MetaTables API change
  together: an older client is refused by an API on 0.1.66 or later. A table's impact
  node carries `namespaces`, a list, instead of `namespace`
  (`TableImpactNode`, in the account delete preview).

### Fixed

- **The account delete preview on MetaTables 0.1.66 reported every Markets table as a
  table of another namespace.** It read the one `namespace` of each table the delete
  reaches, which the API no longer returns, so `other_namespace_cascades` and
  `other_namespace_restricts` listed the Markets tables too. A table is now a Markets
  table when the Markets namespace is one of its namespaces.

## [3.8.1] - 2026-11-16

### Added

- **A series-leading index on the signal and portfolio weights contracts.**
  `SignalWeightsStorage` gains `(signal_uid, time_index)` and `PortfolioWeightsStorage`
  gains `(portfolio_identifier, time_index)`, next to the unique time-leading index. A
  read of one signal or portfolio no longer walks the other series, and the last time of
  a series that stopped publishing is found without walking every later row. Measured on
  5,000,000 rows: one series' history read 39,901 pages instead of 82,000, and the last
  time of a stopped series 143 pages instead of 565,693, for 5% more index storage.
  Revision 0026 adds the indexes to the Markets-owned tables. Instances built with
  `configured_signal_weights_storage` and `configured_portfolio_weights_storage` declare
  the same index; **a provider adds it to its existing instances in a revision of its
  own**. The last-row-per-asset read still reads the whole history of the series it asks
  for ([issue 77](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/77)).

## [3.8.0] - 2026-11-15

### Added

- **`ApplicationWeights`: a signal whose weights an application publishes.** A provider
  binds it to its own `SignalWeightsTS` instance with
  `ApplicationWeightsConfig(provider=..., key=...)` and calls
  `publish({time: {asset unique_identifier: weight}})`. The signal uid depends only on the
  provider and key, so it does not change when the weights do. Each observation is the
  whole set (an asset the previous one held is written at `0`), several observations are
  one write, unknown assets and naive times are refused, and an observation at or before
  the last stored time is refused instead of being dropped without a word
  ([issue 75](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/75)).

## [3.7.1] - 2026-11-15

### Fixed

- **Remote row writes with a datetime value work on SQLite.** `create`, `upsert`, `update`
  and `upsert_many` type each string value against the row field of the same name
  (datetime, date, uuid, decimal ...) before the statement is built, so keyword values and
  payload mappings that arrive as JSON strings, such as `OrderManager.create_batch(...)`
  through the Markets API, no longer answer 400 on a SQLite runtime
  ([issue 73](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/73)).

## [3.7.0] - 2026-11-15

3.7.0 withdraws the unit account targets of 3.6.0
([ADR 0054](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0054-account-exposure-and-sized-fund-targets/)).
Projects that depend on ms-markets:
[Upgrading To 3.7](https://mainsequence-projects.github.io/MainSequenceMarkets/upgrading-to-3-7/)
lists what to change, coming from 3.5 or from 3.6, and
[Sizing Targets And Allocating](https://mainsequence-projects.github.io/MainSequenceMarkets/knowledge/msm/accounts/sizing_and_allocation/)
shows the whole flow with an example.

### Added

- **A virtual fund is created when its exposure is written.** A target that names a
  portfolio creates the `VirtualFund` of that account and portfolio, in the same transaction
  as the target rows, if it does not exist
  ([issue 71](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/71)).
- **The sync records its lines: target and assigned units for every owner.** A new table,
  `AccountAllocationLinesStorage`, has one row per sync, owner and asset. The owner is a
  virtual fund, or the account itself for a direct asset target and for what no fund takes,
  so a delta is kept for funds and direct targets alike.
  `GET /api/v1/account/{account_uid}/virtual-fund-allocations/`
  (`getAccountVirtualFundAllocation`, `MarketsClient.account_virtual_fund_allocation`) reads
  the lines of one sync, the latest by default, with `target`, `assigned` and `delta`.
- **`sized_targets` on the plan and allocate calls** (`planAccountVirtualFunds`,
  `allocateAccountVirtualFunds`, their `MarketsClient` methods and
  `plan_account_virtual_fund_allocations`): each exposure of the `PositionSet` in units,
  sized by the caller with its own prices. A mismatch with the target answers 400
  `invalid_sized_targets` and lists every problem. `plan_digest` covers the sized targets.

### Changed

- **Breaking:** an account's exposure to a portfolio is a share of NAV or an amount again.
  `TargetPositionsStorage` returns to its shape before 3.6.0: a portfolio row holds
  `weight_notional_exposure` or `constant_notional_exposure` and no `asset_uid`; an asset
  row holds one of those or `single_asset_quantity`. The target routes,
  `MarketsClient.add_account_target_positions`, `build_target_positions_frame`,
  `expand_portfolio_target_positions` and the exposure fields of
  `GET /api/v1/portfolio/{uid}/account-targets/` are back as they were in 3.5.
  - **Revision 0025** restores the columns and creates `AccountAllocationLinesStorage`. It turns an asset target written in units under
    3.6 into `single_asset_quantity`, and **deletes a `PositionSet` that has a portfolio
    row in units**, with its rows: units per asset cannot be turned back into a share or an
    amount. Targets deleted by revision 0024 are not restored.
- **Breaking:** an allocation takes the fund targets from `sized_targets`, not from the
  account target, and always writes. Every fund of the target gets its holdings set and its
  lines; a fund the account holds nothing of has its lines with nothing assigned. A target
  with no fund is recorded too.
- The allocation plan is built in one pass over its inputs. On 100,000 target rows it takes
  about a tenth of the time it took in 3.6.0.

### Removed

- **Breaking:** the unit columns `quantity` and `direction` of `TargetPositionsStorage`,
  the required `asset_uid` on portfolio target rows, and `asset_count` on
  `GET /api/v1/portfolio/{uid}/account-targets/`, all added in 3.6.0.
- **Breaking:** the `nothing_to_apply` refusal. An allocation that assigns no units is a
  valid allocation of that snapshot.

## [3.6.0] - 2026-11-15

Superseded in part by ADR 0054 (see Unreleased): the unit account targets described below
are withdrawn.

### Added

- The Markets API allocates an account's holdings to its virtual funds again, and values
  nothing to do so
  ([ADR 0053](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0053-virtual-fund-allocation-routes-and-described-policies/)).
  Targets and holdings are both in units (ADR 0052), so a request carries no price, NAV or
  valuation.
  - **Routes and client methods:**
    `GET /api/v1/account/virtual-fund-allocation-policies/`
    (`MarketsClient.virtual_fund_allocation_policies`),
    `GET /api/v1/account/virtual-fund-allocation-policies/{policy_id}/`
    (`virtual_fund_allocation_policy`),
    `POST /api/v1/account/{account_uid}/virtual-fund-allocations/plan/`
    (`plan_account_virtual_funds`) and
    `POST /api/v1/account/{account_uid}/virtual-fund-allocations/`
    (`allocate_account_virtual_funds`). The last path and client method, removed in 3.5.0,
    come back with a new contract. The Command Center adapter lists the four operations.
  - **Described policies:** a policy has an id, a version and an arguments class. Its
    description is generated from that class as JSON Schema 2020-12, and the same class
    validates a request's arguments. A request built against another version is refused.
    The registry has one policy, `proportional_attribution`, with one argument,
    `quantity_tolerance`.
  - **One answer for every policy:** a plan has one line per owner and asset, where the owner
    is a virtual fund or the direct account sleeve, with `target`, `assigned` and
    `delta = target - assigned`. `account_deltas` gives each asset's total target minus what
    the account holds. The target is the full picture: an asset the account holds that no
    target names has a target of zero.
  - **One transaction:** the allocation writes the virtual funds, one holdings set per fund
    and the holdings rows together. The allocate route plans again from the same inputs and
    never accepts a plan from the client; `plan_digest` refuses a plan that changed.
  - **An applied allocation is account history:** the same plan again writes nothing, and a
    different allocation of the same snapshot is refused.

### Changed

- **Breaking:** account targets are stored in units
  ([ADR 0052](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0052-account-targets-in-units/)).
  Every `TargetPositionsStorage` row is a positive `quantity` of one asset with a
  `direction` (`1` long, `-1` short), like account holdings. A portfolio target is the
  virtual fund's unit basket: one row per asset, so `asset_uid` is required on every row
  and joins the storage index. The caller sizes a basket with its own prices and rules and
  writes it; ms-markets records it and values nothing.
  - **Migration 0024 deletes every existing `PositionSet` and its target rows.** They
    hold shares of NAV and notional amounts, which cannot be turned into units without
    prices. `AccountTargetAllocation` rows and applied virtual-fund holdings are kept.
    Write each account's target again in units after upgrading.
  - **Target writes and reads:** `POST /api/v1/account/{account_uid}/add-target-positions/`,
    `MarketsClient.add_account_target_positions` and `build_target_positions_frame` take
    `asset_uid`, `quantity` and `direction` on every row, and a portfolio row also takes
    `portfolio_uid`. `GET /api/v1/account/{account_uid}/target-positions/` answers the same
    fields. A row with a share of NAV, a notional amount, a zero or negative quantity, or
    without an asset is refused.
  - **`GET /api/v1/portfolio/{uid}/account-targets/`** answers `asset_count`, the number of
    assets in the portfolio's unit basket, in place of the exposure fields.
  - **The allocation planner reads units only.**
    `plan_account_virtual_fund_allocations` takes `position_set_uid`, `valuation_time` and an
    optional `policy` (ADR 0053). The plan has no NAV, valuation asset or notional fields.
- **Breaking:** the Python allocation API follows the Markets API contract (ADR 0053).
  - `AccountVirtualFundAllocationPlan` has `lines`, `account_deltas`, `funds`,
    `apply_blockers` and `plan_digest`. It has no `status`, `residuals`, `deficits` or
    `diagnostics`.
  - `apply_account_virtual_fund_allocation_plan(plan)` writes in one transaction and returns
    an `AccountVirtualFundAllocationResult`. It takes no updater.
  - A target with no fund is planned, with every holding on the direct sleeve. A refusal
    raises `AllocationError`, which carries a `code`.

### Removed

- **Breaking:** with unit targets (ADR 0052) these are gone:
  - the `weight_notional_exposure`, `constant_notional_exposure` and
    `single_asset_quantity` columns and wire fields;
  - `expand_portfolio_target_positions` and `TARGET_POSITION_EXPOSURE_FIELDS`;
  - from the allocation planner: the `valuation_asset_uid`, `valuation_resolver` and
    `portfolio_target_expander` parameters, and `ValuationResolver`, `ValuationPolicy`,
    `AllocationValuation`, `ValuationMetricValue`, `ValuationMetricLine`,
    `ValuationMetricResult`, `TargetNotionalDemand` and `expand_portfolio_target_rows`.
    `HoldingValuationInput` is now `AccountHoldingInput`, and `ValuationDiagnostic` is
    `AllocationDiagnostic`;
  - the `target_weight` and `weight_notional_exposure` branches of
    `Account.pretty_print_positions`;
  - the valuation-resolver skill. `accounts/target_sizing` replaces it.
- **Breaking:** with described policies (ADR 0053) these are gone:
  - `AllocationPolicy`, including the fields that nothing read, and `HoldingsSelectionPolicy`;
  - the `strict_feasible` policy. It assigned nothing differently from
    `proportional_attribution`; it only refused a shortfall. A caller that wants all or
    nothing plans first and allocates only when no account delta is positive;
  - the plan status and its three values;
  - `TargetQuantityDemand`, `AccountHoldingInput`, `AllocationDiagnostic`,
    `AccountVirtualHoldingLine`, `AccountAllocationResidual` and `AccountAllocationDeficit`;
  - the `updater`, `run` and `data_node` parameters of the apply step.

## [3.5.0] - 2026-11-15

### Removed

- **Breaking:** the Markets API no longer allocates an account's holdings to its virtual
  funds (#68,
  [ADR 0029](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0029-account-holdings-virtual-fund-allocation-policy/)
  amendment). `POST /api/v1/account/{account_uid}/virtual-fund-allocations/`
  (`allocateAccountVirtualFunds`), `MarketsClient.allocate_account_virtual_funds`, the
  `AccountVirtualFundAllocation*` wire contracts in `msm.api.accounts`,
  `msm.services.accounts.allocate_account_holdings_set`, `account_allocation_policy` and
  the repository write `replace_account_virtual_fund_holdings` are gone. The route
  supplied the valuation (each holding at its target portfolios' weights `price_current`)
  and the policy itself, while ADR 0029 makes both the caller's inputs, and it refused any
  account holding an asset outside its target portfolios. A client that calls the route
  gets `404`, and the client method no longer exists. An application without grants on
  `mainsequence.markets` has no way to allocate through the Markets API.
  - Kept: the planner and its apply step (`plan_account_virtual_fund_allocations`,
    `apply_account_virtual_fund_allocation_plan`), which still write no fund for a retired
    portfolio (ADR 0049), the virtual-fund tables and their reads, including
    `GET /api/v1/account/{account_uid}/holdings/by-fund/`.
  - The Command Center adapter no longer lists `allocateAccountVirtualFunds`. The account
    routes guide, the virtual-funds and client pages, the account workflow skill and ADR
    0049 drop the route.

## [3.4.2] - 2026-11-15

### Fixed

- Account history can no longer be deleted one row at a time under the runtime backend
  (#66, [ADR 0049](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0049-portfolio-lifecycle-and-account-history/)).
  `AccountHoldingsSet`, `AccountTargetAllocation`, `PositionSet`, `VirtualFund` and
  `VirtualFundHoldingsSet` `delete` now raises `MarketsOperationUnsupported` under both
  backends and deletes nothing; before, it deleted the row locally and was refused only by a
  hosted Markets API. The message says the rows are account history and that
  `Account.delete` removes them with the account. Code or test doubles that deleted these
  rows must stop: the account delete (ADR 0050) is the only way to remove them.
- The row router's `501` for a resource without a delete no longer tells the caller to use
  "service routes" that do not exist: it answers "`<Class>.delete` is not offered remotely."

## [3.4.1] - 2026-11-13

### Changed

- Requires `mainsequence-metatable>=0.1.64,<0.2` (was `>=0.1.61`). The lock and
  `requirements.txt`, which hosted images install, select 0.1.64. No other locked package
  changes.
  - **Rollouts:** API discovery waits out a MetaTables API rollout within its budget
    instead of failing at once (MetaTables#108). The 3.4.0 Markets API rollout stopped at
    its migrate step this way, while MetaTables was rolling out.
  - **Fewer requests:** a hosted row operation is one request (MetaTables#106).
  - **SQLite account delete:** SQLite enforces foreign keys from tables outside the
    caller's grants (MetaTables#105). On the local runtime, an account delete is no longer
    refused because another namespace's table has a key into the account tables.
- The SQLite account-delete tests create the provider tables outside the execution
  identity. The strict `xfail` for MetaTables#105 is gone, and the API guide no longer lists
  the limitation. [ADR 0050](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0050-account-deletion/)
  carries an amendment.
- The README, the getting-started, tutorial, release and FastAPI guides, and the migration
  pages give the MetaTables minimum as 0.1.64. The vendored skills in
  `.agents/skills/metatables/` are refreshed from 0.1.64.

## [3.4.0] - 2026-11-12

### Added

- One call registers an account and writes its holdings snapshot (#63,
  [ADR 0051](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0051-account-registration-in-one-transaction/)):
  `POST /api/v1/account/registration/` (`registerAccount`), `MarketsClient.register_account`
  and `msm.services.register_account`. In one MetaTables transaction it creates the
  missing asset types, assets and cash currency asset, writes asset snapshots whose values
  changed, creates the account or updates the fields that differ, and writes the
  holdings. It reads twice whatever the number of assets and positions: the assets with
  their latest snapshots, and the account with its holdings at `holdings_date`. A
  re-registration of known assets costs those two reads and one transaction, or no
  transaction when nothing changed; before, a connector made about 13 Markets calls.
  - Idempotent on `(account.unique_identifier, holdings_date)`: holdings equal to the
    stored ones are not written again and the call succeeds, with or without
    `overwrite`. Different holdings answer `409` without `overwrite`, and nothing in the
    call is written.
  - An existing asset keeps its `asset_type`; a different requested type answers `409`
    listing each asset, and nothing is written. A position naming an asset that is
    neither listed nor existing answers `400`.
  - Snapshot rows are written with plain SQL inside the transaction, not through the
    `AssetSnapshot` updater, only when the asset has none or its latest snapshot is
    earlier than `holdings_date` and differs in `name`, `ticker`, `exchange_code` or
    `asset_ticker_group_id`. MetaTables catalog statistics do not count them.
  - The holdings rows look the account uid up by `unique_identifier` inside the
    transaction, so concurrent first registrations reference the account that won.
  - Audited as `registry_write("account", "register")`, with one record per row
    created or changed. Command Center lists it as a mutation.
  - Provider sidecars stay provider-owned: the provider writes its sidecar afterwards
    with the returned account uid.
- `Asset.get_or_create_currency(code)` and `msm.services.get_or_create_currency_asset`
  return the currency asset `code`, creating it and the built-in `currency` asset type
  when missing, in one transaction. The migrations do not seed built-in asset types. An
  existing asset of another type raises `AssetTypeConflictError` (`409`). It is a row
  operation, so it runs through the Markets API too.
- `msm.time_index.assets.snapshots.changed_asset_snapshots` and
  `SNAPSHOT_VALUE_COLUMNS`; `AssetSnapshot.without_stored_snapshots` and
  `stored_snapshot_values`; `msm.api.assets.AssetSnapshotPublication`.
- `msm.repositories.crud.UpsertStatus`, `UPSERT_STATUS_COLUMN` and
  `UPSERT_STATUS_GUARD`; `msm.repositories.base.values_parameter`.

### Changed

- Upserts no longer rewrite unchanged rows (#62). `upsert_model`, `bulk_upsert_model`
  (and so every row class's `upsert` and `upsert_many`) update a conflicting row only
  when one of the updated columns differs from its new value; conflict, primary-key
  and `onupdate` columns are not compared, and JSON columns compare as `jsonb` on
  PostgreSQL, where the Markets migrations create them as `json`. A row with only key
  columns is inserted or left alone (`ON CONFLICT DO NOTHING`). Every input row still
  comes back, in input order, now with `upsert_status`: `inserted`, `updated` or
  `unchanged`.
  - On PostgreSQL this is one statement that reads the unchanged rows from its own
    snapshot. A row another transaction commits with the same values after that
    snapshot is read back afterwards and reported `unchanged`.
  - On SQLite the statuses are read first, then one transaction refuses rows whose
    status changed since (guard `upsert_status`, `UPSERT_STATUS_GUARD`), upserts and
    returns the rows; a refused write is read and tried again, up to three times.
  - An upsert refuses a `NULL` conflict-key value (a `NULL` never conflicts, so the
    row was inserted again on every call) and a conflict key given twice, with
    `ValueError`.
  - `build_upsert_model_operation` and `build_bulk_upsert_model_operation` return a
    `MarketsCompiledWrite` and take `dialect=` and, for SQLite, `statuses=`; so do
    `build_upsert_asset_operation`, `build_upsert_portfolio_group_operation`,
    `build_upsert_portfolio_group_membership_operation` and
    `build_replace_asset_category_memberships_operations`. `upsert_asset`,
    `upsert_portfolio_group`, `upsert_portfolio_group_membership` and
    `replace_asset_category_memberships` run through `upsert_model` and
    `bulk_upsert_model`.
- **Breaking:** `AssetSnapshots.publish` writes only the rows that change their
  asset's snapshot and returns `AssetSnapshotPublication(written=, skipped=)` instead
  of an `int` (#62). Each row is compared on `name`, `ticker`, `exchange_code` and
  `asset_ticker_group_id` (`None` equals `""`) with the snapshot in effect at its own
  `time_index`: the asset's latest stored row at or before it, or the asset's
  previous row in the batch when that one is later, so a backdated change is still
  written. When every row is unchanged, no update run starts. A row that repeats a
  stored or an earlier `(time_index, asset_identifier)` with the same values is
  skipped; with different values it raises `ValueError` (`400` from the rows route),
  as before. The remote client decodes the new result.
- An `AssetSnapshot` run drops rows already stored with the same values instead of
  failing; a key stored with different values still fails it with `ValueError`.

### Removed

- `AssetSnapshot.verify_backend_index_available` and `existing_backend_index_keys`,
  replaced by `without_stored_snapshots` and `stored_snapshot_values`.

### Fixed

- Publishing an account holdings snapshot costs 3 MetaTables operations whatever
  the number of positions, down from N + 4, or N + 5 with asset detail (#61):
  `POST /api/v1/account/{uid}/add-holdings/`, `AccountHoldingsSnapshots.publish` and
  `msm.services.add_account_holdings_snapshot_response`. One select reads every
  position's asset, and the answer is built from the rows the write returns
  instead of reading the snapshot back. The response is unchanged. A write whose
  rows exceed an operation's `max_rows` reads the rest back in pages.
- A holdings publish with several unknown assets names all of them in one error
  (`400` on the route), and writes nothing.

## [3.3.0] - 2026-11-11

### Added

- Accounts can be deleted with their whole history (#58,
  [ADR 0050](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0050-account-deletion/)).
  `DELETE /api/v1/account/{uid}/` (`deleteAccount`), `POST /api/v1/account/bulk-delete/`
  (`bulkDeleteAccounts`) and `POST /api/v1/account/bulk-delete/preflight/`
  (`preflightBulkDeleteAccounts`), offered as a bulk action on the account list. One
  transaction removes the account's orders, trades and the order events of those
  orders, its order managers, virtual funds, target allocations, position sets,
  holdings sets and their rows, then the account, on PostgreSQL and SQLite; if
  anything refuses, nothing is deleted.
  - Markets sends deletes only to its own tables. A table in another namespace loses
    rows only through its own foreign key: a `CASCADE` key deletes them with their
    parent and the response lists the table in `other_namespace_cascades`; a
    `RESTRICT` key refuses the delete with `409`. The preflight reports both kinds of
    table from the MetaTables impact, and the Markets rows per table for each
    account.
  - Orders of other accounts that name the account's order managers, and virtual
    funds of other accounts allocated from its holdings sets, block the delete.
  - The same identities that may delete a portfolio may delete an account; both
    routes are registry writes.
- `msm.services.delete_account`, `bulk_delete_accounts`, `preflight_account_delete`,
  `preflight_bulk_delete_accounts` and `account_delete_impact` run the delete for the
  routes and for `msm.api`; `msm.repositories.account_deletion` compiles it.

### Changed

- `Account.delete(uid)` deletes the account with its history, as the route does,
  under the runtime and the remote backend; it was a one-row delete in-process and
  `MarketsOperationUnsupported` remotely. It returns `None` for an unknown account and
  raises `AccountDeleteConflictError` (`MarketsConflictError` remotely) when a key
  refuses it. `Account.bulk_delete(uids=...)` is new. The row router now runs any
  row class's own `delete`.
- The API runtime also binds `OrdersStorage`, `TradesStorage` and
  `OrderEventsStorage`.

### Removed

- `msm.services.delete_account_target_allocation`, `delete_position_set` and
  `delete_virtual_fund`, with `msm.repositories.accounts`'
  `build_delete_account_target_allocation_operation`,
  `delete_account_target_allocation`, `build_delete_position_set_operation`,
  `delete_position_set` and `msm.repositories.virtual_funds`'
  `build_delete_virtual_fund_operation` and `delete_virtual_fund`. Nothing called
  them, and an account's history is not removed from an account that is kept
  (ADR 0049). `msm.repositories.build_delete_account_operation` and `delete_account`
  now compile and run the cascading delete and take the account's
  `unique_identifier` as well as its `uid`.

### Fixed

- `Curve.delete(uid, delete_values=True)` and
  `DELETE /api/v1/pricing/curves/{uid}/?delete_values=true` no longer delete rows
  in a discount-curve storage another application owns (#59). They deleted the
  curve's observations from every storage table a pricing market-data-set binding
  named, including a provider's instance in its own namespace, which broke ADR
  0047. `delete_values` now cleans only Markets' `DiscountCurvesStorage`. A
  provider's instance keeps the core storage's `RESTRICT` key on
  `curve_identifier`, so while it holds rows of the curve the delete preflight
  lists it as a blocker (`provider_discount_curve_observations:{storage_table_uid}`,
  whatever the flags), and the delete sends that table no statement, deletes
  nothing and answers 409 naming the table and pointing to the owning
  application. The row API raises the new `CurveDatasetOwnershipError`, a
  `CurveDeleteConflictError`. A bound table Markets cannot resolve still blocks
  the delete and is reported with `count_accuracy: "unavailable"`.
  `PROVIDER_TABLE_DELETE_GUIDANCE` and the ownership check behind the portfolio
  and signal deletes moved to `msm.storage_instances` (`provider_owned_table_uid`)
  so both deletes share them; `msm_portfolios.services.public_api` still exposes
  `PROVIDER_TABLE_DELETE_GUIDANCE`.

## [3.2.3] - 2026-11-11

### Changed

- No code changes from 3.2.2. This release redeploys the Production Markets API: the
  platform workflow for the 3.2.2 merge failed while preparing its image, so its migration
  Job and API rollout never ran.

## [3.2.2] - 2026-11-11

### Fixed

- A test that replaced an account hook on `msm.services.accounts`, such as
  `get_account_by_uid`, no longer leaves it on `msm.services.accounts.core` (#55). The
  snapshot entry points copied the package's hooks onto `core` before each call and never
  put them back. pytest's `monkeypatch` undid only the package attribute, so a later test
  calling `core` directly got the earlier test's fake. Now the entry points hand `core` only
  the hooks replaced on the package, for one call, and restore `core`'s own afterwards,
  also when the call raises. With nothing replaced, as in a deployment, `core` is no longer
  written on each call.

## [3.2.1] - 2026-11-11

### Fixed

- The account target-position, holdings and virtual-fund holdings snapshot writes run on
  a SQLite DataSource, such as the MetaTables local runtime (#53). Before, the target and
  holdings writes failed to compile there, and the clear and the virtual-fund write
  compiled but SQLite refused them: each is one PostgreSQL statement whose data-modifying
  CTEs upsert the parents, delete the old rows and insert the new ones, and SQLite accepts
  only `SELECT` inside `WITH`. PostgreSQL keeps that statement. On SQLite the same steps
  compile into a statement list that MetaTables runs in one transaction (MetaTables ADR
  0026), so a snapshot still commits whole or not at all. The values bind without casts,
  because SQLite casts `DATETIME` and `JSON` to numbers.
- A refused write behaves the same on both dialects: an existing snapshot without
  `overwrite`, a retired portfolio (ADR 0049) or a virtual fund of another account returns
  no rows, and the services answer as before. On SQLite a refused write changes nothing at
  all.

### Changed

- Requires `mainsequence-metatable>=0.1.61,<0.2` (was `>=0.1.57`). 0.1.60 adds statement
  lists; 0.1.61 binds UUIDs on SQLite inside `IN` lists and when given as text
  (MetaTables#100, #101), which the services' reads need on the local runtime.
- Requires `mainsequence>=9.0.31,<10` (was `>=9.0.29`), the SDK that MetaTables 0.1.60 and
  later require. The lock and `requirements.txt` select `mainsequence` 9.0.40 and
  `mainsequence-metatable` 0.1.61.
- The README, the getting-started, tutorial, release and FastAPI guides, and the migration
  pages gave the minimums as SDK 9.0.29 and MetaTables 0.1.51; they now give 9.0.31 and
  0.1.61.
- The vendored skills in `.agents/skills/metatables/` and `.agents/skills/mainsequence/`
  are refreshed from the locked releases; the MetaTables copy now includes ADR 0026.
- `build_replace_account_target_positions_snapshot_operation`,
  `build_replace_account_holdings_snapshot_operation` and
  `build_replace_account_virtual_fund_holdings_operation` take `dialect=`. On SQLite they
  return a `MetaTableCompiledSQLTransaction`.
- `msm.repositories.base` adds `resolve_markets_sql_target`, `compile_markets_statements`
  and `execute_markets_write`. `compile_markets_statement` takes `data_source_uid=`. A
  write resolves the runtime once, as compiling it did before.

## [3.2.0] - 2026-11-10

### Added

- `GET /api/v1/portfolio/{uid}/account-targets/` (`listPortfolioAccountTargets`) pages
  the accounts whose current target names a portfolio (#49): each item gives the
  account, its target allocation, the `PositionSet` uid and time of the snapshot, and
  the portfolio row's exposure. The current target is the one
  `GET /api/v1/account/{account_uid}/target-positions/` reads; an account that named
  the portfolio only earlier, or whose target was cleared, is not listed. One query
  starts from the `portfolio_uid` index. `MarketsClient.portfolio_account_targets`
  returns a `ResourceCollection[PortfolioAccountTarget]`.
- Portfolios can be retired instead of deleted (#51,
  [ADR 0049](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0049-portfolio-lifecycle-and-account-history/)).
  `Portfolio.retired_at` (revision `0023`) is null while a portfolio is live.
  `POST /api/v1/portfolio/{uid}/retire/` (`retirePortfolio`) sets it to the time of
  the request and is refused with `409` while any account's current target names the
  portfolio; `POST /api/v1/portfolio/{uid}/reinstate/` (`reinstatePortfolio`) clears
  it. `MarketsClient.retire_portfolio` and `reinstate_portfolio` call them. Nothing is
  deleted: account target snapshots, virtual funds and their holdings, and the
  portfolio's weights and values stay. While a portfolio is retired:
  - a target snapshot that names it is refused with `409`, whatever its date, and
    writes nothing; the statement locks the named portfolio rows, so it cannot
    interleave with a retirement. The SDK `TargetPositions` updater refuses it too;
  - applying a virtual-fund allocation for a snapshot at or after `retired_at` is
    refused (`409` from the route, `PortfolioRetiredError` in the SDK);
  - `GET /api/v1/portfolio/` and `GET /api/v1/account/target-allocation/targets/`
    leave it out unless `include_retired=true`;
  - `PortfoliosUpdater`, `PortfolioWeights`, `PortfolioRebalance` and
    `PortfolioEngine` write nothing dated at or after `retired_at`.

### Removed

- `POST /api/v1/portfolio/bulk-cascade-delete/` (`bulkCascadeDeletePortfolios`), the
  `apps.v1` services `cascade_delete_portfolio` and `bulk_cascade_delete_portfolios`,
  `msm_portfolios.services.cascade_delete_portfolio_record` and
  `bulk_cascade_delete_portfolio_records`, and the `PortfolioDeleteRequest`,
  `PortfolioCascadeDeleteResponse` and `PortfolioBulkCascadeDeleteResponse` schemas.
  The route deleted every account's target rows and virtual funds for a portfolio,
  current targets included; account history is now kept, and a portfolio that
  accounts referenced is retired instead (ADR 0049). `DELETE /api/v1/portfolio/{uid}/`
  and `POST /api/v1/portfolio/bulk-delete/` are unchanged.

### Changed

- ADR 0048's remaining column steps are revisions `0024` to `0026`, because `0023`
  holds `Portfolio.retired_at`; 3.1.0 shipped without the read switch the ADR had
  assigned to it.

## [3.1.0] - 2026-11-09

### Added

- `msm.api.http` has the account sync contract every venue connector shares (#44):
  `AccountSyncRequest`, `AccountSyncResult` (`account_uid`, `holdings_set_uid` or
  `null`, `time_index` in UTC, `holdings_rows`, optional `extra`) and
  `AccountSyncOperation`, the `ObservableOperation` with `action = "account_sync"`.
  A succeeded sync must carry its result, for the requested account. The convention
  (`POST /v1/accounts/{account_uid}/actions/sync` with no body, `200` with a terminal
  operation or `202` with a queued one polled at `GET /v1/operations/{operation_uid}`)
  is documented in the provider toolkit guide.
- `POST /api/v1/account/{account_uid}/virtual-fund-allocations/`
  (`allocateAccountVirtualFunds`) runs the virtual-fund allocation planner for one
  account holdings snapshot inside the Markets API, so a caller needs no grants on
  `mainsequence.markets` (#46). The target defaults to the one in force at the
  snapshot's time. The Markets API values the account itself: the valuation asset at
  one and every other asset at its target portfolios' latest weights `price_current`
  at or before the snapshot's time; an asset without such a price fails the request.
  The response is the plan (funds, allocation lines, residuals, deficits, warnings).
  With `apply`, the funds and their holdings for the snapshot are written to the core
  `VirtualFund`, `VirtualFundHoldingsSet` and `VirtualFundHoldingsStorage` tables in
  one statement, replacing what the account's funds held for it, and
  `holdings/by-fund/` shows them; a dry run writes nothing.
- `MarketsClient.add_account_target_positions`, `account_target_positions`,
  `clear_account_target_positions` and `allocate_account_virtual_funds` call those
  routes and return typed responses (#47). The target-position request and response
  models now live in `msm.api.accounts`, so the client returns them from the wheel.

### Changed

- An empty `positions` list on `POST /api/v1/account/{account_uid}/add-target-positions/`
  clears the account's target (#47): it writes an empty `PositionSet` at
  `target_positions_date`, so the history records the clearing, and sets the account's
  target allocation inactive. The read then returns no positions until a new target is
  written. A refused snapshot write (`overwrite=false` on an existing snapshot) no
  longer changes the allocation's `is_active`.

### Fixed

- The allocation planner used a target only when its rows' time equalled the holdings
  valuation time, so a capture taken after the target was written could never be
  attributed to the virtual funds (#45). The planner now uses the rows of the
  `PositionSet` the caller passes, as they are, in both the resolved and the in-memory
  paths. A `PositionSet` written after the valuation time is refused, as are target
  rows of another `PositionSet` or of several snapshots.

## [3.0.5] - 2026-11-04

### Changed

- Second rebuild of 3.0.3: the 3.0.4 pipeline's migration step failed on the platform side
  (the Job pod never started), so Production still runs 3.0.2. No code change.

## [3.0.4] - 2026-11-04

### Changed

- Rebuild of 3.0.3: its hosted image build failed on the platform side during a database
  outage, so this release carries no code change and exists to redeploy the fix below.

## [3.0.3] - 2026-11-04

### Fixed

- The Markets API now attaches every table its remote row route offers. `OrderManager`,
  `Issuer`, `BondAssetDetails`, `CurrencySpotAssetDetails` and `RebalanceStrategyMetadata`
  were missing from `V1_RUNTIME_MODELS`, so every `POST /rows/{resource}/{operation}/` call on
  `order-manager`, `issuer`, `bond`, `currency-spot` or `rebalance-strategy-metadata` failed
  in `resolve_runtime` and answered 500. A connector's execution ledger looks its batch up
  with `OrderManager.get_by_unique_identifier`, so no remote-backend application could submit
  or read orders. A test now requires every offered resource to be served by the runtime.

## [3.0.2] - 2026-10-27

### Fixed

- Portfolio contract instances now carry the core storage's `__storage_layout__`.
  Instances previously fell back to MetaTables' default layout. For
  `PortfolioEventLedgerTS` that default names the secondary index after the
  four identity dimensions, which is 70 characters, and MetaTables refuses
  derived names over PostgreSQL's 63-character limit. Every event-ledger
  instance therefore failed registration, which stopped a downstream
  consumer's hosted migration Job before it migrated anything. Instances of
  the other five contracts declare no layout and are unchanged.

## [3.0.1] - 2026-10-27

### Removed

- The registry write allow-list of 3.0.0: `apps.v1.policy` and the Main Sequence
  Constant `MARKETS_REGISTRY_WRITERS`. Which applications may trigger registry
  writes is the platform's grant: an application reaches the Markets API only
  when its workflow grants it the `MainSequenceMarkets` branch, and every
  caller the API admits may write. `registry_write` still records the acting
  identity of every write. A deployment that created the constant can delete it.

## [3.0.0] - 2026-10-26

Breaking release 3.0.0. It renames the DataNode vocabulary to the MetaTables
time-index terms: packages, updater and configuration classes, and UID fields
that now name the identity they hold. See
[ADR 0048](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0048-time-index-vocabulary-rename/)
and [Upgrading To 3.0](https://mainsequence-projects.github.io/MainSequenceMarkets/upgrading-to-3/).
Every pre-3.0 name keeps working through 3.x with a `DeprecationWarning`.
Producers built from a moved class get a new `update_hash` once; signal,
portfolio and strategy identities do not change. Dependent packages declare
`ms-markets>=3,<4`.

### Added

- Provider-owned Index values (ADR 0047, decision 4):
  `configured_index_values_storage(cadence=..., namespace=, storage_app=, base=)`
  builds a provider's `<storage_app>__index_values__t_<cadence>` table in its own
  namespace; without them it is Markets' own table, unchanged. The Index dataset
  catalog discovers and reads both.
- Moving existing history into provider instances (ADR 0047):
  `msm.storage_copies.copy_time_index_rows` copies the rows of some keys that a
  target table lacks from another table of the same contract, through the
  `TimeIndexRowsCopy` updater, and verifies every key; a second pass fills only
  the gaps. `TableSeriesMove`, `msm_portfolios.services.series_moves`
  `PortfolioSeriesMove` and `SignalSeriesMove` move a series and roll it back,
  including the catalog and signal-binding calls in a fixed order, and
  `run_series_moves` / `msm series move|rollback` run a provider's moves.
  A move refuses, before switching the provider, a signal without a
  `SignalMetadata` row; a portfolio rollback keeps the binding of a signal that
  did not move with it (`PortfolioDatasets.unregister(..., unbind_signal=False)`);
  moves take `keys_per_read` and `deadline_seconds`; `msm series` passes
  `rollback=` to a callable that accepts it.
- Remote reads and lifecycle calls providers need (ADR 0047): `filter` and
  `count` take `<field>__gte`, `__gt`, `__lte` and `__lt` range bounds
  (`msm.repositories.crud` `range_filters`); `AssetSnapshots.latest` returns
  each asset's latest snapshot by identifier, uid or ticker
  (`msm.services.assets.asset_identifiers_by_ticker`);
  `PortfolioDatasets.register_signal` binds any signal's weights instance;
  `FormulaIndex.activate_definition` and `retire_definition` back
  `activate()`/`retire()`; `GET /portfolio/values/` takes `offset` and
  `MarketsClient.portfolio_values` pages past 5,000 rows.
  `CurrencySpot` and `Future` gain `upsert_many` and `filter`;
  `AccountHoldingsSnapshots.get_many` returns several snapshots in one call
  (`msm.services.get_account_holdings_snapshots_response`);
  `PortfolioDatasets.unregister` removes a catalog row for a rollback, and
  `unregister_signal` clears one signal's instance binding.
- Provider time series (ADR 0047): `msm.storage_instances.configured_time_index_instance`
  builds a provider-owned instance of any Markets time-index storage, with its
  columns, foreign keys and grain index, in the provider's namespace and Alembic
  base. `configured_interpolated_prices_storage` takes `namespace`,
  `storage_app` and `base`, and `InterpolatedPrices` takes `storage_namespace`,
  `storage_app` and `storage_base`, without changing `update_hash`.
  `msm_portfolios.api.datasets.PortfolioDatasets.register/reconcile/get` run the
  portfolio dataset catalog services through the remote backend.
- Set-based row operations on every table row class, under both backends:
  `upsert_many(payloads)` (one bulk upsert on `__upsert_keys__`, each payload
  validated through `<Row>Upsert`), `count(**filters)`, and `filter(...)` with
  `order_by`, `offset` and `<field>__in`. `msm.repositories.crud.search_model`
  gains `order_by`. `AccountHoldingsSnapshots.publish/get` and
  `AssetSnapshots.publish` publish holdings and asset snapshots into Markets, so
  an application on the remote backend needs no grant on those tables.
- Under the remote backend, `msm.start_engine(models=[...])` no longer attaches
  a Markets table that is only a foreign-key target of another namespace's
  table; the provider's tables reference it by physical name, and the
  provider needs no grant on `mainsequence.markets`. Runtime-backend processes
  attach foreign-key targets as before.
- `msm.client` and the remote row backend (ADR 0047, decision 2). With
  `use_remote_backend(MarketsClient.from_environment().backend)` or
  `MSM_API_BACKEND=remote`, every public class method of a Markets row class
  (`Asset.upsert`, `Portfolio.get_by_uid`, `CurrencySpot.upsert`,
  `Index.get_formula` ...) runs through the Markets API instead of MetaTables,
  so an application needs no grant on `mainsequence.markets`. A provider's own
  row classes keep the runtime backend. The client discovers the `api` release
  of the `MainSequenceMarkets` repository in the caller's Environment and
  authenticates with its release token; `MARKETS_API_URL` and
  `MARKETS_API_TOKEN` select a local API. New routes `GET /rows/` and
  `POST /rows/{resource}/{operation}/` serve it; writes go through the registry
  write policy. `MarketsClient.portfolio_values` and `portfolio_weights` read
  catalogued portfolio time series.
- Registry write policy (ADR 0047, decision 3). `apps.v1.policy` runs before
  every `registry_write` service: an application (workload identity) may create,
  update or delete registry rows only when the Main Sequence Constant
  `MARKETS_REGISTRY_WRITERS` lists its User uid for that resource or for `"*"`;
  other applications get `403`. People, requester-bound calls, Organization
  admins and calls outside a request are unaffected. A missing constant allows
  no application, and an unreadable or malformed one returns `503`. The Markets
  workload needs `reader` on the constant. Deployments where applications write
  registry rows today must create the constant before upgrading.
- The portfolio engine can write every output to a provider's own instances
  (ADR 0047). `PortfolioRebalanceStateTS`, `PortfolioCalendarEventsTS` and
  `PortfolioEventLedgerTS` are storage contracts with the factories
  `configured_portfolio_rebalance_state_storage`,
  `configured_portfolio_calendar_events_storage` and
  `configured_portfolio_event_ledger_storage`. `PortfoliosUpdater` takes
  `weights_output_table=` and `rebalance_output_table=` for the
  `PortfolioWeights` and `PortfolioRebalance` updaters it builds, and
  `PortfolioWeights` takes `rebalance_output_table=`. Output tables do not
  enter `update_hash`, so no existing identity changes.
- [ADR 0047](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0047-markets-api-application-boundary/)
  proposes the
  Markets API as the application boundary: provider-owned namespaces and
  sidecars, a contracts package with a remote row backend, and contract-plus-
  instances for portfolio and signal time series catalogued by Markets. Its
  migration path step 1 is implemented in this release as described below,
  except per-service ownership and Team scoping policy, which is still open;
  the packaging split (step 2) and the provider and consumer moves (steps 3
  and 4) are not.
- `PortfoliosTS`, `PortfolioWeightsTS` and `SignalWeightsTS` are storage
  contracts with instances (ADR 0047, decision 5).
  `msm_portfolios.data_nodes.contract_instances` adds
  `configured_portfolios_storage`, `configured_portfolio_weights_storage` and
  `configured_signal_weights_storage`, which build an instance under a
  caller-chosen MetaTables namespace, physical-name app segment and optional
  SQLAlchemy base, with the contract's columns, dtypes, time index, index
  names and foreign keys and a stable identifier `<Contract>.<instance_key>`.
  The core tables remain the Markets-owned instance.
- `PortfolioDatasetAvailabilityTable` (`PortfolioDatasetAvailability`) catalogs,
  per portfolio, the values, weights and signal instance uids and the
  reconciled population state of the values instance, mirroring
  `IndexDatasetAvailability`. `SignalMetadataTable.meta_table_uid` records the
  signal's instance. Alembic revision `0021` creates the table and the column;
  no existing table, column or row changes.
- `msm_portfolios.services.portfolio_datasets` adds
  `register_portfolio_datasets`, `reconcile_portfolio_dataset_availability`,
  `list_portfolio_dataset_states` and `verify_contract_instance`. Registration
  verifies each declared table against the contract; reconciliation aggregates
  each instance once for all of its portfolios and records unreadable
  instances as `unavailable`.
- `apps.v1.identity` adds `acting_identity()`, the one place the Markets API
  decides whom a request acts for: `User.get_requester()` on a requester-bound
  call, `User.get_logged_user()` otherwise, never both, and `None` outside a
  request. `registry_write` wraps every API service that creates, updates or
  deletes a registry row (accounts, asset categories, assets, calendars,
  indexes, portfolio groups, portfolio signals, portfolios, pricing curves and
  pricing market data) and records the acting identity with the resource,
  action and row uid on the `apps.v1.identity` logger after a successful
  write. The Index routes derive their actor from the acting identity, so a
  requester-bound call acts for the requester.
- Markets API routes the ADR 0047 boundary needs: `POST /api/v1/account/`
  and `PATCH /api/v1/account/{uid}/` (account create and update over
  `msm.api.accounts`); `POST /api/v1/index/{uid}/formulas/`,
  `.../{definition_uid}/activate/`, `.../{definition_uid}/retire/`,
  `.../formulas/preview/` and `.../{definition_uid}/preview/` (formula save,
  activate, retire and preview over `FormulaIndex`, previews as
  `core.tabular_frame@v1`); `GET .../by-uids/?uid__in=` batch lookups for
  assets, accounts, portfolios and indexes (at most 500 uids, request order,
  unknown uids omitted, no paging or discovery); `GET /api/v1/portfolio/values/`
  and `GET /api/v1/portfolio/weights/` multi-portfolio frames grouped by
  catalogued table; and `POST /api/v1/portfolio/{uid}/datasets/`,
  `GET /api/v1/portfolio/{uid}/datasets/` and
  `POST /api/v1/portfolio/datasets/reconcile/` for the portfolio dataset
  catalog. All are registered in the Command Center adapter contract; the
  mutating ones record the acting identity. The by-uid lookups accept
  `include=<sidecar MetaTable uid>` and attach provider sidecar rows under
  `includes`, resolving the sidecar's foreign key to the core `uid` from the
  MetaTables catalog and reading each sidecar once (ADR 0047 `include`
  hydration; the Markets workload needs `data_viewer` on the sidecar).
- A design note for the contracts package split and `msm.client` (ADR 0047,
  decision 2) under `docs/planning/implementation_tasks/`; the README now
  describes `msm.client` as planned rather than shipped.
- The `markets-api` resource in `.mainsequence/workflows/ms-markets-api.yaml`
  declares `acts_for_requester: true`, so the platform signs the person an
  application works for into the caller assertion and the API acts for that
  requester (ADR 0047, decision 3). Caller-bound calls are unchanged. The
  declaration takes effect only when an Organization admin pushes it; a push by
  anyone else makes the `markets-api` resource fail before it deploys.
- `tests/identity/test_pinned_identities.py` pins the identities that a rename
  or a module move would rotate: the physical table name and MetaTable
  identifier of every library-owned model, the `module:qualname` of every
  shipped `TimeIndexTableUpdater` and `TimeIndexTableUpdateConfig` subclass
  (MetaTables hashes both into each producer's `update_hash`), and the
  `signal_uid` and portfolio configuration hash of fixed library and
  application signal configurations. Changing a pinned value is a deliberate
  identity rotation and belongs in this changelog.
- [ADR 0048](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0048-time-index-vocabulary-rename/)
  records the rename of the DataNode vocabulary to the MetaTables time-index
  terms: package and class names, UID columns named after the identity they
  hold, a 3.x deprecation window, and expand-then-contract column migrations
  across 3.0.0, 3.1.0, 4.0.0 and 4.1.0.
- `msm.identity` keeps the identities ms-markets derives stable when an updater
  or configuration class moves. `compute_signal_uid`,
  `compute_portfolio_configuration_hash` and the new
  `msm_portfolios.configuration.compute_strategy_revision` (which the portfolio
  engine now uses for ledger events) map moved class paths and nested updater
  hashes back to their pre-rename values before hashing. No class has moved
  yet, so every identity is unchanged; the pinned identity tests now also cover
  real updaters built offline, nested updater hashes, strategy revisions,
  factory-built storage tables and a simulated class move.
- Alembic revision `0022` adds `holdings_storage_table_uid`,
  `source_storage_table_uid`, `portfolio_weights_table_update_uid`,
  `signal_weights_table_update_uid`, `portfolio_table_update_uid` and an
  indexed `storage_table_uid` next to the pre-3.0 `*_data_node_uid` columns and
  copies their values. No row or pre-3.0 column changes. ms-markets 3.x writes
  both columns on every CRUD and repository write path
  (`msm.repositories.crud.mirror_renamed_columns`, driven by each model's
  `__renamed_columns__`) and reads the pre-3.0 columns until every writer runs
  3.x (ADR 0048).
- `msm rename-preflight` helps host projects move to the 3.0 names. `scan`
  lists pre-3.0 import paths, class names and UID field names with their
  replacements, including `getattr(..., "<pre-3.0 field>", default)` calls that
  4.0 would turn into silent defaults, and exits 1 while any remain.
  `rotation module:callable` reports each updater's new and pre-3.0
  `update_hash`. `account-uids` classifies the stored account and holdings-set
  UIDs as storage tables or table updates. The new
  [Upgrading To 3.0](https://mainsequence-projects.github.io/MainSequenceMarkets/upgrading-to-3/)
  page describes the upgrade order.

### Changed

- **Renamed packages and classes (ADR 0048).** `msm.data_nodes`,
  `msm_portfolios.data_nodes` and `msm_pricing.data_nodes` are now
  `msm.time_index`, `msm_portfolios.time_index` and `msm_pricing.time_index`,
  and `msm_portfolios.contrib.prices.data_nodes` is
  `msm_portfolios.contrib.prices.updaters`. `*DataNode` updaters are
  `*Updater`, `*DataNodeConfiguration` classes are `*UpdaterConfiguration`,
  `TargetPositionsDataNodeConfiguration` is `TargetPositionsConfiguration`, and
  `DiscountCurvesNode` and `FixingRatesNode` are `DiscountCurvesUpdater` and
  `FixingRatesUpdater`. Storage classes, physical table names and MetaTable
  identifiers are unchanged. The asset-indexed skill folder is now
  `assets/asset_indexed_updaters`; re-run `msm copy-msm-skills` to replace the
  old folder.
- **Identity rotation.** MetaTables hashes each updater's and each
  configuration class's import path into `update_hash`. Every producer whose
  class or configuration class moved, or that nests such a producer, gets a
  new `TimeIndexTableUpdate` on its first run under 3.0.0. The old record keeps
  its run history, and the producer continues from its output table's last
  observation. `signal_uid`, portfolio configuration hashes and rebalance
  strategy revisions do not change; `msm.identity` maps the moved paths back.
- **Renamed UID fields (ADR 0048).** Row APIs, payloads, repositories, services
  and HTTP responses use `holdings_storage_table_uid` (`Account`),
  `source_storage_table_uid` (`AccountHoldingsSet`),
  `portfolio_weights_table_update_uid`, `signal_weights_table_update_uid` and
  `portfolio_table_update_uid` (`Portfolio`), and `storage_table_uid`
  (`PricingMarketDataSetBinding` and the curve and resolve responses).
  `PricingMarketDataConfiguration.data_node_uids` is `storage_table_uids`,
  `PricingMarketDataSetBinding.resolve_data_node_uid` is
  `resolve_storage_table_uid`, `direct_data_node_uid_for` is
  `direct_storage_table_uid_for`, and the virtual-fund allocation methods take
  `updater=` instead of `data_node=`. Rows read the pre-3.0 column, which 2.x
  writers still update. Portfolio detail fields use the new keys and the
  labels "Portfolio Weights Table Update", "Signal Weights Table Update" and
  "Portfolio Values Table Update"; the Command Center binding column is
  `storage_table_uid`. Missing-curve messages call the bound UID a storage
  table instead of a TimeIndexTableUpdater.
- `portfolio_values`, `latest_portfolio_weights` and the new `signal_weights`
  read in `msm_portfolios.services.portfolio_reads` resolve each portfolio's
  table from the catalog and read it by uid through `TimeIndexTableRef`,
  filtered by `portfolio_identifier` or `signal_uid`. Portfolios without a
  catalog row read the core tables as before. A request for several portfolios
  groups them by table uid, reads each table once and returns one ordered
  list. `latest_portfolio_weights` gains `order`, and the reads accept a
  `dataset_reader` for tests. The portfolio values, weights and signal-weight
  API routes use these reads. The `apps/v1` runtimes attach
  `PortfolioDatasetAvailability`.
- ms-markets requires `mainsequence-metatable>=0.1.57,<0.2` (was `>=0.1.51`).
  0.1.57 is the first MetaTables release that computes the `update_hash` of an
  updater whose configuration holds a `datetime.date` or `datetime.time`.

### Deprecated

- The pre-3.0 import paths `msm.data_nodes`, `msm_portfolios.data_nodes`,
  `msm_pricing.data_nodes` and `msm_portfolios.contrib.prices.data_nodes`, with
  every submodule, are aliases of the renamed modules through 3.x. They
  re-export the same objects and raise a `DeprecationWarning` at the importing
  line. The pre-3.0 class names, such as `AssetIndexedDataNode`,
  `PortfoliosDataNode` and `DiscountCurvesNode`, resolve from those paths and
  from `msm_portfolios` with a warning. Stored configurations that name the old
  paths still rebuild. ms-markets 4.0 removes the aliases.
- The pre-3.0 UID field names (`holdings_data_node_uid`,
  `source_data_node_uid`, `portfolio_weights_data_node_uid`,
  `signal_weights_data_node_uid`, `portfolio_data_node_uid` and
  `data_node_uid`) stay readable on rows and in every HTTP response, where
  OpenAPI marks them deprecated, and requests, payloads, row writes and
  repository builders accept them with a `DeprecationWarning`.
  `data_node_uids`, `resolve_data_node_uid`, `direct_data_node_uid_for`,
  `data_node=` and `msm.settings.markets_data_node_identifier` are deprecated
  aliases. ms-markets 4.0 removes them.

### Fixed

- Every hosted rollout since 2026-10-21 stopped at the `migrate-markets` Job
  with `No package metadata was found for ms-markets`. Main Sequence images no
  longer install the repository itself (platform ADR-080); Jobs and the Markets
  API import it from `/workspace`. `msm`, the API and the CLI now read the version
  through `msm.distribution.package_version()`, which falls back to the
  checkout's `pyproject.toml` when the distribution is not installed.

- `requirements.txt`, the only dependency input of a Main Sequence image, still
  pinned `mainsequence-metatable==0.1.51` after the floor moved to 0.1.57, so the
  image lacked `metatables.envelope_contract`. It is regenerated with
  `mainsequence code-repository sync`, and a test now fails when its pins differ
  from `uv.lock`.

- A storage instance built on a provider's declarative base copied each
  referenced Markets table whole, with that table's own foreign keys to tables
  that were not copied, so the provider's `metadata.sorted_tables` and Alembic
  autogenerate failed with `NoReferencedTableError`. The provider's metadata now
  holds only the referenced key columns of each Markets table
  (`msm.storage_instances.markets_reference_table`).

- Building a storage instance on a provider's declarative base raised
  `TypeError: Boolean value of this clause is not defined` once the base already
  held a copied foreign-key target (any table with two foreign keys to one
  Markets table, such as trades or the event ledger, or a second instance on the
  same base); the copied target is now reused. `msm.start_engine` accepts such
  instances: they are not `MarketsBase` subclasses but carry the Markets mixins.
- The portfolio guide's provider example passed `namespace=` to
  `PortfoliosUpdater`, which is the hash namespace and rotates `update_hash`.

- Under the remote backend, `PersistedCalendarSchedule.schedule` (calendar-relative
  rebalancing) and `FormulaIndex.activate()`/`retire()` ran compiled SQL in the
  calling process and failed; they now run through dispatched row methods.
- `Index.upsert_many` now applies `Index.upsert`'s `calculation_method` guard
  to every existing index.
- A holdings snapshot read scanned at most 500 holdings rows in no order, so
  for a larger account the latest (or earliest) snapshot could be missed. The
  scan is ordered by time, and a dated read filters on that date.

- UID column labels and descriptions name the identity each column holds.
  The three `PortfolioTable.*_data_node_uid` columns are labelled as
  `TimeIndexTableUpdate` uids, which is what the portfolio updaters write.
  `PricingMarketDataSetBindingTable.data_node_uid` is labelled as the storage
  table uid it is resolved through. `AccountTable.holdings_data_node_uid` and
  `AccountHoldingsSetTable.source_data_node_uid` describe `TimeIndexMetaTable`
  uids, as their original `DataNodeStorage` descriptions did, instead of being
  labelled as updater uids. The Command Center market-data binding columns
  read "Storage table UID", and the API settings namespace assumption names
  time-index table updaters instead of DataNodes. Column names, API fields and
  MetaTable contract hashes are unchanged; the catalog refreshes the labels on
  the next migration finalization.
- `docs/concepts.md` describes timestamped data in MetaTables terms: a
  `PlatformTimeIndexMetaTable` storage class written by a
  `TimeIndexTableUpdater` producer, instead of a single DataNode storage
  contract.
- `include` on the by-uid lookups no longer returns application-encrypted
  sidecar columns. Markets skips every column the MetaTables catalog marks with
  `encryption` (MetaTables ADR 0025) and drops any value that is an `mt1.`
  encryption envelope, so a provider can grant the Markets workload
  `data_viewer` on a sidecar that holds credentials without its ciphertext
  reaching Markets responses. A sidecar whose join column is encrypted is
  refused.
- `from <pre-3.0 module path> import <name>` no longer recurses forever. The
  import system probes `__path__` on every from-import, and the deprecated
  alias modules treated that dunder as a submodule to import, which probed
  `__path__` again. Aliases now answer dunder lookups with `AttributeError` and
  try submodule imports only for package aliases. Every module alias is tested
  with a from-import.
- Portfolio, portfolio-weights, signal and signal-weights deletes respect the
  ADR 0047 catalog. They used to touch only the core tables, so a portfolio
  catalogued in another application's contract instance reported zero rows
  deleted and kept its data. `DELETE /portfolio/{uid}/weights/` and
  `DELETE /portfolio-signal/{uid}/weights/` now return 409 and delete nothing
  when the weights live in a table another application owns
  (`PortfolioDatasetOwnershipError`, `SignalDatasetOwnershipError`). Portfolio
  and signal deletes, including bulk and cascade, still delete the Markets rows
  and any core rows, and list each table they left in place in a new
  `retained_datasets` field. The bulk-delete preflight warns about those tables.
  A catalog row that names the core table counts as core.
- `compute_portfolio_configuration_hash` and `compute_signal_uid` no longer
  raise `TypeError` when a configuration holds a `datetime.date` or
  `datetime.time`, such as the execution window of `TimeWeighted`,
  `VolumeParticipation` and `TrailingAverageDailyVolumeParticipation`. The
  canonical signal, portfolio and rebalance strategy payloads carry these values
  as ISO strings. Configurations that hashed before keep their identities, and
  rebalance strategy revisions do not change. With MetaTables 0.1.57, which
  ms-markets now requires, `PortfolioWeights` and `PortfoliosUpdater` also
  compute their `update_hash` for a portfolio that uses one of these
  strategies, instead of raising the same `TypeError`.

## [2.2.12] - 2026-10-22

- Require certifi 2026.10.19 or newer so downstream installs receive the corrected
  CA bundle; refresh the matching lock/export pins.
- Use Python 3.13.17 and patched pip/uv bootstrapping in CI. This release changes
  dependency security requirements without changing application APIs.

## [2.2.11] - 2026-10-21

### Changed

- Requires `mainsequence>=9.0.29,<10` and `mainsequence-metatable>=0.1.51,<0.2`; the
  lock and exported `requirements.txt` select `mainsequence` 9.0.30,
  `mainsequence-metatable` 0.1.51 and, through them, `mcp` 2.3.0. SDK 9.0.24 and
  earlier refuse the platform's identity-only caller assertions, so the Markets API,
  locked at 9.0.19, answered `401` to every signed request; SDK 9.0.25 and 9.0.26 raise
  when code reads the request identity's `team_uids`; and MetaTables clients before
  0.1.51 fail on SDK 9.0.30. This release adds no Alembic revision.
- The deployment workflow uses workflow API `3.0.0`, the only version the platform
  accepts: `markets-api` and `migrate-markets` declare `policy: reader` on the
  MetaTables branch, the conversion of their former `level: view`.
- MetaTables access follows its namespace and table roles (MetaTables ADR 0024). On
  `mainsequence.markets` the `migrate-markets` Job holds `editor`, the `markets-api`
  release `data_writer`, and a person or a people-only Team `owner`; the namespace's
  owners grant these in each Environment. The release, migration and FastAPI guides
  and the packaged `metatable_migrations` skill describe them, with the roles consuming
  projects need: `editor` for migration Jobs that register tables in
  `mainsequence.markets`, table `editor` on their outputs plus `data_viewer` for
  updater producers, `data_writer` for row writers and `data_viewer` for readers.
- `IndexActor.team_uids` is deprecated and empty for HTTP callers, because caller
  assertions name no Teams. The Index actor never reads the request identity's
  `team_uids`; an SDK `User` still contributes its `organization_teams`. No Index
  operation authorizes by Team.
- Canonical Index dataset discovery no longer reports `can_edit=True` to the user who
  registered the table, because registering grants no MetaTables role by itself.
  `can_edit` is `None`; the platform checks edit access when a change runs.
- `get_openfigi_api_key()` raises `OpenFigiConfigurationError` naming `value_reader` on
  `OPEN_FIGI_API_KEY` when the caller may not read the Secret's value. Its
  missing-Secret message also says that a Secret is hidden from a caller without a
  policy on it. A deployment that calls OpenFIGI declares
  `secrets: [{name: OPEN_FIGI_API_KEY, policy: value_reader}]`.
- Test fixtures sign identity-only caller assertions, and a test checks that an
  assertion listing `team_uids`, for the caller or for a requester, is refused.
- Refreshed the copied Main Sequence SDK skills to 9.0.30 and the MetaTables skills to
  0.1.51 (0.1.35 dropped the retired `metatables-upgrade-legacy-app` skill), and removed
  the retired managed block from `AGENTS.md`: `mainsequence code-repository update` no
  longer exists.

### Removed

- `scripts/bootstrap_metatables_access.py` and its tests. It called Team bulk-member
  and MetaTables Reader/Writer routes that no longer exist, and roles replace its Team
  Writer model. `mainsequence.markets` exists in the development and Production
  Environments, and its owner grants the roles above.

## [2.2.10] - 2026-10-11

### Fixed

- Retry read-only API startup attachment after explicit temporary gateway authentication
  or MetaTables wake failures within one 300-second budget. Production previously exited
  on the first transient `503`; invalid credentials, permissions, schema errors, and
  persistent failures still prevent startup. Normal request behavior is unchanged.

## [2.2.9] - 2026-10-11

### Fixed

- Give FastAPI startup an explicit 300-second MetaTables discovery scope for
  canonical and pricing runtime attachment. A waking shared API previously
  exhausted the ordinary 30-second budget and failed development rollout.
  Startup still propagates attachment errors; normal request budgets are unchanged.

### Changed

- Document the shared MetaTables API 0.1.34 dependency for finalizing the
  populated legacy TimescaleDB schema after the committed `0020` upgrade. Its
  ownership-before-conversion repair preserves rows without adding internal
  schema grants. Retry through the hosted migration Job; client requirements,
  applied Alembic revisions, and development tables remain unchanged.

## [2.2.8] - 2026-10-11

### Fixed

- Give the hosted migration Job an explicit 300-second MetaTables discovery
  scope, so waking APIs receive the documented migration wait budget instead
  of the ordinary 30 seconds. Schema and catalog errors still fail the Job;
  the data-preserving `0017` bridge and applied revisions stay unchanged.

## [2.2.7] - 2026-10-11

### Fixed

- Restore a forward upgrade for populated PostgreSQL databases at the retired
  `0017` head, which blocked the Production API rollout. A compatibility anchor
  and merge revision `0020` join that history with development's `0018`/`0019`
  without changing those applied revisions or replacing application tables.
- Validate all 62 application table column contracts before reconciliation;
  refuse overlong identifiers, bound only ten known legacy string columns, and
  verify locked tables' row counts and checksums remain unchanged. Extra tables
  and columns are preserved. Already-bounded development needs no alterations.
- Add original-history PostgreSQL data-preservation and failure regressions,
  fresh/development upgrade checks, and matching migration guide, release
  instructions, ADR 0046, tutorial, and print-only lifecycle example.

## [2.2.6] - 2026-10-10

### Added

- `scripts/bootstrap_metatables_access.py` gives the deployment's workload Users
  Writer on the `mainsequence.markets` MetaTables namespace in one Environment, for
  an Organization admin to run once from a checkout of `development` or `main`.
  It creates the Team `ms-markets-<environment>` from the checkout's Environment
  name, adds the migration Job's and FastAPI release's workload Users from the
  deployment workflow, creates the namespace if it is missing and grants the Team
  Writer on it. Every other grant is kept, and `--dry-run` only reports. Without
  this grant the migration Job could not register tables. In `development` it got
  `422 MetaTable is not editable` on `msm.alembic_version`, which a previous runtime
  identity had registered. See [MetaTables#43](https://github.com/mainsequence-projects/MetaTables/issues/43)
  and "MetaTables access in each Environment" in `docs/releasing.md`.

### Changed

- Requires `mainsequence-metatable>=0.1.33,<0.2`; the lock and runtime export
  select 0.1.33, while Main Sequence remains 9.0.19. The shared migration runner
  batches table inventories and inspections and waits up to 300 seconds for a
  waking API, addressing the 30-second discovery timeout in the failed Markets
  deployment ([MetaTables#55](https://github.com/mainsequence-projects/MetaTables/pull/55)).
  Server-side batching, unchanged-contract write avoidance, and startup
  improvements also require deployment of the updated shared MetaTables API.
- The upgraded migration runner carries changed, non-empty authored table and
  column metadata through finalization at an unchanged Alembic revision. Empty
  values preserve existing catalog metadata and equal-valued reruns avoid
  catalog writes. The matching API update is required for this payload; it also
  fixes SQLite schema reflection during multi-batch downgrade finalization
  ([MetaTables#59](https://github.com/mainsequence-projects/MetaTables/pull/59)).
- The migration Job exposes the shared runner's INFO phase timings, always
  reconciles the catalog even at head, and propagates failures to block rollout.
  Provider identity, version-table binding, and applied revisions are unchanged.
- Refreshed the MetaTables-owned skills and guide snapshots to 0.1.33; aligned
  migration documentation, release guidance, tutorial, and print-only example.
- Requires `mainsequence-metatable>=0.1.29,<0.2`; the lock and exported
  `requirements.txt` select 0.1.29. Changes in MetaTables 0.1.29
  ([MetaTables#52](https://github.com/mainsequence-projects/MetaTables/pull/52)):
  - Hosted migrations no longer create application tables in the `metatables`
    catalog schema. The migration connection pins `search_path=public`, the
    client checks it, and the PostgreSQL version table is always schema-qualified
    ([MetaTables#50](https://github.com/mainsequence-projects/MetaTables/issues/50)).
    The first ms-markets migration in `development`, on 2026-10-03, had created
    all its tables in `metatables`, so every later migration found its version
    table at head, ran no DDL and failed finalization. MetaTables removed those
    tables, so the next deployment creates them in `public`.
  - Before issuing a migration connection, the API refuses misplaced provider
    tables with `provider_tables_misplaced`.
  - Finalization deletes a catalog binding only for a table the client names as
    removed. It no longer drops the bindings of current tables it can't find.
  - The vendored MetaTables agent skills are refreshed to 0.1.29.
- Requires `mainsequence-metatable>=0.1.28,<0.2`; the lock and exported
  `requirements.txt` select 0.1.28. Changes in MetaTables 0.1.28
  ([MetaTables#49](https://github.com/mainsequence-projects/MetaTables/pull/49)):
  - The client finalizes at most 10 tables per request, the Alembic version
    table first. A rerun of the migration Job finalizes whatever an
    interrupted run left. Finalizing all 62 ms-markets tables in one request
    ran past the hosted request limit, so the migration could never finish
    ([MetaTables#46](https://github.com/mainsequence-projects/MetaTables/issues/46)).
  - The hosted API reuses connections and serves concurrent requests on more
    resources, so a long request no longer leaves it refusing connections
    ([MetaTables#45](https://github.com/mainsequence-projects/MetaTables/issues/45)).
  - A busy API answers `503` `database_connections_busy` with `Retry-After`;
    nothing ran, and the call can be retried.
  - The vendored MetaTables agent skills are refreshed to 0.1.28.
- Requires `mainsequence-metatable>=0.1.27,<0.2`; the lock and exported
  `requirements.txt` select 0.1.27. Changes in MetaTables 0.1.27
  ([MetaTables#44](https://github.com/mainsequence-projects/MetaTables/pull/44)):
  - One platform Team per Environment owns an application's tables, with the
    application's workload Users as members. This is what
    `scripts/bootstrap_metatables_access.py` sets up.
  - A table registered in a namespace the caller already writes gets no grant of
    its own.
  - A refused registration answers `403` `table_not_editable` or
    `namespace_not_writable`, with the caller's User UID.
  - The vendored MetaTables agent skills are refreshed to 0.1.27. The
    `metatables-migrations` skill makes the per-Environment Team a deployment
    step.
- Requires `mainsequence>=9.0.19,<10` and `mainsequence-metatable>=0.1.26,<0.2`;
  the lock and exported `requirements.txt` select `mainsequence` 9.0.19 and
  `mainsequence-metatable` 0.1.26. MetaTables 0.1.24 and later require
  `mainsequence[mcp]>=9.0.19` and always install `fastembed`, so `onnxruntime`,
  `tokenizers`, `huggingface-hub` and `mcp` are new runtime dependencies (about
  100 MB installed). The API does not import them at startup. No ms-markets
  code uses an API that changed in this range.
- The local MetaTables API is now one per laptop. After upgrading, restart
  `metatables serve --local` and apply the local system migration
  `0011_table_search` (`metatables --local runtime upgrade`); projects on
  MetaTables 0.1.21 or earlier then fail against the shared local file.
- Every request to the Markets API is authenticated before its handler (see
  Fixed). A local request must send the signed-in user's
  `Authorization: Bearer` token, which is checked against
  `MAINSEQUENCE_ENDPOINT`; without one it receives `401`.
- Refreshed the Main Sequence SDK agent skills and the managed `AGENTS.md`
  block to 9.0.19, and the MetaTables agent skills to 0.1.26. The 0.1.18
  MetaTables skills said registered foreign keys must use `RESTRICT` or
  `NO ACTION`; 0.1.26 allows any referential action, including the cascades
  ms-markets declares.

### Fixed

- Repair the portfolio event ledger's TimescaleDB-incompatible non-time unique
  constraint through forward migration `0019`, preserving applied `0018`, all
  existing rows, and full-grain uniqueness. Canonical publication, restart, and
  projections reject duplicate economic record identities across timestamps
  and event revisions split across times. Exact retries remain idempotent.
- Align ADR 0042, accounting and migration documentation, the portfolio tutorial,
  and the offline dividend/FX example with the storage and validation boundary.
- The Markets API installs the SDK request identity with
  `install_request_identity(app)` in `create_app()`. The platform launcher
  refuses to serve an application that does not install it, and SDK releases
  before 9.0.18 reject the platform's current caller assertions. Handlers read
  the verified caller from `request.state.user`, which the platform never
  injected, so the Index routes treated every hosted request as anonymous.
- The Index actor takes its Teams from the request identity's `team_uids`. It
  read `organization_teams`, which a request identity does not have, so an
  HTTP caller's Teams were always empty.
- The `markets-api` release and the `migrate-markets` Job declare
  `access.branches` view on the MetaTables repository in the deployment
  workflow, and the platform grants it to their workload Users on every push.
  They run as their own workload Users, and MetaTables API discovery failed
  without that access: "No visible FastAPI deployment named 'metatables'",
  then "Cannot verify the Environment of every visible API deployment".
- `msm_portfolios.utils.get_portfolios_logger()` returns the logger bound with
  `sub_application="portfolios"`. It discarded the result of `.bind()` and
  returned the unbound SDK logger, so `msm_portfolios.utils.logger` and the
  `msm_portfolios.configuration` logger never carried the binding.
- `examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` runs the
  dynamic Alembic revision and upgrade through the `metatables migrations` CLI.
  It invoked `python -m mainsequence migrations ...`, which the SDK no longer
  provides, so schema preparation failed unless `--check-only` was set.
- Removed a stray module-level developer note from
  `msm_portfolios/configuration.py` that referenced the retired SDK
  `data_publishing` skill by a local absolute path.

## [2.2.5] - 2026-10-04

### Fixed

- `TabularFrameResponse` and its field, source, time-series and table-visual
  models omit unset optional fields instead of serializing them as `null`,
  which the `core.tabular_frame@v1` schema rejects. A plain dump of
  `build_tabular_frame(...)` failed the schema on `error`, `meta`, `source`
  and the field `label`, `provenance`, `derivedFrom` and `warnings`; only routes
  declared with `response_model_exclude_none=True`, as every ms-markets frame
  route is, returned a valid frame. `null` cell values in `rows` are kept. A
  test fails if any optional field of the bulk-action, resource-collection or
  tabular-frame contract models serializes as `null`, other than
  `BulkDeletePreflightResponse.impact`, and the Command Center connection
  contract is validated against the Adapter from API discovery schema.

## [2.2.4] - 2026-10-04

### Fixed

- `BulkActionDefinition` omits `tone`, `confirmation` and `preflight_endpoint`,
  and `BulkActionPreflightResponse` omits `detail`, `matched_count`, `blockers`
  and `warnings`, when they are unset, instead of serializing them as `null`.
  The Command Center SDK accepts these fields only when they are absent or
  valid, so a discovery route that advertised an action without a `tone` or
  `confirmation` failed with "Bulk-action discovery returned an invalid action
  definition.", and a preflight that left any of those fields unset failed to
  parse ([#22](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/22)).
  The ms-markets bulk-delete routes set every field and were not affected. A
  contract test dumps the resource-discovery and preflight models with only
  their required fields and checks that the output has no `null` values and
  validates against the pinned SDK schemas.

## [2.2.3] - 2026-10-03

### Added

- The portfolio, portfolio-group and asset-category bulk-delete preflights
  report what the delete reaches through foreign keys. They return the
  MetaTables `delete_rows` impact as `impact` and describe each cascade,
  `SET NULL` or `SET DEFAULT` action in `warnings`. MetaTables' blockers (the
  caller cannot write the table, the table does not accept writes, or its
  DataSource is read-only) are added to `blockers` and also stop the bulk
  delete with `409`; cascades never block. If MetaTables cannot compute the
  impact, a warning says so and the delete is not blocked.
  `BulkDeletePreflightResponse` and the `TableImpact` models are exported from
  `msm.api.http`, and `delete_rows_impact` from `msm.services`.

### Changed

- Requires `mainsequence-metatable>=0.1.18,<0.2`; the lock and exported
  `requirements.txt` select `mainsequence-metatable` 0.1.18. MetaTables 0.1.18
  removes the cascade write narrowing released in 0.1.17: write on a table
  depends only on its own grants, so a foreign key on a referencing table no
  longer locks the referenced table's Writers out. Its impact pre-flight
  reports cascades as information, never as blockers.
- Refreshed the MetaTables agent skills to 0.1.18.

## [2.2.2] - 2026-10-03

### Changed

- Requires `mainsequence-metatable>=0.1.17,<0.2`; the lock and exported
  `requirements.txt` select `mainsequence-metatable` 0.1.17. Earlier releases
  refuse to finalize tables with cascading foreign keys
  (`cascading_foreign_key_unsupported`), so the ms-markets provider could not
  finish `migrations upgrade`. MetaTables 0.1.17 allows them: writing a table
  requires write access on every table its cascades modify. The ms-markets
  cascades are unchanged.
- Refreshed the MetaTables agent skills to 0.1.17. They document explicit
  `__storage_layout__` names, cascading foreign keys and the `get_impact`
  pre-flight.

### Fixed

- `PortfolioEventLedgerTS` declares an explicit `__storage_layout__` whose
  lookup index is named `portfolio_event_ledger_identity`. The default layout
  derived a 70-character name from its four identity dimensions, which
  MetaTables rejects (it never shortens derived names), so the ms-markets
  migration provider could not be applied in any new environment
  ([#19](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/19)).
  A test runs the MetaTables layout check on every provider time-index model.

## [2.2.1] - 2026-10-03

### Changed

- The VS Code launch configurations and tasks that check, apply and downgrade
  migrations pass `--local`, so they act on the local runtime instead of
  whichever MetaTables API the SDK environment resolves, and their names say
  so.

### Documentation

- The FastAPI deployment docs describe workflow API 2.3.0 and its
  `image` → `migrate` → `deploy_api` graph, and say that publishing is a plain
  `git push`. Since Main Sequence SDK 9.0.5, `mainsequence code-repository sync`
  only refreshes `uv.lock`, the environment and `requirements.txt`; it no longer
  bumps, tags, commits or pushes.
- Every developer migration command targets the local runtime
  (`metatables --local`), including the ADR 0045 reset path. Hosted
  environments are migrated only by the deployment workflow's Job.
- Downstream projects declare their own migration provider and version table.
  The MetaTable migration, portfolio accounting and asset-indexed storage
  guides, the pricing tutorial and the bootstrap, index and
  `metatable_migrations` skills no longer suggest extending the ms-markets
  revision graph or applying `msm_migrations:migration` outside the ms-markets
  deployment.
- MetaTable registration no longer describes the removed catalog projection
  hook, and the `metatable_migrations` skill's project provider example uses
  the locations `metatables migrations scaffold --module` derives.
- Refreshed the MetaTables agent skills to 0.1.14 and the managed `AGENTS.md`
  section from SDK 9.0.5; the SDK skill bundle is unchanged.

## [2.2.0] - 2026-10-03

### Removed

- **Breaking:** the `msm_command_center` package is removed. Import the
  `core.tabular_frame@v1` models and helpers (`TabularFrameResponse`,
  `TabularFrameMetaResponse`, `TabularFrameFieldResponse`,
  `TabularFrameSourceResponse`, `build_tabular_frame`, `build_tabular_field`,
  `CORE_TABULAR_FRAME_CONTRACT`) from `msm.api.http`. `infer_tabular_field_type`
  is removed.
- **Breaking:** `build_asset_monitor_frame` and
  `build_asset_monitor_workspace_document` are removed. `getAssetMonitorFrame`
  builds its frame inside `apps/v1` and its response is unchanged; workspace
  documents are not built by this library.
- **Breaking:** fixed income pricing support no longer returns
  `response_mappings`, and the cashflow response schemas no longer carry
  `x-response-mappings`. Command Center SDK 0.1.13 retired response mappings;
  bind the `cashflows/frame/` and `net-cashflows/frame/` routes instead.
- **Breaking:** `getAssetMonitorFrame` returns only the `uid`,
  `unique_identifier`, and `asset_type` columns, and its `meta.marketAsset` no
  longer names a `tickerField`. The removed `ticker`, `name`, `figi`,
  `composite_figi`, `exchange_code`, `security_type`, `security_market_sector`,
  and `currency` columns were always null: the asset list does not load them.
- The `apps/v1` re-export modules are removed: `apps.v1.schemas.command_center`,
  `apps.v1.schemas.resource_contracts`, `apps.v1.schemas.bulk_actions`,
  `apps.v1.services.resource_collections`, `apps.v1.services.bulk_actions`, and
  the `ErrorResponse` re-export in `apps.v1.schemas.common`. Import from
  `msm.api.http`.
- The Command Center Asset Monitor skills are removed.

### Changed

- Adapter from API discovery takes an operation's `responseContract` only from
  its `x-ui-contract` declaration; it no longer infers `core.tabular_frame@v1`
  from a response model named `TabularFrameResponse`. Every frame route already
  declares it, so the advertised contracts are unchanged.
- Requires `mainsequence-metatable>=0.1.14,<0.2`; the lock and exported
  `requirements.txt` select `mainsequence-metatable` 0.1.14. MetaTables 0.1.13
  and 0.1.14 change only how a failed runtime database bootstrap names its cause.

## [2.1.2] - 2026-10-03

### Changed

- Releases follow the MetaTables branch model. Every push to `development`
  publishes an `X.Y.Z.devN` build to PyPI. `main` is protected, and each merged
  pull request from `development` publishes the declared `X.Y.Z`, creates the
  `vX.Y.Z` tag and GitHub release, deploys the documentation and returns the next
  patch version to `development`. Pushing a `v*` tag no longer publishes.
- Pull requests and both publishing workflows run `Package and static checks`:
  the lockfile, Ruff, the strict documentation build, the full test suite, and a
  distribution check that the wheel and sdist match the current sources.
- The `dev` extra adds `build`, `packaging` and `twine>=7`. twine 6 rejects the
  `Metadata-Version: 2.5` that hatchling writes.

### Documentation

- Added the [Releasing](https://mainsequence-projects.github.io/MainSequenceMarkets/releasing/)
  guide.

## [2.1.1] - 2026-10-03

### Changed

- Renamed the deployment workflow file from `.mainsequence/workflows/fastapi.yaml`
  to `.mainsequence/workflows/ms-markets-api.yaml`. Its `name`, resources and
  execution graph are unchanged.

### Fixed

- `api_http_error` maps the SDK `ConflictError` to a non-retryable `409`
  `conflict` response with a fixed message, instead of a retryable `503`
  `dependency_unavailable`. Fixes
  [#13](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/13).

### Documentation

- Aligned the migration docs and examples with the MetaTables 0.1.12 guidance:
  manual `upgrade`/`downgrade` commands target the local runtime (`--local`),
  hosted schema changes come from the `migrate-markets` deployment Job, raw
  PostgreSQL SQL in a revision must branch on the dialect, and the 2.1.0
  `0018_initial_schema` squash replaces the old revision history. The documented
  client requirement is `mainsequence-metatable>=0.1.12,<0.2`. Refreshed the
  MetaTables agent skills to 0.1.12.
- Withdrew the 2.1.0 instruction that applications reading ms-markets tables
  apply `msm_migrations:migration` in their own migration Job. The migration
  docs and the shipped `metatable_migrations` skill now state that only the
  ms-markets deployment's `migrate-markets` Job migrates the ms-markets schema;
  other applications apply only their own providers.

## [2.1.0] - 2026-10-03

### Changed

- **Breaking:** the migration history is one revision, `0018_initial_schema`,
  generated from the models; `0001`–`0017` are removed, which withdraws the
  2.0.2 promise that they stay unchanged. No old ID is reused, so a database at
  any of them fails with an unknown-revision error instead of passing as
  head. Downgrade it to `base` with 2.0.x installed, then apply 2.1.0 from empty.
  The provider key, `MarketsAlembicVersion` and its table are unchanged. The
  history now builds on the MetaTables local SQLite runtime as well as PostgreSQL
  ([ADR 0045](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0045-squashed-initial-schema-and-namespaced-packages/),
  #12, #15).
- **Breaking:** the `cli` and `command_center` packages are renamed `msm_cli` and
  `msm_command_center`, and bundled skills ship inside `msm_cli/_skills`. The
  wheel installs only `msm*` packages; the `msm` console script is unchanged
  (#14).
- Requires `mainsequence>=9.0.5,<10` and `mainsequence-metatable>=0.1.12,<0.2`;
  the lock and exported `requirements.txt` select `mainsequence` 9.0.5 and
  `mainsequence-metatable` 0.1.12.
- The Markets API deployment workflow (`.mainsequence/workflows/fastapi.yaml`)
  moves to workflow API 2.3.0 and runs a migration Job,
  `jobs/migrate_markets.py`, from the candidate image before the API deploys. The
  Job applies `msm_migrations:migration` with
  `metatables.upgrade_application(...)`; a failed migration blocks the rollout.
- Migration docs and the shipped `metatable_migrations` skill scope manual
  `metatables migrations upgrade` to the local runtime (`--local`). Hosted
  environments are migrated only by the deployment workflow's Job, and
  applications that deploy code reading ms-markets tables apply
  `msm_migrations:migration` in their own migration Job first.

## [2.0.2] - 2026-10-02

### Changed

- **Breaking:** the Alembic migration provider moved from the top-level
  `migrations` package to `msm_migrations`, and the wheel no longer installs a
  top-level `migrations` package. Use
  `metatables migrations ... --provider msm_migrations:migration`;
  `msm.migrations:migration` remains a compatibility alias. The provider key
  `msm:<namespace>`, `MarketsAlembicVersion`, and revisions `0001`–`0017` are
  unchanged, so existing databases continue from their current revision. See
  [ADR 0044](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0044-namespaced-migration-provider-package/)
  and [#14](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/14).
- The provider now sets `version_location_prefix="msm_migrations:versions"`
  instead of relying on the client default `migrations:versions`.

### Removed

- The unreachable `versions/default` revision directory and the redundant
  `script.py.mako` wheel force-include.

## [2.0.0] - 2026-10-01

Breaking release for Main Sequence SDK 9, which moved MetaTables out of the SDK
into the separate `mainsequence-metatable` client (imported as `metatables`).
See
[ADR 0043](https://mainsequence-projects.github.io/MainSequenceMarkets/ADR/0043-sdk-9-metatables-client-hard-cut/).

### Changed

- **Breaking:** requires `mainsequence>=9.0.2,<10` and
  `mainsequence-metatable>=0.1.6,<0.2`. SDK 8 and earlier are unsupported; stay
  on `ms-markets` 1.x for SDK 8 projects. Dependent packages declare
  `ms-markets>=2,<3`. `mainsequence-metatable` requires SQLAlchemy 2.1, whose
  PostgreSQL compiler renders typed bind casts such as
  `%(direction_0)s::SMALLINT` in compiled SQL.
- **Breaking:** MetaTables imports moved from `mainsequence.meta_tables`,
  `mainsequence.client.metatables`, `mainsequence.client.dtype_codec`, and
  `mainsequence.client.BaseUpdateStatistics` to the `metatables` public exports;
  `mainsequence.meta_tables.time_index_table_updates.<module>` moved to
  `metatables.updaters.<module>`; migration helpers moved to
  `metatables.migrations`; the compiler moved to `metatables.compiled_sql.v1`.
  Types in ms-markets signatures (`MetaTable`, `TimeIndexMetaTable`,
  `MetaTableCompiledSQLOperation`, `MetaTableOperationLimits`,
  `UpdateStatistics`, `BaseUpdateStatistics`, `TimeIndexTableUpdater`,
  `TimeIndexTableRef`, `PlatformManagedMetaTable`, `PlatformTimeIndexMetaTable`,
  and the updater configuration classes) are now the `metatables` classes.
- **Breaking:** `msm.repositories.base.compile_markets_statement(statement, *,
  context, operation, models, access)` is now
  `compile_markets_statement(statement, *, context, operation, dialect=None)`.
  The `models=` and `access=` parameters were removed with the SQL operation
  scope; passing them raises `TypeError`. The compiled operation carries
  `data_source_uid` at top level and has no `scope`. ms-markets leaves
  `context.data_source_uid` as `None`, so the compiler takes the DataSource and
  the SQL dialect together from the runtime of the MetaTables API that the
  caller's Organization Environment selects; no API URL or DataSource setting
  is needed. A runtime without a usable DataSource raises
  `metatables.DataSourceResolutionError`, and an explicit `data_source_uid`
  that differs from the runtime is rejected unless `dialect=` is also passed
  for offline compilation. Limits, offsets, statement deadlines, HTTP
  timeouts, and the `select` (read) versus other labels (write) execution
  semantics are unchanged.
- **Breaking:** `MarketsRepositoryContext` no longer accepts or exposes
  `reserved_policy` and no longer has `scope_table(...)`.
  `MarketsMetaTableHandle` no longer has the `reserved_policy` field,
  `scope_table(...)`, or `meta_table_uid_for_model(...)`. Kept:
  `MarketsRepositoryContext(limits=, data_source_uid=, timeout=, namespace=)`,
  `MarketsRepositoryContext.meta_table_uid_for_model(...)`,
  `MarketsRepositoryContext.table(...)`, and `MarketsMetaTableHandle.meta_table_uid`.
- **Breaking:** `AssetReferenceExecutor` and `PortfolioReadExecutor` callbacks
  passed as `executor=` to `asset_reference_details(...)`,
  `asset_reference_details_by_uids(...)`, `latest_portfolio_weights(...)`, and
  `portfolio_values(...)` are called as `executor(statement)` instead of
  `executor(statement, models)`.
- **Breaking:** MetaTable migration admin commands moved from
  `mainsequence migrations ...` to
  `metatables migrations ... --provider migrations:migration`;
  `current --json` is now `metatables --json migrations current`, and
  `revision` autogenerates by default. The provider identity is unchanged
  (package `msm`, namespace `mainsequence.markets`, version table
  `ms_markets__alembic_version`, head `0017`), and no revision was added.
- **Breaking:** Index FastAPI routes resolve the caller from the
  platform-injected `request.state.user` (SDK 9 request identity) instead of
  binding the removed `_CURRENT_AUTH_HEADERS` and `_CURRENT_USER` SDK context
  variables. A request without injected identity is anonymous.

### Removed

- Removed `MetaTableOperationScopeTable` usage and every scope-only helper and
  parameter. No compatibility classes or aliases are provided.
- Removed the dead `metatable_configured_tablename` usage from
  `examples/msm/platform/inspect_markets_metatable_models.py`; the helper has
  no `metatables` equivalent and the example already reports the configured
  physical `table_name`.

### Added

- Added the version-matched MetaTables client skills under
  `.agents/skills/metatables/`, copied with
  `metatables copy-metatables-skills --path .`.

### Documentation

- Updated the README, getting started, concepts, tutorials, knowledge guides,
  FastAPI notes, examples, packaged `ms_markets` agent skills, VS Code tasks and
  launch configurations, and the managed AGENTS.md section to the SDK 9 and
  `metatables` imports and commands. Added ADR 0043 and marked ADR 0022, 0024,
  and 0039 as amended or superseded.
- Refreshed the SDK-owned skills under `.agents/skills/mainsequence/` with the
  offline SDK 9.0.2 `mainsequence code-repository update-agent-skills --path .`.
  The retired SDK MetaTable skills are gone, and platform-owned skills are no
  longer mirrored into that namespace; the authenticated platform update
  installs them under `.agents/skills/mainsequence_platform/`.
- Refreshed the repository lock and exported requirements.

## [1.0.16] - 2026-09-12

### Added

- Added explicit, vectorized `TargetWeightExecutionModel` and
  `InstrumentExecutionSpec` contracts for converting the configured signal and
  rebalance policy into simulated quantities, settlement legs, and restartable
  execution progress.
- Added composable strategy-owned execution cost models and an offline linear
  perpetual fixture proving variation-margin settlement and pre-execution
  funding order.

### Changed

- Routed opt-in position-aware portfolios through one coordinated
  signal-to-`RebalanceStrategy` simulation path while leaving the weight-only
  `PortfolioRebalance` and commission path unchanged.
- Included execution progress in canonical ledger restart state and made exact
  incremental retries publish no duplicate ledger tail.
- Refreshed the repository lock, exported requirements, and managed platform
  skills to Main Sequence SDK 8.1.11.

### Removed

- Removed the external execution-fact source from position-aware Portfolio
  configuration and accounting. Portfolios accept no broker/Account execution
  ingress, compatibility alias, replay lane, or fallback.

### Fixed

- Prevented floating-point noise at exact quantity-step boundaries from rounding
  a mathematically integral target down by one lot.
- Excluded explicitly closed zero-quantity positions from strict mark
  requirements while preserving their ledger and state rows.

### Documentation

- Corrected ADR 0042 and the portfolio accounting guidance to enforce that a
  Portfolio is a backtest model with no Account or broker execution inputs.
  The configured signal and `RebalanceStrategy` are the sole producer of
  internal simulated execution facts; issue #11 removes the external-execution
  ingress from `1.0.15` without a compatibility fallback.

## [1.0.15] - 2026-09-12

### Added

- Added the opt-in `PortfolioEngine` and pure `PortfolioAccounting` reducer,
  public directly injected lifecycle-event contracts, columnar event batches,
  explicit execution-fact conversion, and a built-in dividend entitlement and
  settlement model.
- Added strict multi-currency position, cash, and obligation valuation through
  explicit price and FX observations, plus ledger-derived completed-cash-flow
  state, and normalized portfolio-value projections.
- Added strict reducer restart from a complete active ledger, including event
  digest, record-count, state-chain, and opening-configuration validation.
- Added `PortfolioEventLedgerStorage`, `PortfolioStateStorage`, and
  `PortfolioCashFlowsStorage` with provider migration `0017`.
- Added offline EUR-dividend/USD-NAV and custom vectorized cash-flow examples.

### Changed

- Added optional `PortfolioBuildConfiguration.accounting_configuration` while
  omitting disabled accounting from legacy serialization. The legacy
  `PortfoliosDataNode` rejects enabled accounting instead of mixing histories
  or silently falling back to weight-only valuation.

### Documentation

- Added a dedicated position-aware accounting guide covering engine ownership,
  configuration, execution/dividend/price/FX input grains, ledger records,
  retry and restart behavior, projections, custom lifecycle models, failure
  semantics, examples, and the explicit absence of an SDK blocker. Updated the
  repository portfolio-workflow skill with the same maintenance invariants.

## [1.0.14] - 2026-09-09

### Added

- Added the installable `msm.api.http` provider adapter toolkit with strict
  Command Center collection, discovery, bulk-action preflight, structured
  error, and owner-scoped observable-operation contracts and helpers.
- Added a provider-neutral HTTP contract example covering discovery metadata
  and operation creation.

### Changed

- Moved the reusable `apps/v1` resource and bulk-action implementations behind
  the public `msm.api.http` import boundary while retaining compatibility
  imports for the repository FastAPI app.

### Documentation

- Documented provider adapter reuse, error sanitization, operation ownership,
  and the explicit single-process durability boundary of the bundled in-memory
  operation store.

## [1.0.13] - 2026-09-09

### Fixed

- Unified asset-scope mapping identity on canonical `asset_identifier` and
  removed `unique_identifier` fallback behavior from mapping and object scopes,
  so inherited asset-indexed validation and portfolio calendar resolution
  enforce the same payload. Added regressions for
  [#9](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/9).
- Discarded out-of-range executed-weight seed rows and enforced unique
  `(time_index, asset_identifier)` coordinates before portfolio weight pivots,
  while preserving one set-based seed lookup. Added regressions for
  [#10](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/10).

### Documentation

- Documented canonical mapping scopes and defensive portfolio seed validation
  in the asset guide, portfolio guide, tutorial, and equal-weight example.

## [1.0.12] - 2026-09-08

### Fixed

- Made strict portfolio valuation require fresh values only where the current
  or immediately preceding executed holding is nonzero. Unchanged zero-weight
  assets can remain in complete signal and weight snapshots without blocking
  valuation, while entry and exit observations remain mandatory. Added
  regressions that close
  [#8](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/8).

### Documentation

- Documented exposure-aware strict valuation in the portfolio guide, tutorial,
  and equal-weight example.

## [1.0.11] - 2026-09-08

### Fixed

- Preserved `open_time`, `first_trade_time`, `last_trade_time`, and intraday
  `trade_day` as timezone-aware `datetime64[ns, UTC]` values throughout price
  interpolation instead of round-tripping pandas 3 microsecond timestamps
  through unit-ambiguous integers. Added daily and intraday regressions that
  close [#7](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/7).
- Replaced the deprecated naive `datetime.utcnow()` comparison in intraday
  interpolation with a timezone-aware UTC timestamp.

### Documentation

- Documented the interpolated price timestamp contract and the required
  upgrade-before-scoped-replay order in the portfolio guide, tutorial, and
  equal-weight example.

## [1.0.10] - 2026-09-08

### Changed

- Raised the minimum, locked, and exported Main Sequence SDK dependency plus
  managed repository skill pin from 8.1.7 to 8.1.8.

### Fixed

- Restored the complete SDK dimension-query contract on
  `AssetIndexedDataNode.get_last_observation(...)` while retaining validated
  optional asset scoping.
- Fixed portfolio seed observation reads to include complete multidimensional
  coordinates such as `(signal_uid, asset_identifier)` in one set-based backend
  request. Added concrete AssetIndexedDataNode regressions that close
  [#6](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/6).

### Documentation

- Documented the set-based asset seed-read contract in the asset, portfolio,
  tutorial, and equal-weight example surfaces.

## [1.0.9] - 2026-09-08

### Documentation

- Corrected the live README, getting-started guide, and FastAPI package
  contract documentation to state the required Main Sequence SDK 8.1.7 floor;
  the published dependency metadata already enforced that floor.

## [1.0.8] - 2026-09-08

### Added

- Added a source-backed trailing-average-daily-volume participation preview
  example that performs bounded, asset-filtered reads and reports execution
  quantities, remaining weights, and daily-cap consumption without persisting
  portfolio state.

### Changed

- Raised the minimum, locked, and exported Main Sequence SDK dependency plus
  managed repository skill pin from 8.1.5 to 8.1.7 so portfolio configuration
  durations serialize deterministically during updater hashing.

### Fixed

- Restored deterministic updater hashing and configuration reconstruction for
  `CalendarEventSignal.event_offset` and
  `ValuationAlignmentPolicy.maximum_staleness` by requiring Main Sequence SDK
  8.1.7 or newer.
- Added the repository root to pytest's configured import path so executable
  examples can be imported by example-focused tests without shell-specific
  `PYTHONPATH` setup.

## [1.0.7] - 2026-09-08

### Added

- Added the generic `PortfolioRebalance` updater and
  `PortfolioRebalanceStateStorage` ledger for deterministic active-intent,
  partial-execution, remaining-target, event-provenance, and restart state.
- Added `PortfolioCalendarEvents` and `PortfolioCalendarEventsStorage` so
  calendar-relative strategies consume an explicit published schedule rather
  than reading or generating dates behind the dependency graph.
- Added supported `TimeWeighted`, `VolumeParticipation`, and
  `LiquidityConstrained` strategies driven by observed bars, volume, and
  available liquidity.
- Added `TrailingAverageDailyVolumeParticipation`, which estimates a bounded
  per-asset daily notional cap from completed historical daily VWAP and volume
  while executing only at observable intraday prices and volumes.
- Added static migration `0016` for calendar-event and rebalance-state storage;
  it also provisions the previously declared portfolio-analytics storage.

### Changed

- Replaced the fixed `execution_timestamps(...)` /
  `apply_rebalance_logic(...)` strategy API with declared dependencies,
  required input contracts, strategy-owned event selection, and deterministic
  per-event state transitions. This is a breaking portfolio execution contract
  change.
- Added the optional `prepare_execution_context()` strategy hook and indexed
  signal/event preparation so rolling inputs are computed once rather than
  rescanned for every event.
- Converted `PortfolioWeights` from the strategy executor into a pure
  projection of rebalance-state events that changed executed allocations.
- Updated the SDK lock, exported requirements, and managed repository skills
  to Main Sequence SDK 8.1.5.

### Fixed

- Removed central assumptions that every rebalance strategy uses an immediate
  signal, one execution valuation frame, or an optional column named
  `volume`. New strategy categories can declare arbitrary typed observed
  inputs without changing portfolio valuation code.
- Preserved unfinished volume- and liquidity-constrained work as `pending` or
  `partial`, with explicit supersession when a newer signal arrives.
- Prevented ex-post current-session VWAP from being treated as an execution
  price or eligible trailing-capacity observation. Daily participation usage
  now survives same-session restarts and target supersession.

### Documentation

- Marked ADR 0040 implemented and updated the portfolio knowledge page,
  tutorial, and equal-weight example for the general strategy-driven
  rebalance graph.
- Documented the trailing daily-liquidity strategy and added a focused public
  configuration example.

## [1.0.6] - 2026-09-07

### Added

- Added `CalendarEventSignal` with hash-bearing calendar, session, event,
  offset, cadence, cutoff, and execution-valuation semantics.
- Added `PortfolioAnalytics` and separate `PortfolioAnalyticsStorage` for
  consumer-owned reporting resampling with explicit period boundaries and
  source-observation lineage.
- Added a dry-run-first legacy portfolio timestamp repair that validates
  midnight rows against persisted calendar sessions, applies only a scoped
  inclusive tail rollback, and requires deterministic portfolio replay.

### Changed

- Promoted `PortfolioWeights` to the execution/rebalance updater and made
  `PortfoliosDataNode` a valuation-only consumer of canonical executed weights.
  Canonical execution and valuation timestamps now originate only from signal,
  persisted calendar, execution-data, or valuation-source observations.
- Made `CalendarEventSignal.calendar_identifier` required and removed silent
  fallback from persisted calendar lookup to local pandas or synthetic
  calendars. Missing, ambiguous, and failed governed lookups now fail visibly.
- Replaced portfolio-local price-grid controls with strict, bounded per-asset
  `ValuationAlignmentPolicy` as-of selection. Portfolio configuration no longer
  accepts `portfolio_prices_frequency` or `price_alignment_policy`.
- Updated the Main Sequence SDK lock and managed repository skills to 8.1.4.

### Fixed

- Chunked long-horizon persisted-calendar reads so daily price interpolation
  remains within governed operation limits.
- Resolved sparse per-asset valuation seeding, midnight relabeling and rerun
  duplication, and implicit calendar-event timing semantics tracked in issues
  #2, #3, and #4.

### Removed

- Removed unfinished `TimeWeighted` and `VolumeParticipation` strategies from
  the supported public strategy surface until their bar-driven execution
  contracts are implemented.

### Documentation

- Added and implemented ADR 0040, establishing separate temporal ownership for
  portfolio execution, valuation, and analytics.

## [1.0.4] - 2026-09-05

### Fixed

- Updated portfolio, asset-snapshot, holdings, virtual-fund, and pricing updater calls for the
  Main Sequence SDK 8.1 execution contract. `PortfoliosDataNode.run()` now forwards only
  `update_tree`, `update_only_tree`, and `override_update_stats`; the removed scheduler,
  debug, and force-update controls are no longer exposed or passed to the SDK runner.

## [1.0.3] - 2026-09-04

### Fixed

- Replaced the per-asset `AssetCategory.replace_memberships()` write loop with
  one governed multi-row upsert followed by one scoped stale-membership delete.
  Duplicate asset UIDs are normalized before compilation, empty replacements
  execute one delete, and the public API returns every row from the bulk upsert.
  This closes [#1](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/1).

### Changed

- Raised the SDK 8 package floor and validated project lock to
  `mainsequence>=8.0.7`, and refreshed the managed Main Sequence repository
  scaffold from SDK 8.0.7.

## [1.0.2] - 2026-08-30

### Fixed

- Aligned the FastAPI deployment-contract test with the backend-validated
  workflow API `2.1.0` declaration and its explicit three-revision retention
  policy.

## [1.0.1] - 2026-08-30

### Changed

- Released the first SDK-8-only `ms-markets` major version. Package metadata
  requires `mainsequence>=8.0.4` without an exact SDK patch pin; SDK 6 and SDK 7
  are unsupported and no compatibility aliases or mixed-version mode are
  provided.
- Completed the SDK 8 hard cut: repository operations use the canonical
  CodeRepository and CodeRepositoryBranch ontology, while updater,
  configuration, and reference imports use the `mainsequence.meta_tables`
  time-index-table API, configuration schema version 2, canonical dependency
  actions, and read-only table references.
- Updated `msm copy-msm-skills` for the SDK 8 scaffold-copy contract and renamed
  its JSON target field from `project` to `code_repository`.
- Completed OpenAPI documentation metadata for every FastAPI v1 operation and tag, added stable
  tag groups and the canonical source-repository link, documented the composed Asset schemas, and
  derived canonical row and field descriptions from existing MetaTable metadata so downstream API
  references do not maintain a duplicate schema-description inventory.
- Replaced every FastAPI v1 list response with the strict Command Center SDK
  `command-center.resource_collection@v1` contract and added authoritative
  `command-center.resource_discovery@v1` siblings for all 25 collections.
  Removed `response_format`, DRF-style pagination, and standalone
  `/bulk-actions/` discovery paths; embedded authorized bulk actions in resource
  discovery; added canonical account and pricing-curve detail operations; and
  pinned conformance tests to the complete Command Center SDK `0.1.13` schema
  and fixture bundle.
- Added port 3010 to the development-only FastAPI CORS wrapper so the static-site repository's VS
  Code full-stack debugger can run the local API on port 8001 and frontend on port 3010 together
  without changing production application middleware.
- Linked the automatically deployed Markets static site to the stable `main`
  FastAPI ResourceRelease identity and admitted the supported
  `https://*.site-dev.main-sequence.app` browser origin. API redeployments now
  rotate behind the same release UID while the Command Center SDK resolves the
  current opaque RPC endpoint at request time.
- Migrated the automatic `main` FastAPI deployment declaration to the current
  workflow API `2.0.0` contract and added regression coverage for every-commit
  redeployment without a caller-selected project image.
- Added the canonical `api/main.py` deployment entrypoint for the existing
  `apps/v1` application so the platform can discover and automatically deploy
  the FastAPI resource without moving application logic out of `apps/v1`.
  Added `.mainsequence/workflows/fastapi.yaml` to redeploy that release on
  every synchronized commit, and replaced the machine-local Main Sequence SDK
  source override with the published `mainsequence==6.0.35` package so remote
  image builds can resolve the dependency.
- Added Command Center SDK bulk-action discovery, preflight, and canonical
  execution contracts for asset categories, portfolios, and portfolio groups.
  Execution now accepts `{selection, options}`, rejects the retired FastAPI
  bulk payloads, and rechecks missing rows and protected portfolio references
  immediately before deletion.
- Restricted the project runtime to Python 3.13, upgraded the Main Sequence SDK,
  removed the obsolete SDK upper-version cap, rebuilt the uv lock and local
  environment on Python 3.13, and moved documentation and package-publish
  workflows to Python 3.13. Refreshed the installed SDK, dependency lock, and
  managed Main Sequence skills to `6.0.36`.
- Replaced the Index calculation architecture with strict `formula` and
  `custom` methods. Formula expressions use typed Asset/Index identifiers,
  exact source MetaTable UIDs and observables, an allow-listed arithmetic
  parser, immutable validity versions, exact or bounded backward as-of
  alignment, and deterministic DataNode dependencies. Added `FormulaIndex`,
  formula catalog routes, mixed-source and Portfolio-to-custom examples, and
  revision `0015`; removed operator/leg/resolved-leg registries, observation
  units, stateful Index performance operators, and all compatibility aliases.
  Asset and Index now share `list_related_meta_tables(uid, numeric=True,
  timestamped=True)` and equivalent FastAPI routes backed by paginated,
  authoritative-FK catalog discovery. Added the immutable Pydantic
  `IndexFormula` contract for historical evaluation of caller-supplied Series
  or DataFrames without a persisted Index or formula-definition UID.
- Removed the untyped `Index.provider` attribute and its database index through
  revision `0014`. Index create/update payloads, catalog search,
  ordering, FastAPI filtering, detail badges, examples, and OpenAPI no longer
  expose it, and legacy payloads containing `provider` are rejected rather
  than accepted through a compatibility shim. Source-native facts such as
  OpenFIGI details remain in their structured metadata payloads.
- Hardened the Index catalog and publication path.
  Revision `0013` adds rebuildable per-Index dataset availability metadata, a
  historical one-active-definition invariant, and identifier-first canonical
  lookup indexes. List filters use indexed availability predicates; dataset
  lists expose populated, compatible-empty, and unavailable states; direct
  delete impact is typed without a custom deletion workflow; and producers use
  post-persistence reconciliation.
- Replaced asset-biased curve key-node identity with typed
  `source_reference={"type": "asset" | "index", "identifier": "..."}`
  provenance. Added the shared `FixedIncomeCurveKeyNode` base across deposit,
  OIS, futures, bond, FX, and cross-currency basis helper models, updated the
  reconstruction example to demonstrate asset- and index-sourced inputs, and
  rejected top-level `asset_identifier`/`index_identifier` key-node fields.
- Changed floating-rate bond and swap pricing to resolve projection and
  discount curves independently through market-data-set curve bindings.
  Projection curves build floating indexes and forecast coupons; discount
  curves feed QuantLib discounting engines. The floating bond example, tutorial,
  and pricing docs now demonstrate separate projection and discount curves.
  Both role bindings must exist even when they point to the same physical
  `curve_uid`.
- Changed `MSDataInterface.get_historical_discount_curve_observations(...)` to
  read multi-curve latest-as-of observations through a backend window query
  instead of scanning full curve history into pandas.
- Changed asset snapshot enrichment services to resolve latest rows through
  backend queries instead of scanning history and choosing the latest row in
  Python.
- Removed the legacy `MSDataInterface` process-wide latest-observation
  environment flag; callers must use explicit latest-curve APIs or bounded
  historical reads.
- Added `msm_pricing.pricing_engine.apply_z_spread_to_curve(...)` for strict
  runtime z-spread overlays that match `Bond.z_spread(...)`'s continuous
  decimal spread convention without mutating persisted curve observations.
- Added `PreparedInstrument.z_spread(...)` so valuation-context prepared
  instruments propagate the selected market-data set and curve quote side when
  solving z-spreads.
- Added `msm_pricing.valuation.build_valuation_position(...)` for strict
  construction of transient valuation baskets from normalized instrument/unit
  rows.
- Added reusable `latest_portfolio_weights(...)`, `portfolio_values(...)`, and
  `asset_reference_details(...)` services for package-owned portfolio output
  and asset reference reads.
- Added `msm_pricing.scenarios.curves` with typed curve scenario models,
  key-node basis-point bump helpers, runtime scenario curve-handle construction,
  and `price_curve_scenario(...)` delegation to the prepared
  `price_scenario(...)` path.
- Added `price_resolved_curve_scenario(...)`,
  `prepare_resolved_curve_scenario_runtime_overrides(...)`, and
  `LineCurveResolutionInput` for caller-resolved curve scenarios that already
  have explicit base/scenario handles per valuation line, with selected
  base/scenario handle maps exposed for downstream analytics/reporting reuse.
- Added `msm_pricing.scenarios.valuation` with typed valuation scenario
  workflow orchestration, partial-success line pricing, line/carry impacts,
  optional analytics and cashflows, observed dirty-price z-spread overlays, and
  an offline workflow example.
- Added `msm_pricing.analytics.spreads` with cross-asset spread primitives,
  fixed-income DV01 spread metrics, optional dependency diagnostics, and an
  offline fixed-income spread analytics example.
- Added `msm_pricing.pricing_engine.curves` with generic QuantLib rate-helper
  specs/builders, helper-key-node adapters, helper-based curve reconstruction,
  and curve observation export, plus resolver/scenario support for
  `builder_type="rate_helper_curve"` without importing connector-specific code.
- Extended generic OIS helper reconstruction to expose QuantLib OIS
  schedule/convention fields and to require persisted
  `builder_payload.helper_schema="rate_helpers@v1"` for helper-based curve
  adapters.
- Added generic interest-rate futures helper reconstruction with
  `sofr_future_rate_helper` key-node support and explicit futures price-unit
  validation.
- Added generic zero-coupon and fixed-rate bond helper reconstruction under
  `msm_pricing.pricing_engine.curves`, including bond-helper key-node parsing,
  `rate_helpers@v1` reconstruction support, observation export tests, and
  strict diagnostics for unsupported yield shocks on price-quoted bond helpers.
- Added generic cross-currency helper reconstruction under
  `msm_pricing.pricing_engine.curves`, including FX swap helpers,
  constant-notional cross-currency basis helpers, context/provenance nodes
  under the existing `rate_helpers@v1` schema, explicit FX forward-points and
  basis-spread normalization, `JointCalendar` decoding, runtime dependency
  resolvers, and stable helper quote-error diagnostics.
- Added `BondInstrumentTerms` and
  `build_bond_instrument_from_terms(...)` for provider-neutral construction of
  existing zero-coupon, fixed-rate, and floating-rate bond instrument models
  without source-row parsing or connector dependencies.
- Added `CurveObservationExportConfig.from_curve_building_details(...)` so
  helper-reconstructed curves can export compounded annual zero-rate nodes with
  explicit front-node days and pillar-date inclusion, using term-structure
  reconstruction functions when QuantLib pillar dates are required.
- Extended `price_curve_scenario(...)` to forward `overnight_index` and
  `overnight_index_resolver` into helper-reconstructed scenario curve builds.
- Updated swap and floating-bond scenario repricing to use explicit
  `reset_curves(projection_curve=..., discount_curve=...)` role handles.
- Added `get_many_by_unique_identifier(...)` on typed row APIs such as
  `Asset` for batch canonical-identifier resolution.
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
- Added an implementation task plan for reusable valuation input construction,
  portfolio and asset read services, curve-keyed scenario pricing, and optional
  fixed-income spread analytics without copying project-local adapter code into
  the library.
- Added an implementation task plan for upstreaming generic curve
  reconstruction and observation export machinery from provider connector code
  into `msm_pricing.pricing_engine.curves`.
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
  discount-curve lookup by curve identity.
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
