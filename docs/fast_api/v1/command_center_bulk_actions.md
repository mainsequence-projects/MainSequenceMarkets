# Command Center Bulk Actions

The `apps/v1` API exposes backend-authoritative bulk deletion for asset
categories, portfolios, and portfolio groups. These routes implement the
Command Center SDK v1 resource discovery, execution, and preflight contracts
pinned to command-center-sdk `0.1.13`, commit
`f11c0ea8c5d3fc267997e476aa1522c798fdaced`.

## Resource boundaries

| Resource | Discovery | Preflight | Execution |
| --- | --- | --- | --- |
| Accounts | `GET /api/v1/account/discovery/` | `POST /api/v1/account/bulk-delete/preflight/` | `POST /api/v1/account/bulk-delete/` |
| Asset categories | `GET /api/v1/asset-category/discovery/` | `POST /api/v1/asset-category/bulk-delete/preflight/` | `POST /api/v1/asset-category/bulk-delete/` |
| Portfolios | `GET /api/v1/portfolio/discovery/` | `POST /api/v1/portfolio/bulk-delete/preflight/` | `POST /api/v1/portfolio/bulk-delete/` |
| Portfolio groups | `GET /api/v1/portfolio-group/discovery/` | `POST /api/v1/portfolio-group/bulk-delete/preflight/` | `POST /api/v1/portfolio-group/bulk-delete/` |

Each `command-center.resource_discovery@v1` response advertises one destructive action with `explicit`
selection. `all_matching` is deliberately not advertised. Discovery supplies
the execution endpoint, preflight endpoint, confirmation copy, tone, supported
selection modes, and options.

## Canonical request

Preflight and execution receive the same
`command-center.bulk_action_execution@v1` body:

```json
{
  "selection": {
    "mode": "explicit",
    "uids": ["7dc962fe-58e6-4a04-9cc6-20b44d678d42"]
  },
  "options": {}
}
```

The selected resources use UUID identities. Only the account delete advertises
an option, `delete_portfolios` (boolean, `false` by default): it also deletes
the portfolios only those accounts used
([ADR 0050](../../ADR/0050-account-deletion.md) decision 9). Options an action
does not advertise, values of the wrong type, numeric identifiers, and
unadvertised selection modes are rejected. The former `{ "uids": [...], "select_all": false }` HTTP payload is
not part of this contract.

## Preflight and execution

Preflight returns `command-center.bulk_action_preflight@v1`. It resolves every
selected UID and reports `allowed`, `matched_count`, `blockers`, and `warnings`
without mutating data. Portfolio preflight also lists, per portfolio, the rows
its delete removes from each of its datasets (`portfolios[].row_counts`) and what
refuses it: account history that references it, and tables of other applications
that hold its rows or cannot be checked.

Each bulk-delete preflight also reports what deleting rows from the resource's
table reaches through foreign keys. It asks MetaTables
(`MetaTable.get_impact(action="delete_rows")`), reuses the answer for that
table for five minutes, and adds:

- `impact`: the MetaTables impact graph. Nodes are the tables the delete
  reaches, with their effects and whether the caller may write each one. Edges
  are classified as `cascade_delete`, `cascade_update`, `set_null`,
  `set_default`, `restrict` or `reads`. MetaTables' blockers are included.
- `warnings`: one sentence for each foreign-key action the delete triggers, for
  example "PortfolioGroupMembership rows that reference deleted PortfolioGroup
  rows are deleted too (ON DELETE CASCADE)." Command Center shows warnings
  without custom rendering.
- `blockers`: MetaTables' reasons the caller may not run the delete, prefixed
  with the table: the caller cannot write the table, the table does not accept
  writes, or its DataSource is read-only. The preflight then answers
  `allowed: false`, and execution reports every selected row in `failed` with
  them, before the database refuses the delete. Cascades never block: write on a
  table depends only on its own grants, because a foreign key's action belongs to
  the referencing table.

Deleting portfolios or portfolio groups cascades to their
`PortfolioGroupMembership` rows; deleting asset categories cascades to their
`AssetCategoryMembership` rows. Deleting accounts removes their whole history
([ADR 0050](../../ADR/0050-account-deletion.md)); its preflight also lists, per
account, the Markets rows it removes (`accounts[].row_counts`), the rows of other
accounts that block it, the portfolios it would delete and keep with
`delete_portfolios`, and the tables in other namespaces that its foreign keys
reach (`other_namespace_cascades`, `other_namespace_restricts`). If MetaTables cannot compute the impact,
`impact` is `null` and a warning says so. The preflight is not blocked, because
the database still applies and enforces every foreign-key action.

On the local SQLite runtime, MetaTables documents one limitation: its authorizer
also checks the reads and writes of foreign-key actions, so a delete that
cascades fails unless the caller can access every referencing table. The
preflight cannot detect this. PostgreSQL runs these actions as the referencing
table's owner.

Execution never refuses the selection because one row cannot be deleted
([issue 128](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/128)).
It deletes every selected row that may go, together in one transaction, and
answers `200` with one envelope on every bulk delete:

- `detail` and `deleted_count`;
- `deleted`: each deleted row, as the resource's delete reports it;
- `failed`: each selected row that was not deleted, with its `uid` and the reason:
  it was not found, a check refused it, or the database refused it.

The delete runs its own checks: a reference written after the preflight, or a
`RESTRICT` key of an application's own table, refuses the selection's transaction,
which then deletes nothing, and each row is then deleted on its own, so only the
refused ones are reported. The portfolio bulk delete deletes by its preflight's
counts instead of reading them again.

When MetaTables does not answer the delete (a 5xx or a lost connection), it may have
committed or not. Every bulk delete then reads the selected rows once and still
answers `200` with the envelope
([issue 151](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/151)).
The delete is all or nothing, so while a selected row is still there it did not
commit, or not yet: each row still there is in `failed` with a reason that says its
outcome is unknown and the call may be retried, and each row gone is not found. When
the read fails too, every row is in `failed` the same way. When no row is left, the
delete committed. The portfolio and account deletes read their rows before deleting,
so they list each one in `deleted`. The asset-category and portfolio-group deletes do
not, so a row that is gone may never have existed. Each is listed in `failed`, never in
`deleted`, with a reason that says it no longer exists and that the call cannot tell
whether it deleted it.

Request validation errors return `422`. Unsupported modes or options return
`400`. A preflight that discovers missing or protected rows reports them in
`blockers` and answers `allowed: true` when at least one selected row can still be
deleted; execution of that selection deletes those rows and reports the others.

## Provider discovery

The discovery and preflight operation IDs are also exposed through
`/.well-known/command-center/connection-contract` as resource operations. The
three execution operation IDs remain mutation operations:

- `discoverAccounts` / `preflightBulkDeleteAccounts` / `bulkDeleteAccounts`
- `discoverAssetCategories` / `preflightBulkDeleteAssetCategories` /
  `bulkDeleteAssetCategories`
- `discoverPortfolios` / `preflightBulkDeletePortfolios` /
  `bulkDeletePortfolios`
- `discoverPortfolioGroups` / `preflightBulkDeletePortfolioGroups` /
  `bulkDeletePortfolioGroups`

The language-neutral manifest, schemas, and fixtures in command-center-sdk are
the contract authority. Provider projects, including this repository's FastAPI
app, import the implementing Python models and helpers from `msm.api.http`.
