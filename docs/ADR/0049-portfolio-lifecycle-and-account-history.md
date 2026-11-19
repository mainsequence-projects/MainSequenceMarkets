# 0049. Portfolio Lifecycle And Account History

## Status

Accepted (2026-11-10), implemented in 3.2.0. Amends
[ADR 0027](0027-account-target-position-portfolio-exposure.md) (target writes
refuse a retired portfolio),
[ADR 0029](0029-account-holdings-virtual-fund-allocation-policy.md) (no
virtual-fund holdings for a retired portfolio),
[ADR 0040](0040-portfolio-temporal-ownership.md) (the portfolio updaters stop at
retirement) and [ADR 0047](0047-markets-api-application-boundary.md) (two
routes added, one removed). Implemented through
[issue #51](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/51);
the read in
[issue #49](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/49)
comes first.

## Context

An account's target is a history of `PositionSet` snapshots. Each write adds a
snapshot. The current target is the latest `PositionSet` across the account's
active `AccountTargetAllocation` rows; clearing a target writes an empty
snapshot and sets the allocation inactive. A snapshot's `TargetPositionsStorage`
rows name assets or portfolios. Applying a virtual-fund allocation creates one
`VirtualFund` per account, targeted portfolio and target allocation, and its
holdings sets and holdings record how the account's real holdings were
attributed to that portfolio.

Both reference the portfolio with `RESTRICT`:

- `TargetPositionsStorage.portfolio_uid`;
- `VirtualFund.target_portfolio_uid`. `VirtualFundHoldingsSet` and
  `VirtualFundHoldingsStorage` cascade from the fund.

The portfolio's own datasets (weights, values, rebalance state, analytics and
the engine's ledger, state and cash flows) reference `Portfolio.unique_identifier`
with `RESTRICT`. The delete routes remove all seven with the portfolio row, in one
transaction (amended 2026-11-19, issue 93; see the implementation notes).

`Portfolio` has no lifecycle state. A portfolio that should no longer be used
can be left as it is, in which case it stays selectable as an account target and
its updaters keep computing it, or it can be deleted. Deleting it is blocked
while any account's history names it, which is the protection the `RESTRICT`
references exist for. Four routes delete portfolios:

- `DELETE /api/v1/portfolio/{uid}/`, `POST /api/v1/portfolio/bulk-delete/` and
  the remote `POST /api/v1/rows/portfolio/delete/` delete the portfolio with its
  rows in its seven datasets, in one transaction, and refuse while target rows or
  virtual funds reference it, or while another application's table holds rows
  that reference it (amended 2026-11-19, issue 93).
- `POST /api/v1/portfolio/bulk-cascade-delete/` deletes every account's target
  rows and virtual funds for the portfolio, current targets included, without
  checking them, and then deletes the portfolio.

A request to remove one portfolio's rows from an account's target history, with
the account's virtual funds for it, so that the portfolio could then be deleted
([issue #50](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/50))
was declined. It removes the record of what the account targeted and of how its
holdings were attributed.

The index formula lifecycle ([ADR 0037](0037-index-formula-and-custom-calculation-framework.md))
is the only retirement in ms-markets: `draft`, `active` and `retired` versions,
an exclusive `valid_to`, and a `retire` route.

## Decision

1. **Account history is kept.** Target snapshots and virtual funds that name a
   portfolio, with their holdings sets and holdings, stay for as long as the
   account exists. No route removes a portfolio from an account's history, and
   the `RESTRICT` references stay. A portfolio is deleted only when nothing
   references it.

2. **`Portfolio.retired_at`.** A nullable, timezone-aware column. Null means the
   portfolio is live; a value means it is retired from that instant, an
   exclusive end like a formula's `valid_to`. It is the only lifecycle field:
   portfolios have no versions or drafts, and a status next to the timestamp
   could disagree with it. Retiring sets it to the server time of the request. It
   cannot be backdated, because rows dated after a backdated retirement would
   already exist, and it cannot be set in the future.

3. **Retire.** `POST /api/v1/portfolio/{uid}/retire/` and a typed
   `MarketsClient` method set `retired_at`.
   - The route is refused with `409` while any account's current target names
     the portfolio. "Current" is the definition
     `GET /api/v1/account/{account_uid}/target-positions/` uses. The response
     gives the number of accounts; the read in issue #49 lists them.
   - Retiring a retired portfolio returns it unchanged.
   - A retirement and a target write that names the portfolio are serialized on
     the portfolio row, so a current target never names a retired portfolio. The
     foreign-key check alone does not serialize them: updating `retired_at`
     takes a no-key update lock, which does not conflict with the key-share lock
     the foreign-key check takes.

4. **While a portfolio is retired:**
   - **Account targets.** No target snapshot written while the portfolio is
     retired may name it, whatever the snapshot's date. A backdated snapshot
     becomes an account's current target whenever it is the account's latest,
     so allowing earlier dates would break decision 3.
   - **Virtual funds.** Applying an allocation creates no fund for a retired
     portfolio and writes no fund holdings for it dated at or after
     `retired_at`. An allocation can be run against an explicit
     `position_set_uid`, so the target rule alone does not cover this. Planning
     without applying still works.
   - **Discovery.** The account target-candidate search
     (`GET /api/v1/account/target-allocation/targets/`) and the portfolio list
     (`GET /api/v1/portfolio/`) leave retired portfolios out unless the caller
     asks for them. A read by uid always returns the portfolio, with
     `retired_at`.
   - **Updaters.** `PortfoliosUpdater`, with the `PortfolioWeights` and
     `PortfolioRebalance` updaters it builds, and `PortfolioEngine` write no row
     dated at or after `retired_at`. Rows before it are still written, so a job
     that was behind catches up to the boundary. Once its stored data reaches
     the boundary, a run returns before computing anything. `PortfoliosUpdater`
     already loads the portfolio row on every run; `PortfolioEngine` knows only
     the portfolio identifier and reads the row once per run. Signal weights are
     keyed by signal, not by portfolio, and are not affected.
   - **Storage.** The storage tables do not enforce retirement. A check on every
     written row would cost on large shared tables, and since ADR 0047 some of
     those tables belong to other applications. A direct table write bypasses
     the flag.
   - **History.** Reads of past snapshots, virtual funds and their holdings
     resolve the portfolio as before and expose `retired_at`.

5. **Reinstate.** `POST /api/v1/portfolio/{uid}/reinstate/` and a typed
   `MarketsClient` method clear `retired_at`.
   - Retirement removes nothing, so undoing it removes nothing either. Account
     history stays consistent, because no snapshot written during the retirement
     named the portfolio.
   - On their next run the updaters resume from their last stored row and fill
     the retired period, so the series has no gap.
   - The table keeps no record that the portfolio was retired. Both routes are
     registry writes, and the acting-identity record of each call is that
     record.

6. **Delete.** `DELETE /api/v1/portfolio/{uid}/` and
   `POST /api/v1/portfolio/bulk-delete/` keep their behavior. Retirement is not a
   precondition: an unreferenced portfolio can be deleted whether or not it is
   retired.

7. **The portfolio cascade delete is removed.**
   `POST /api/v1/portfolio/bulk-cascade-delete/` (`bulkCascadeDeletePortfolios`),
   the `apps.v1` services `cascade_delete_portfolio` and
   `bulk_cascade_delete_portfolios`, the `msm_portfolios.services` functions
   `cascade_delete_portfolio_record` and `bulk_cascade_delete_portfolio_records`,
   and their response schemas and tests are deleted, with no replacement.
   Limited to unreferenced portfolios, the route would be `bulk-delete` again.

## Rejected Alternatives

### Remove A Portfolio From An Account's History

Issue #50 asked to delete, for one account and one portfolio, the target rows
naming the portfolio in every snapshot and the account's virtual funds for it.
It rewrites the account's record of what it targeted and of how its holdings
were attributed. It also does not let the portfolio be deleted once any other
account has ever targeted it: other accounts' snapshots and funds still
reference it.

### Let References Outlive The Portfolio

`SET NULL` is impossible on target rows: `ck_target_positions_target_reference`
requires `portfolio_uid` on portfolio rows, with `target_uid = portfolio_uid`.
`VirtualFund.target_portfolio_uid` is not nullable. Dropping the foreign keys
instead leaves uids that every reader must treat as possibly missing, and gives
up integrity for every consumer.

### A Status Column

A `status` of `live` or `retired`, or a status with `valid_to` as formulas have,
adds a field that can disagree with the timestamp. Formulas need a status
because they have drafts and several versions per Index; a portfolio has one
row.

### Permanent Retirement

It brings back the cost of a delete for an operation that removes nothing. A
mistaken retirement would need a new portfolio, and every producer whose
resolver binds to the old one would need a new configuration.

### Retire While Current Targets Name The Portfolio

The targets would keep pointing at a portfolio whose weights stop at
`retired_at`, and allocations against them would run on its last weights
without saying so.

### Guard The Cascade Delete

Refusing the cascade while account history references the portfolio leaves it
doing what `bulk-delete` does. A second route with the same behavior is a
leftover.

### Enforce Retirement In The Storage Tables

A trigger or check on every row written to the weights and values tables costs
on every write, and ms-markets cannot add one to a table another application
owns. The updaters already hold the portfolio row, or can read it once per run.

## Consequences

- A migration adds `Portfolio.retired_at`. Existing portfolios are live.
- The Markets API gains `retire` and `reinstate`, an opt-in parameter for
  retired portfolios on the portfolio list and the target-candidate search, and
  refusals on target writes and allocation applies. It loses
  `bulk-cascade-delete`, a breaking change. It ships in the 3.2.0 minor release,
  as the 3.0.1 patch release removed the registry-write allow-list, and leaves
  4.0.0 to ADR 0048.
- `PortfolioEngine` reads its portfolio row once per run.
- A live portfolio whose valuation source is a retired portfolio's values table
  stops updating at the boundary. ms-markets itself has no such use, but the
  generic valuation source allows it; this stays open.
- When a portfolio was retired is not queryable from the tables, only from the
  registry-write records. A lifecycle-event table can be added if that is ever
  needed.
- Data that targeted a portfolio can no longer be removed together with the
  portfolio. It goes with the accounts that hold it.
- `docs/fast_api/v1/portfolio.md`, `docs/fast_api/v1/accounts.md` and the
  portfolio and account knowledge pages describe retirement.

## Implementation Notes

### 2026-11-10: 3.2.0

Implemented with revision `0023`, which adds `Portfolio.retired_at`. ADR 0048
had assigned `0023` to its read switch, which 3.1.0 did not ship; its remaining
steps are now `0024` to `0026`, and ADR 0048 and the 3.x upgrade guide say so.

- **Current targets.** `msm.repositories.accounts.current_portfolio_target_rows_select`
  is the one definition of "an account's current target names the portfolio".
  It starts from the `TargetPositionsStorage.portfolio_uid` index and keeps a row
  when no later `PositionSet` of the same account's active allocations exists
  (ties broken by the higher uid, as the target read does). The issue #49 read,
  its count and the retire statement all use it.
- **Retire.** `msm.services.portfolio_lifecycle.retire_portfolio_record` runs one
  `UPDATE` that sets `retired_at` only on a live portfolio no current target
  names. Under PostgreSQL's READ COMMITTED, that `NOT EXISTS` sees the snapshot
  taken when the statement starts, so a target write that commits while the
  update waits on the portfolio row does not stop it. The service therefore
  counts current targets again after the update and, if any appeared, clears
  `retired_at` again (only while it still holds the value it set) and answers
  `409`. The target write is the other half: it locks the named `Portfolio` rows
  `FOR SHARE` in a CTE and gates its allocation upsert on every one being live,
  so a write that waited on an uncommitted retirement writes nothing once it
  commits. A refused write runs only the idempotent default allocation-model
  upsert. Both orderings were run against PostgreSQL 16 with two sessions.
- **Virtual funds.** Decision 4's rule is applied per allocation run: applying an
  allocation whose snapshot time is at or after a fund portfolio's `retired_at`
  writes nothing, in the Markets API route and in
  `apply_account_virtual_fund_allocation_plan`. An allocation of a snapshot taken
  before the retirement may still create or update the fund, because that
  attributes holdings from before the boundary.
- **Updaters.** `msm_portfolios.retirement` clamps each updater's window end to
  the last instant before `retired_at` and drops output rows dated at or after
  it. Decision 4 says a caught-up run "returns before computing anything"; as
  built, a run returns before reading inputs only when its stored data is at the
  last instant before the boundary. Otherwise it reads inputs for the window
  between its last stored row and the boundary, which is empty once it has
  caught up, and writes nothing. `PortfolioEngine` replays from its initial
  state on every run, so for it the clamp bounds the replay rather than skipping
  it. `PortfoliosUpdater` takes `retired_at` from the portfolio row it resolves
  at the start of a run; in a long-lived process that is the row the previous
  run's pointer upsert returned.
- **SDK writers.** The SDK `TargetPositions` updater refuses a frame that names
  a retired portfolio, reading each named portfolio once through the
  `Portfolio` row API.
- **Discovery.** The portfolio and target-candidate discovery specs declare an
  `include_retired` boolean filter, the portfolio list shows `retired_at`, and
  `GET /api/v1/portfolio/{uid}/account-targets/discovery/` describes the new
  collection.

### 2026-11-15: 3.4.2

Decision 1 held for the Markets API routes but not for the row classes
([issue #66](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/66)).
`AccountHoldingsSet`, `AccountTargetAllocation`, `PositionSet`, `VirtualFund`
and `VirtualFundHoldingsSet` inherited `MarketsMetaTableRow.delete`, which
deleted one row under the runtime backend, while the remote row router refused
it with a `501` that named service routes that do not exist. Code that removed
history passed locally and failed only against a hosted Markets API.

The five classes now set `__delete_refusal__`. `delete` raises
`MarketsOperationUnsupported` with the same text under both backends, before
any runtime call, and the row router answers `501` with it. Every other
resource without a delete answers "`<Class>.delete` is not offered remotely."
Repository and service deletes are unchanged: the account delete (ADR 0050)
still removes the history with the account.

### 2026-11-15: 3.5.0

The Markets API allocation route is removed
([#68](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/68),
ADR 0029's 3.5.0 amendment). Decision 4's rule for virtual funds is now checked
only in `apply_account_virtual_fund_allocation_plan`; the 3.2.0 note's check "in
the Markets API route" went with the route.

### 2026-11-19: issue 93

The delete routes removed the weights and values with two
`TimeIndexMetaTable.delete_after_date` calls, each its own MetaTables request,
and then deleted the portfolio row. The checks before them counted only virtual
funds and target rows. A `RESTRICT` key from any of the five other datasets, or
from another application's instance, refused the row afterwards with a `409`,
and the portfolio survived without its weights and values
([issue 93](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/93)).

- **One transaction.** `msm_portfolios.repositories.portfolio_deletion` deletes
  the portfolio's rows in all seven datasets and then the row, as one MetaTables
  statement list (MetaTables ADR 0026), as the account delete does (ADR 0050).
  The last statement deletes the row only while it still has the
  `unique_identifier` read before and no virtual fund or target row names it,
  and must delete exactly one row. A portfolio that vanished in between answers
  `404`; one renamed, or named by account history in between, answers `409`.
  Nothing is deleted either way. The `delete_after_date` calls are gone.
- **Checks first.** One read counts, per portfolio, its rows in each dataset and
  the virtual funds and target rows that name it. A table outside those whose
  `RESTRICT` key references the portfolio, listed by MetaTables' delete impact or
  named by the catalog as an instance another application owns, gets one
  read-only count. It refuses the delete while it holds rows of the portfolio,
  or when it cannot be checked, as for curves
  ([#59](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/59)).
  Markets sends it no statement (ADR 0050 decision 2). Such rows used to stay in
  place and be listed in `retained_datasets`; that field is gone.
- **Same checks in the preflight.** `POST /api/v1/portfolio/bulk-delete/preflight/`
  runs them and reports each portfolio's `row_counts` and blockers. The bulk
  delete deletes each portfolio in its own transaction, as the account bulk
  delete does.
- **Update statistics.** `delete_after_date` also rebuilt the update statistics
  MetaTables stores for each table (`index_stats`), and the portfolio updaters
  resume from a portfolio's entry there. The statement list's plain deletes do
  not touch them ([MetaTables#117](https://github.com/mainsequence-projects/MetaTables/issues/117)). Every insert into the table
  rebuilds them, so a stale entry lasts until the next write by any updater. It
  matters when a portfolio re-created under the same identifier is the first
  writer. So, after the transaction commits, the delete calls
  `delete_after_date` once on each dataset table that lost rows, scoped to the
  deleted identifiers and with a cutoff later than any row. It deletes nothing,
  not even rows a re-created portfolio wrote since, and MetaTables replaces the
  table's statistics with ones rebuilt from its rows. `set-last-update-index-time`
  would not do: it merges into the stored statistics and keeps the deleted
  entry. Each call locks the table in `SHARE ROW EXCLUSIVE` mode and scans it
  whole under a 45-second statement timeout, so it can fail on a large table. A
  failed call leaves the delete in place, is logged as an error, and is reported
  per portfolio in `statistics_not_refreshed`. The call is removed once
  MetaTables#117 is fixed.
