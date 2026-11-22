# 0049. Portfolio Lifecycle And Account History

## Status

Note (2026-11-20): the delete notes below that count a portfolio's rows in another
application's table are replaced by
[ADR 0060](0060-producers-publish-markets-reads-only-its-own-tables.md) decision 7: the
database applies that table's key, and a `RESTRICT` refusal answers 409 with its message.

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

### 2026-11-19: 4.1.1, issue 93

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
  resume from a portfolio's entry there. After a statement list commits,
  MetaTables rebuilds the statistics of each time-index table the list changed
  ([MetaTables#117](https://github.com/mainsequence-projects/MetaTables/issues/117),
  `mainsequence-metatable` 0.1.69 and later; ms-markets requires 0.1.74), so a
  portfolio re-created under the same identifier starts from scratch.
- **Deadline.** MetaTables runs a compiled read, and a statement list as a whole
  (MetaTables ADR 0026), under a deadline of 15 seconds by default. The read that
  counts a delete's rows, for the delete and for the preflight, and the
  transaction ask for the longest it allows, 60 seconds
  (`msm.repositories.base.with_delete_deadline`).
  Measured on PostgreSQL 16 in Docker on a busy workstation (load average 155 to
  210), with five portfolios of ten years of daily data on 500 assets: 6.3 million
  rows each in the weights and rebalance-state tables, 504,000 in the event
  ledger. The transaction that deletes one of them, with 1.26 million weights
  rows, 1.26 million rebalance-state rows and 100,800 ledger rows, took 12.3 and
  14.1 seconds, most of it in the rebalance-state delete (about 6 s), the
  portfolio row's `RESTRICT` checks (3 to 4 s) and the weights delete (about
  3 s). The same deletes took 16.5 and 18.7 seconds in an earlier run at a load
  average of 130 to 250. The read took 3.3 and 5.6 seconds for that portfolio
  and 20.8 and 23.1 seconds for all five. Its count subqueries are correlated:
  PostgreSQL runs them once per portfolio, and only the weights table has an
  index that leads with `portfolio_identifier`, so the read scans each of the six
  other dataset tables once per portfolio. The 4.1.1, issue 96 note gives those six
  tables an index that leads with `portfolio_identifier`, so each count reads only
  its portfolio's rows.

### 2026-11-19: 4.1.1, issue 96

The read that counts a portfolio delete's rows counts each dataset with a subquery
on the portfolio row, which PostgreSQL runs once per selected portfolio. Six of the
seven dataset tables had no index that leads with `portfolio_identifier`, so each
of those counts read its table in full: the read grew with the number of portfolios
times the size of the tables (the "Deadline" bullet above). The account delete's
read with its portfolios ([ADR 0050](0050-account-deletion.md)) counts the same
way, and `POST /api/v1/portfolio/bulk-delete/` ran the read twice: in its preflight,
and again to delete
([issue 96](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/96)).

- **Series indexes.** Revision `0031` gives the six other dataset tables (values,
  rebalance state, analytics, event ledger, state and cash flows) the
  `(portfolio_identifier, time_index)` index that revision `0026` gave the weights
  table, and the storage models declare it as the weights model does, so the
  contract instances built from them copy it. A count, read or delete of one
  portfolio's rows then reads that portfolio's rows instead of the whole table, and
  so does the `RESTRICT` check of the portfolio row's delete.
- **Per-portfolio counts.** Both reads keep their count per portfolio row. A read
  that grouped each dataset once for the whole selection
  (`GROUP BY portfolio_identifier`) was built and measured first. Without the
  indexes it avoided reading each table once per portfolio; with them, the
  per-portfolio counts read the same index entries (about 13,000 buffers for five
  portfolios) and took less time, 0.43 s against 0.94 s for five portfolios with the
  pages in memory, because the grouped read hashes every row it counts. The grouped
  read was dropped.
- **One read per bulk delete.** `msm_portfolios.services.plan_portfolio_deletes`
  runs the delete's checks once and returns a `PortfolioDeletePlan`, whose
  `preflight()` is the preflight's report; `bulk_delete_portfolio_records(...,
  plan=...)` deletes by it. The route plans once, answers `409` from that report,
  and deletes by the same plan, so each portfolio's `deleted_rows` are its
  preflight `row_counts`. The delete is as safe as before: a reference written
  after the read stops that portfolio's transaction at its guarded statement, or
  a `RESTRICT` key refuses it, and only then is that portfolio read again, to
  name what refused it.
- **The migration on ordinary tables.** The upgrade builds the index inside its
  transaction, as `0026` did: a `SHARE` lock on each table until the upgrade
  commits, so writes to the table wait and reads do not. On the tables measured
  below it took 2.3 to 3.2 seconds with their pages in memory, and 6.8 to 15.5
  seconds on PostgreSQL 16 on the busy workstation.
- **The migration on hypertables.** A TimescaleDB DataSource makes these tables
  hypertables, one chunk per week of data by default. Built in one transaction, an
  index on a hypertable takes about two locks per chunk until the transaction ends:
  with 505 chunks per table (ten years) the six indexes held 6,087 locks, and with
  8,030 chunks across the six tables the upgrade failed with `out of shared memory`
  at `max_locks_per_transaction = 64`, PostgreSQL's default, and rolled back.
  Revision `0031` therefore builds a hypertable's index with
  `timescaledb.transaction_per_chunk`, which TimescaleDB runs one chunk per
  transaction and refuses inside a transaction block, so the migration runs it in
  Alembic's `autocommit_block()`, after committing what the upgrade did before. The
  build holds a few locks at a time whatever the number of chunks, and writes wait
  only on the chunk being indexed. On the same 8,030 chunks at the default 64, the
  upgrade took 32 s and held at most 22 locks; in one transaction, with the limit
  raised to 256, it had taken 5.6 s.
- **Interrupted and repeated.** A per-chunk build that stops part way leaves the
  hypertable's index invalid, with the chunks built so far indexed; nothing links
  those chunk indexes to it in TimescaleDB 2.22's catalog. The upgrade skips a
  valid index; otherwise it drops each chunk's index on the series columns in its
  own transaction, then the hypertable's index, and builds again. The indexes on
  ordinary tables are created only if missing. So an upgrade stopped at any point
  can be run again. On the 8,030 chunks, an upgrade stopped after 5 s, with 979 of
  the values table's 1,005 chunks indexed, left the revision at `0030` and that
  index invalid; run again, it finished in 50 s with all six indexes valid on every
  chunk. The downgrade drops a hypertable's chunk indexes one at a time too, 88 s
  for the 8,030. The builds run without a statement timeout and restore the
  session's own afterwards, so a role's default timeout cannot cut a long build
  short.
- **Dropping a hypertable's index.** TimescaleDB 2.22 drops a hypertable's index in
  one transaction, and opens every chunk of the table and every index on it to find
  the chunk indexes to drop, even when none is left: here about two locks per
  chunk, and no statement drops it chunk by chunk. Revision `0031` drops one only in
  the downgrade and in the upgrade after an interrupted build, once the chunk
  indexes are gone, so that drop only reads the chunks. The migration's session
  peaked at 1,986 locks in the upgrade after the interruption and at 4,010 in the
  downgrade: two for each chunk of the 1,005-chunk table and of a 2,005-chunk
  table. At 64 this server's lock table is sized for 9,344 locks (64 for each of
  its 146 backends), so by that count a table would need about 4,600 chunks, 88
  years at one chunk a week, before its drop could not fit on an otherwise idle
  server; the build stays at a few locks.

Measured on PostgreSQL 17.6 (the TimescaleDB 2.22 image, ordinary tables, pages in
memory, idle machine) with five portfolios of 2,520 days on 500 assets and one of
50 days (0.4 % of the rows); the weights and rebalance state tables hold 6.3 million
rows each. Medians of six runs for the reads, of two for the big deletes and six for
the small one. Before is `development` without the indexes; the reads' SQL is the
same before and after.

| Operation | Before | 4.1.1 |
| --- | ---: | ---: |
| Portfolio delete read, one portfolio | 0.47 s | 0.10 s |
| Portfolio delete read, five portfolios | 1.51 s | 0.43 s |
| Portfolio delete read, the small portfolio | 0.27 s | 9 ms |
| Account delete read, one portfolio | 0.43 s | 0.11 s |
| Account delete read, five portfolios | 1.67 s | 0.43 s |
| Delete transaction, one portfolio | 4.8 s | 3.5 s |
| Delete transaction, the small portfolio | 0.38 s | 28 ms |
| Delete transactions, five portfolios | 21 s | 22 s |

The read for five portfolios touched 586,635 buffers before and 12,821 after. The
five big deletes remove about 2.6 million rows each, which takes the same time
either way (20.6 and 21.4 s before, 15.8 and 28.0 s after). The bulk delete runs
the read once instead of twice.

### 2026-11-19: 4.1.1, `Portfolio.delete` is refused

After issue 93 the same call still did two different things. Through
`msm.client`, the row router ran the routes' service, so `Portfolio.delete`
deleted the portfolio with its seven datasets. Under the runtime backend it was
the inherited `MarketsMetaTableRow.delete`: one `DELETE` of the portfolio row,
which removed none of the datasets and was refused by the first `RESTRICT` key
from any of them. ADR 0050 rejected that split for `Account` ("Keep The Runtime
Delete As A One-Row Delete").

`Account` closed it by running its delete service under both backends.
`Portfolio` cannot: the row class is in core `msm`, while the delete service and
the seven dataset storages are in `msm_portfolios`, which core `msm` does not
import ([ADR 0019](0019-msm-portfolios-package-boundary.md)). A hook that
`msm_portfolios` fills when it is imported would keep that rule, but the runtime
`Portfolio.delete` would then depend on what the process had imported.
Applications other than the Markets deployment and the producers of Markets
tables already reach portfolios through the Markets API (ADR 0047).

- `Portfolio` sets `__delete_refusal__`, as the account-history rows do (the
  3.4.2 note). `Portfolio.delete` raises `MarketsOperationUnsupported` under both
  backends, before any runtime call, and names the two routes below. The remote
  `POST /api/v1/rows/portfolio/delete/`, which the context lists among the
  routes that delete portfolios, answers `501` with the same text: the row
  router no longer has a service delete for `portfolio`, and `GET /api/v1/rows/`
  no longer lists `delete` for it.
- `DELETE /api/v1/portfolio/{uid}/` and `POST /api/v1/portfolio/bulk-delete/`
  are the only portfolio deletes; this change does not alter them. The single
  delete answers `404` for a missing portfolio and `409` when a reference
  refuses it; the bulk delete answers `409` naming each portfolio that is
  missing or refused.
- The unused one-row helpers `msm.services.delete_portfolio`,
  `msm.repositories.delete_portfolio` and
  `msm.repositories.build_delete_portfolio_operation` are removed.

### 2026-11-20: unreleased, `MarketsClient` calls the portfolio delete routes

- `MarketsClient.delete_portfolio` and `MarketsClient.bulk_delete_portfolios` call
  `DELETE /api/v1/portfolio/{uid}/` and `POST /api/v1/portfolio/bulk-delete/` from
  Python and return `PortfolioDeleteResponse` and `PortfolioBulkDeleteResponse`. Those
  response models moved from the API app's schemas into `msm.api.portfolios`, where the
  client takes its models; the wire contract is unchanged.
- `Portfolio.delete`'s refusal, and the `501` of `POST /api/v1/rows/portfolio/delete/`,
  name the two methods next to the routes.
