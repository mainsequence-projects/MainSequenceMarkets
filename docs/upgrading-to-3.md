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
Through 3.x every pre-3.0 name still works: old import paths re-export the same
objects, old class and field names resolve, and HTTP responses repeat each field
under its old name. Each use raises a `DeprecationWarning`. ms-markets 4.0
removes the old names.

## Find What To Change

Run the scan from the project root. It exits 1 while pre-3.0 names remain, so it
can gate a CI job:

```bash
msm rename-preflight scan src tests
```

Fix every `silent default` finding first. Code such as
`getattr(binding, "data_node_uid", "")` keeps working through 3.x, but under
4.0 it returns the default without an error.

## Upgrading To 4.0

ms-markets 4.0 removes every pre-3.0 name. An import from a pre-3.0 path raises
`ModuleNotFoundError`, a pre-3.0 class name raises `AttributeError`, and a
pre-3.0 field name fails validation in payloads and HTTP requests. The exception
is `getattr(obj, "<pre-3.0 field>", default)`, which returns the default without
an error, so `msm rename-preflight scan` must report nothing before a project
moves to 4.0.

## Identities

Every producer whose class or configuration class moved gets a new MetaTables
`update_hash`, so its first run under 3.0 creates a new `TimeIndexTableUpdate`.
It continues from its output table's last observation; the old record keeps its
run history. Projects that subclass an ms-markets updater with their own
configuration class keep their hash, unless that configuration nests an
ms-markets updater or uses an ms-markets configuration class directly.

`signal_uid`, portfolio configuration hashes and rebalance strategy revisions do
not change. To see which of your producers rotate, and the pre-3.0 hash that
names each old record, pass a callable that builds them:

```bash
msm rename-preflight rotation my_project.pipelines:updaters
```

## Release Order

The UID columns move in four steps, because each needs every Environment to
have upgraded first:

1. **3.0.0** adds the new columns (revision `0022`), writes both names and reads
   the pre-3.0 columns. Upgrade every project that writes accounts, portfolios
   or pricing bindings.
2. **3.1.0** copies late 2.x writes and reads the new columns (revision
   `0023`). Release it only when no 2.x writer remains in any Environment;
   after it, a 2.x writer can no longer create pricing bindings.
3. **4.0.0** removes the pre-3.0 names and stops writing the pre-3.0 columns
   (revision `0024`). Release it only when no project older than 3.1 reads
   these tables, and after the scan is clean everywhere.
4. **4.1.0** drops the pre-3.0 columns (revision `0025`). Release it only when
   no project older than 4.0 uses these tables, because every 3.x release
   still selects and writes them.

In each Environment, a project can run a release only after the ms-markets
deployment's `migrate-markets` Job has applied that release's revision there:
3.0 selects the columns that `0022` adds, and 4.0 inserts pricing bindings
without the `data_node_uid` value that `0024` makes optional.

To check what the stored account UIDs hold, run
`msm rename-preflight account-uids` with the Markets runtime attached.
