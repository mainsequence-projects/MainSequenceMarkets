# 0048. Rename DataNode To The MetaTables Time-Index Vocabulary

## Status

Accepted. Ships in four releases: 3.0.0 renames the code and adds the new UID
columns, 3.1.0 reads the new columns, 4.0.0 removes the old names and stops
writing the old columns, and 4.1.0 drops them. Amends
[ADR 0043](0043-sdk-9-metatables-client-hard-cut.md) with one exception: a
deprecation window for the renamed import paths and fields.

## Context

DataNode is the retired SDK's term for a dataset that bundled its producer and
its storage. MetaTables separates the two: a storage class is a
`PlatformTimeIndexMetaTable` whose backend record is a `TimeIndexMetaTable`, and
a producer is a `TimeIndexTableUpdater` whose backend record is a
`TimeIndexTableUpdate`. MetaTables rejects the legacy `data_node_*`
configuration keys and the `data_node` dependency kind.

ms-markets already runs on `TimeIndexTableUpdater`, but it still names its
producers `*DataNode` and keeps them in `msm.data_nodes`,
`msm_portfolios.data_nodes` and `msm_pricing.data_nodes`. Its `*_data_node_uid`
columns hold two different identities. The three portfolio pointer columns
store the `TimeIndexTableUpdate` uid of a producer. The pricing market-data
binding column is resolved as a `TimeIndexMetaTable` uid, and the two account
columns were described as `DataNodeStorage` uids, the retired storage-table
object.

Names and module paths are part of persisted identities:

- MetaTables hashes each updater's and each configuration class's
  `{module, qualname}` into the producer's `update_hash`, prefixes the hash
  with the class name, and refers to a nested updater by its `update_hash`.
- ms-markets hashes class paths into `signal_uid`, the portfolio configuration
  hash and the rebalance strategy revision. The strategy revision also hashes
  the `update_hash` of each declared dependency. `signal_uid` partitions
  signal-weight rows, and the strategy revision is part of every ledger event
  revision that replay validation compares.
- Physical table names and MetaTable identifiers come from each model's
  authored identifier, not from its module or class name. Incremental update
  statistics come from the output table, not from the update record.

## Decision

1. **Names.** `msm.data_nodes`, `msm_portfolios.data_nodes` and
   `msm_pricing.data_nodes` become `msm.time_index`,
   `msm_portfolios.time_index` and `msm_pricing.time_index`, and
   `msm_portfolios.contrib.prices.data_nodes` becomes
   `msm_portfolios.contrib.prices.updaters`. `*DataNode` classes become
   `*Updater`, `*DataNodeConfiguration` becomes `*UpdaterConfiguration`,
   `TargetPositionsDataNodeConfiguration` becomes `TargetPositionsConfiguration`,
   and `DiscountCurvesNode` and `FixingRatesNode` become `DiscountCurvesUpdater`
   and `FixingRatesUpdater`. Storage classes, physical tables, curve key nodes
   and MetaTables' own names keep their names.
2. **UID columns name the identity they hold.** Producer uids use
   `*_table_update_uid`: `portfolio_weights_table_update_uid`,
   `signal_weights_table_update_uid` and `portfolio_table_update_uid`. Table
   uids use `*storage_table_uid`: `storage_table_uid` on pricing market-data
   bindings, `holdings_storage_table_uid` on accounts and
   `source_storage_table_uid` on account holdings sets. API fields use the same
   names. When this was decided, no production account or account holdings set
   stored a value in either account column, so naming them as table uids
   changes no data; `msm rename-preflight account-uids` checks other
   Environments.
3. **Identities.** MetaTables' `update_hash` rotates once, in 3.0.0. Identities
   that ms-markets derives do not: `msm.identity` maps every moved class path
   back to its pre-rename path, and every nested updater's hash to the hash it
   had under those paths, before ms-markets hashes. The mapping is permanent;
   removing an entry rotates the identities that depend on it.
4. **Deprecation window.** Through 3.x the old import paths are alias packages
   that re-export the same objects and warn on import. Old class names resolve
   with a warning, row APIs accept the old field names and expose them as
   deprecated properties, and HTTP responses carry each new field next to its
   old name, which OpenAPI marks deprecated. Requests accept both names. 4.0.0
   removes all of them. ADR 0043 forbade aliases because they would hide a mix
   of incompatible SDK runtimes. These aliases cover the rename of one contract
   during a staged rollout, so the exception does not reopen that risk.
5. **Columns expand, then contract.** MetaTables requires each revision to keep
   the deployed release working during a rollout: add first, drop or rename in
   a later release.
   - 3.0.0, revision `0022`: add the new columns and the `storage_table_uid`
     index and copy the old values. Write both columns and read the old one,
     because 2.x writers update only the old columns.
   - 3.1.0, revision `0023`: once no writer older than 3.0 remains, copy old
     values into new columns where they differ, make `storage_table_uid` NOT
     NULL, and read the new columns while still writing both.
   - 4.0.0, revision `0024`: once no reader older than 3.1 remains, stop mapping
     and writing the old columns, and make `data_node_uid` nullable so inserts
     without it succeed. The downgrade copies the new values back and restores
     NOT NULL.
   - 4.1.0, revision `0025`: once no process older than 4.0 remains, drop the
     old columns and their index. Every 3.x model maps the old columns, so its
     reads and writes fail once they are gone. Dropping them in 4.0.0, whose
     migration runs as soon as it deploys, would break every 3.x process still
     running. The downgrade re-adds them from the new columns.
6. **Guards.** `tests/identity/test_pinned_identities.py` pins table names and
   identifiers, updater and configuration class paths, MetaTables and
   pre-rename update hashes, `signal_uid`, portfolio configuration hashes,
   strategy revisions and factory-built storage names, and simulates a class
   move. `msm rename-preflight` reports the code a consumer has to change and
   each producer whose `update_hash` rotates.

## Consequences

- After 3.0.0 deploys, every producer built from an ms-markets class gets a new
  `TimeIndexTableUpdate` on its first run. The old records keep their history,
  so run history splits at the upgrade. Producers continue from the output
  table's last observation, and portfolios rewrite their pointer columns on the
  next run.
- Signals, portfolios and strategy revisions keep their identities, so signal
  history stays readable and ledger replay keeps matching.
- Consumer code keeps working through 3.x with deprecation warnings. Imports
  and field names must move before 4.0.0.
- 3.1.0, 4.0.0 and 4.1.0 depend on the versions running in every Environment,
  not on the code alone.
- `msm.identity` stays after 4.0.0.
