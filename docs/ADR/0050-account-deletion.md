# 0050. Account Deletion

## Status

Accepted (2026-11-11), implemented in 3.3.0 through
[issue #58](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/58).
Builds on [ADR 0049](0049-portfolio-lifecycle-and-account-history.md) decision 1
(account history is kept for as long as the account exists) and amends
[ADR 0047](0047-markets-api-application-boundary.md): the account gets delete
routes, and the row router runs `Account`'s own `delete`.

Amended 2026-11-19 by
[issue 91](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/91):
a delete sends one read and one transaction and asks MetaTables for no impact
(decisions 3 and 5), and it can delete the account's portfolios too (decision 9).
See the implementation notes.

## Context

An `Account` is the root of its history. These keys reference it, directly or
through its sets:

| Referencing rows | Column | References | On delete |
|---|---|---|---|
| `AccountHoldingsSet`, `AccountTargetAllocation`, `VirtualFund` | `account_uid` | `Account.uid` | `CASCADE` |
| `OrderManager` | `target_account_uid` | `Account.uid` | `CASCADE` |
| account holdings rows (`AccountHoldingsStorage`) | `account_uid` | `Account.uid` | `RESTRICT` |
| account holdings rows | `holdings_set_uid` | `AccountHoldingsSet.uid` | `CASCADE` |
| orders rows (`OrdersStorage`), trades rows (`TradesStorage`) | `account_identifier` | `Account.unique_identifier` | `RESTRICT` |
| orders rows | `order_manager_identifier` | `OrderManager.unique_identifier` | `RESTRICT` |
| `PositionSet` | `account_target_allocation_uid` | `AccountTargetAllocation.uid` | `CASCADE` |
| target-position rows (`TargetPositionsStorage`) | `position_set_uid` | `PositionSet.uid` | `CASCADE` |
| `VirtualFundHoldingsSet`, virtual-fund holdings rows | `virtual_fund_uid` | `VirtualFund.uid` | `CASCADE` |
| `VirtualFundHoldingsSet`, virtual-fund holdings rows | `source_account_holdings_set_uid` | `AccountHoldingsSet.uid` | `RESTRICT` |

`OrderEventsStorage` has no foreign key. It names an order only by
`order_identifier`.

Other applications reference the same tables in two ways (ADR 0047):

- **Sidecars.** A table keyed one-to-one by a core uid "declares its delete
  action". ADR 0047's worked example is an account sidecar on
  `ms_markets__account.uid` with cascade delete.
- **Storage instances.** `msm.storage_instances` builds a provider's copy of a
  Markets storage in the provider's namespace, migrated by the provider. It copies
  the core storage's foreign keys with the same delete actions. A provider's
  instance of the holdings, target-position, virtual-fund holdings, orders or
  trades storage therefore carries the keys in the table above.

No account can be deleted today:

- `apps/v1/routers/accounts.py` has no delete route.
- `POST /api/v1/rows/account/delete/` answers `501`, and through `msm.client`,
  `Account.delete` raises `MarketsOperationUnsupported`. The row router runs
  `delete` only for resources with an `apps/v1` service delete and for
  composites that define their own `delete`; `_owns_checked_delete` ignores a
  `delete` defined on a `MarketsMetaTableRow` subclass.
- Under the runtime backend, `Account.delete` is the generic
  `MarketsMetaTableRow.delete`, which deletes one row. Orders, trades or holdings
  rows that name the account refuse it through their `RESTRICT` keys.
- `msm.services.delete_account` is the same one-row delete. It and the
  helpers that delete one target allocation, position set or virtual fund
  (`delete_account_target_allocation`, `delete_position_set`,
  `delete_virtual_fund`) have no route and no caller.

Some accounts should not exist at all, for example one registered by mistake or
by an integration that has since been removed. ADR 0049 decision 1 forbids
removing parts of a kept account's history, and
[issue #50](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/50)
was declined for that reason. Deleting the whole account is the only way to
remove that history, and it does not exist.

## Decision

1. **An account is deleted with its whole history.** A service in
   `msm.services` deletes an account and every row in the Markets tables that
   references it, in one transaction, in the order the keys require:
   1. the account's orders and trades rows, and the order-event rows of those
      orders, which must be deleted explicitly because they have no key; then
      its order managers;
   2. its virtual funds, with their holdings sets and holdings rows;
   3. its target allocations, with their position sets and target-position rows;
   4. its holdings sets and holdings rows;
   5. the `Account`.

   It runs on PostgreSQL and on SQLite. On SQLite it is an ordered statement
   list that MetaTables runs in one transaction (MetaTables ADR 0026), as the
   account snapshot writes do. If any statement fails, nothing is deleted.

2. **Markets deletes only its own rows.** Every statement the service sends
   targets a table in the Markets namespace. It never sends a delete to a table
   in another namespace, a provider's storage instance included. A row in such a
   table is removed only by a foreign key that the table carries:
   - a sidecar's key and delete action are declared by the application that
     owns the sidecar;
   - a storage instance's keys are created by the provider's own migration, with
     the delete actions of the Markets contract. A provider that declares an
     instance accepts them.

   Rows with no key stay in place, for example order events in a provider's
   instance of `OrderEventsStorage`. This is ADR 0047's rule that Markets does
   not delete rows in a table another application owns.

3. **Other applications' keys are allowed and reported.**
   - A `CASCADE` key deletes the referencing rows with their parent: a sidecar
     on `Account.uid` goes with the account, and rows in instances of the
     holdings, target-position and virtual-fund holdings storages go with their
     sets. The preflight warns about each such table. (Amended 2026-11-19: the
     delete response no longer lists them, because the delete no longer asks
     MetaTables for its impact.)
   - A `RESTRICT` key refuses the whole delete, for example a provider's orders
     or trades instance that still holds rows for the account. The preflight
     warns about the table, and the delete answers `409` with the database's
     message, which on PostgreSQL names the constraint. The provider deletes
     those rows through its own application first.

4. **The same delete on both backends.** `Account.delete(uid)` and a new
   `Account.bulk_delete(uids=...)` call the service. Under the runtime backend
   they run it in-process. Through `msm.client`, the row router runs them as
   ordinary operations, as `PortfolioGroup.bulk_delete` already calls its
   `msm.services` function. The row router runs `Account`'s own `delete`
   instead of answering `501`. The same call removes the same rows on either
   backend.

5. **Preflight.** A preflight reports, per table, how many rows the delete would
   remove, the tables in other namespaces it reaches, and what blocks it. It
   builds on `msm.services.table_impact.delete_rows_impact`, as the asset-category,
   portfolio and portfolio-group preflights do. The database enforces the same
   keys when the rows are deleted, so the preflight is advisory. (Amended
   2026-11-19: only the preflight asks MetaTables for the impact, which takes
   MetaTables seconds per table, and `delete_rows_impact` reuses an answer for
   the same table for five minutes. The impact depends on the table, not on the
   caller: the Markets API reaches MetaTables as one workload identity, ADR 0047.)

6. **Routes.** Following the asset-category and portfolio deletes:
   - `DELETE /api/v1/account/{uid}/`;
   - `POST /api/v1/account/bulk-delete/`;
   - `POST /api/v1/account/bulk-delete/preflight/`.

7. **Who may delete.** The same identities as for a portfolio. The services are
   wrapped in `registry_write("account", "delete")` and
   `registry_write("account", "bulk-delete")`, as the portfolio deletes use
   `registry_write("portfolio", ...)`. Any caller the platform admits to the
   Markets API may delete an account, as it may delete a portfolio.
   `registry_write` records the acting identity on the audit log. There is no
   other check.

8. **No partial deletes.** Virtual funds, target allocations, position sets and
   holdings sets are not deleted from an account that is kept (ADR 0049
   decision 1). `virtual-fund`, `virtual-fund-holdings-set`,
   `account-target-allocation` and `position-set` keep no remote delete. The
   one-row `delete_account` is replaced by the service in decision 1, and the
   unused `delete_account_target_allocation`, `delete_position_set` and
   `delete_virtual_fund` helpers are removed, with their repository
   counterparts.

9. **The account's portfolios, on request** (added 2026-11-19, issue 91). The
   portfolio package owns this delete, because the portfolio datasets live there
   and core `msm` does not import it (ADR 0019): `msm_portfolios.services`
   exposes `delete_account_with_portfolios`, `bulk_delete_accounts_with_portfolios`
   and their preflights, which take a runtime's context. The account routes run
   them when `delete_portfolios` is set, off by default: the query parameter of
   `DELETE /api/v1/account/{uid}/`, and the option of the bulk-delete action and
   its preflight. `Account.delete` and `Account.bulk_delete` delete the account
   alone, under both backends; nothing refuses. The delete composes core's
   account read and statements with the portfolios' own, so the same
   transaction also deletes the portfolios that the account's
   virtual funds or target rows name and that nothing references once the
   account's history is gone, with all their data, as the portfolio delete
   removes it (ADR 0049, issue 93): their rows in the seven datasets, then the
   portfolio, whose catalog row and group memberships go by `CASCADE`. A
   portfolio is kept, and the answer says why, when:
   - account history of another account references it: a virtual fund of
     another account targets it, or target rows outside this account's position
     sets name it. Account history is never rewritten (ADR 0049 decision 1);
   - the catalog places its values or weights in a table another application
     owns (ADR 0047). Markets never deletes rows there, and the portfolio row
     cannot go while they exist;
   - a key of a table the read cannot see, such as an uncatalogued instance
     another application owns, refuses its delete. Then the transaction deletes
     nothing, and a second one deletes the account alone.

   The portfolios are never deleted without the account, and a refused portfolio
   never keeps the account from being deleted.

## Rejected Alternatives

### Remove Parts Of A Kept Account's History

Deleting a virtual fund, allocation or snapshot from an account that stays
rewrites what the account targeted and how its holdings were attributed. ADR
0049 rejected it for portfolios (issue #50), and the same reasons hold here.

### Delete Rows In Other Applications' Tables

Markets could find every table in another namespace that references the
account and delete its rows explicitly. That breaks ADR 0047. It would also fail
on a hosted runtime, where ADR 0047 grants the Markets workload at most Reader on
a provider's tables. The owning application has already said what should happen through the
delete action of its key.

### Refuse Whenever Another Namespace Is Reached

Refusing any delete that cascades into another namespace overrides the action
the owning application declared, and makes a sidecar with cascade delete
impossible to use as intended. Reporting the cascade keeps it visible without
taking the decision away from the owner.

### Keep The Runtime Delete As A One-Row Delete

`Account.delete` would remove one row in-process and the whole history
remotely, so the same call would do different things on the two backends. It
would also keep failing in-process on any account with orders, trades or
holdings.

### Delete In Separate Requests

The portfolio delete removes weights, values and the row in separate requests.
For an account that would leave a partly deleted history whenever a later step
is refused, for example by a `RESTRICT` key in another namespace. One
transaction leaves either the whole account or nothing.

### Delete The Account's Portfolios In Their Own Requests

The account delete could be followed by one portfolio delete per orphaned
portfolio. Each is its own read and transaction, so a delete of an account with
several portfolios would again take many MetaTables requests, the cost issue 91
removes, and a failure between them leaves the portfolios without the account
that used them and without a record of why. One transaction answers what was
deleted and what was kept.

### A Separate Route For The Account And Its Portfolios

A second delete route would duplicate the account delete's routes and preflight.
The account routes take an option, off by default, which keeps the portfolios as
before. In Python the delete with portfolios is its own function in
`msm_portfolios`, because core `msm` cannot import the portfolio datasets
(ADR 0019); `Account.delete` keeps deleting the account alone.

### A Registry Of Portfolio Datasets In Core

Core could keep a list of the portfolio datasets that the portfolio package fills
when it is imported, so that `Account.delete` could take the option. The delete
would then depend on what the process had imported, the hook ADR 0049 rejected
for `Portfolio.delete`, and would have to refuse when nothing was registered.

### An Ownership Or Admin Check

Accounts have no owner column, and admission to the Markets API is decided by
the platform (ADR 0047). A stricter check than the portfolio delete's would make
the two registry deletes behave differently with no ms-markets rule behind it.

## Consequences

- An account's history can be removed only by deleting the account.
- A provider's orders or trades instance that holds rows for an account blocks
  its deletion until the provider removes them. Order events in a provider's
  instance stay after the account is gone.
- Rows in other applications' tables can disappear with an account through
  their own `CASCADE` keys. The preflight and the delete response list those
  tables.
- `Account.delete` under the runtime backend changes from a one-row delete to
  the cascading delete. `msm.services` and `msm.repositories` lose
  `delete_account_target_allocation`, `delete_position_set` and
  `delete_virtual_fund`.
- The Markets API gains three account routes. The release is a minor version.
- `docs/fast_api/v1/accounts.md` and the account knowledge pages describe the
  delete, its preflight and what blocks it.
- MetaTables' `delete_rows` impact reports both kinds of key from other
  namespaces: its cascade walk follows every table's declared cascade targets,
  and it adds a `restrict` edge for each registered key that targets a table the
  delete reaches. Tables the caller cannot view appear as opaque nodes.
- (Added 2026-11-19, issue 91.) An account and the portfolios only it used can go
  in one request. A portfolio another account, a virtual fund of another account
  or another application's table uses stays with all its data, and the answer
  says why. Without the option nothing changes for portfolios.

## Implementation Notes

### 2026-11-11: 3.3.0

- **Statements.** `msm.repositories.account_deletion` compiles thirteen
  statements in decision 1's order and runs them as one MetaTables statement list
  on both dialects (ADR 0026 allows lists on PostgreSQL too). The last deletes the
  account only while it still has the `unique_identifier` read before, and is
  guarded to one row: an account that vanished in between answers `404`, one that
  was renamed answers `409`, and nothing is deleted either way. Order events are
  deleted when their `order_identifier` belongs to one of the account's orders and
  to no other account's order, because orders are unique per account, not
  globally.
- **Counts.** A statement list returns only its last statement's rows, so
  `deleted_rows` and the preflight's `row_counts` come from one counting read
  just before the delete. The same read counts decision 3's Markets-side
  blockers, which refuse the delete before it is sent: orders of other accounts on
  its order managers, and virtual-fund holdings sets and rows of other accounts
  allocated from its holdings sets.
- **Other namespaces.** `account_delete_impact` splits the MetaTables impact by
  namespace: nodes outside the Markets namespace that the delete reaches are
  `other_namespace_cascades`, and `restrict` edges whose source is outside it are
  `other_namespace_restricts`. Both are warnings, because Markets cannot count
  rows in those tables. A `RESTRICT` refusal from the database becomes
  `AccountDeleteConflictError` naming those tables.
- **SQLite.** MetaTables' SQLite authorizer is also asked about the reads SQLite
  makes to enforce a foreign key, so on the local runtime the delete is refused
  while any table the caller cannot read has a key into the account tables, even
  with no referencing rows. MetaTables documents this limitation;
  [MetaTables#105](https://github.com/mainsequence-projects/MetaTables/issues/105)
  asks to lift it. The SQLite tests give the identity access to the provider
  tables and check separately that no statement names them; a strict `xfail`
  test turns red once MetaTables lifts the limitation.

  Amended in 3.4.1: MetaTables 0.1.64 lifted the limitation (#105), and
  ms-markets requires it. The SQLite tests now create the provider tables
  outside the identity, and the `xfail` marker is gone.
- **Row router.** `_owns_checked_delete` now accepts any row class that defines
  `delete` itself, so `Account.delete` and `Account.bulk_delete` run through the
  generic row path, wrapped in `registry_write("account", "delete")` and
  `registry_write("account", "bulk_delete")`. The HTTP routes use
  `registry_write("account", "delete")` and `("account", "bulk-delete")`.

### 2026-11-19: 4.1.1, issue 91

Deleting an account through the Markets API took minutes: each step was its own
MetaTables request, about 2 s per statement and about 14 s per delete impact.
The delete read the account and then counted its rows, and asked for the impact;
the bulk delete asked for it in its preflight and again to delete
([issue 91](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/91)).

- **One read.** `read_account_delete` replaces `count_account_delete_rows` and
  the separate account read. One `SELECT` from the account by uid answers whether
  it exists, its rows per table and the rows of other accounts that block it.
  Every count is a subquery on the bound account uid alone (the account's
  identifier is read in the same statement), so the database runs each once
  whatever the number of result rows. With `delete_portfolios` there is one row
  per portfolio the account's virtual funds or target rows name, with the account
  history of other accounts that references it, its catalog row's values and
  weights instances, and its rows in each dataset. Each of those counts reads only
  its portfolio's rows, through the index revision `0031` gives the datasets
  ([issue 96](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/96),
  ADR 0049's 4.1.1, issue 96 note).
- **One transaction.** The list is the 14 statements of the 3.3.0 note, then,
  with portfolios to delete, one `DELETE` per dataset for all of them and the
  portfolio `DELETE`: at most 22 of the 32 statements MetaTables allows. Each
  portfolio statement keeps only the portfolios no virtual fund or target row
  references, which, after the account's own history is gone, means no other
  account's. MetaTables checks a statement's row guard right after it runs, not
  only on the last statement, and rolls everything back on a miss, so the
  account's guard (exactly the account read before) still guards from the
  middle of the list. The last statement is guarded to delete every portfolio
  read as deletable and returns them; a portfolio referenced in between stops
  it, and the account is then deleted alone.
- **Refusals.** A key the read cannot see refuses the whole list. Markets then
  sends the account's 14 statements alone; if a key refuses those too, it is the
  account's own and `409` says so with nothing deleted. With no portfolio to
  delete, one delete is one read and one transaction; with a refused portfolio,
  one read and two transactions.
- **Deadline.** The read and the transaction run with MetaTables' longest
  deadline, 60 s (`msm.repositories.base.with_delete_deadline`), instead of its
  15 s default, which covers the whole list. With
  portfolios, the read counts and the transaction deletes each portfolio's rows in
  all seven datasets: millions of rows for a portfolio with years of daily weights
  over hundreds of assets.
- **Core and the portfolio package.** Core `msm` does not import `msm_portfolios`
  (ADR 0019), so the delete with portfolios lives in
  `msm_portfolios.repositories.account_portfolio_deletion` and
  `msm_portfolios.services.account_portfolio_deletion`. It extends core's read,
  `account_delete_read_statement`, with the portfolio columns, and appends its
  statements to core's `account_delete_statements`. It runs the transaction
  through core's `run_account_delete`, tells a vanished account from a renamed one
  with `account_delete_refused`, and answers through `account_deleted_response`,
  so both deletes check and answer the same way.
  `ACCOUNT_HISTORY_REFERENCES` and the `NOT EXISTS` condition built from it are
  core's, so both deletes and the portfolio delete use the same definition. The
  Markets API's account delete runtime includes the portfolio tables.
- **No impact in the delete.** `delete_account` and `bulk_delete_accounts` no
  longer ask MetaTables for the account table's impact, and their responses no
  longer carry `other_namespace_cascades`; the preflight still does. The `409`
  carries the database's message without the list of tables from the impact.
  `POST /api/v1/account/bulk-delete/` asks for the impact once, in its preflight,
  and a preflight within five minutes reuses it.
- **Bulk.** Each account is still deleted in its own transaction, in the order
  selected, so a portfolio only selected accounts use goes with the last of
  them. The preflight reads each account as if it were deleted alone.
- **Update statistics.** An updater run drops every row it publishes at or before
  the last time MetaTables stores for its coordinates. After a statement list
  commits, MetaTables rebuilds the stored statistics of each time-index table the
  list changed
  ([MetaTables#117](https://github.com/mainsequence-projects/MetaTables/issues/117),
  `mainsequence-metatable` 0.1.69 and later; ms-markets requires 0.1.71). So an
  account re-created under the same `unique_identifier`, whose connector publishes
  its orders, trades and events again, and a portfolio re-created under a deleted
  one's identifier start from scratch.
