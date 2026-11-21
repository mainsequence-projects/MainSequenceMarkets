# Upgrading To 3.0

ms-markets 3.0 renames the DataNode vocabulary to the MetaTables time-index
terms ([ADR 0048](ADR/0048-time-index-vocabulary-rename.md)). This page lists
what changes for a project that depends on ms-markets and the order to change it.

## What Changes

| Before 3.0 | From 3.0 |
|---|---|
| `msm.data_nodes`, `msm_portfolios.data_nodes`, `msm_pricing.data_nodes` | `msm.time_index`, `msm_portfolios.time_index`, `msm_pricing.time_index` |
| `msm_portfolios.contrib.prices.data_nodes` | `msm_portfolios.contrib.prices.updaters` |
| `*DataNode`, `*DataNodeConfiguration` | `*Updater`, `*UpdaterConfiguration` |
| `TargetPositionsDataNodeConfiguration` | `TargetPositionsConfiguration` |
| `DiscountCurvesNode`, `FixingRatesNode` | `DiscountCurvesUpdater`, `FixingRatesUpdater` |
| `holdings_data_node_uid`, `source_data_node_uid` | `holdings_storage_table_uid`, `source_storage_table_uid` |
| `portfolio_weights_data_node_uid`, `signal_weights_data_node_uid`, `portfolio_data_node_uid` | `portfolio_weights_table_update_uid`, `signal_weights_table_update_uid`, `portfolio_table_update_uid` |
| `data_node_uid` on pricing bindings | `storage_table_uid` |
| `data_node_uids`, `resolve_data_node_uid`, `direct_data_node_uid_for` | `storage_table_uids`, `resolve_storage_table_uid`, `direct_storage_table_uid_for` |
| `data_node=` on virtual-fund allocation | `updater=` |

Storage classes, physical table names and MetaTable identifiers do not change.
From 3.0.0 until 5.0.0 every pre-3.0 name still worked with a `DeprecationWarning`:
old import paths re-exported the same objects, old class and field names
resolved, and HTTP responses repeated each field under its old name. ms-markets
5.0.0 removes them ([#107](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/107)),
so an old name now fails like any unknown name: an old import raises
`ModuleNotFoundError` or `ImportError`, a payload or request with an old field
is rejected, and a response no longer carries it.

## Find What To Change

Search the project, its tests and its documentation for every name in the left
column before moving to 5.0. Look closely at `getattr(obj, "<old name>", default)`:
it raises nothing, it returns the default.

## Identities

Every producer whose class or configuration class moved gets a new MetaTables
`update_hash`, so its first run under 3.0 creates a new `TimeIndexTableUpdate`.
It continues from its output table's last observation; the old record keeps its
run history. Projects that subclass an ms-markets updater with their own
configuration class keep their hash, unless that configuration nests an
ms-markets updater or uses an ms-markets configuration class directly.

`signal_uid`, portfolio configuration hashes and rebalance strategy revisions do
not change: `msm.identity` maps the moved class paths back to their pre-3.0
paths before ms-markets hashes, and that mapping stays after 5.0.

## UID Columns

3.0.0 added a column named after the identity it holds next to each pre-3.0
`*_data_node_uid` column (revision `0022`). Every release from 3.0.0 until 5.0.0
wrote both columns and read the pre-3.0 one. The steps that were planned for
3.x, 4.0.0 and 4.1.0 never shipped.

5.0.0's revision `0035` copies each pre-3.0 column into its successor, makes
`storage_table_uid` NOT NULL on pricing market-data bindings and drops the
pre-3.0 columns. Once the ms-markets deployment's `migrate-markets` Job has
applied it in an Environment, a project on a release before 5.0.0 fails there
on the account, account holdings set, portfolio and pricing market-data binding
tables, and a project on 5.0 works. Upgrade every project that uses these
tables to 5.0 at the same time.
