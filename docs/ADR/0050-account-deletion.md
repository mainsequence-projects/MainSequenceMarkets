# 0050. Account Deletion

## Status

Accepted (2026-11-11), implemented in 3.3.0 through
[issue #58](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/58).
Builds on [ADR 0049](0049-portfolio-lifecycle-and-account-history.md) decision 1
(account history is kept for as long as the account exists) and amends
[ADR 0047](0047-markets-api-application-boundary.md): the account gets delete
routes, and the row router runs `Account`'s own `delete`.

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
     sets. The preflight warns about each such table, and the delete response
     lists them.
   - A `RESTRICT` key refuses the whole delete, for example a provider's orders
     or trades instance that still holds rows for the account. The preflight
     reports the table as a blocker, and the delete answers `409` naming it. The
     provider deletes those rows through its own application first.

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
   keys when the rows are deleted, so the preflight is advisory.

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
- **Row router.** `_owns_checked_delete` now accepts any row class that defines
  `delete` itself, so `Account.delete` and `Account.bulk_delete` run through the
  generic row path, wrapped in `registry_write("account", "delete")` and
  `registry_write("account", "bulk_delete")`. The HTTP routes use
  `registry_write("account", "delete")` and `("account", "bulk-delete")`.
