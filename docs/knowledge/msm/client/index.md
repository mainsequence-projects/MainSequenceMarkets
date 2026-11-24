# Client

`msm.client` lets an application use Markets registries through the Markets
API instead of MetaTables ([ADR 0047](../../../ADR/0047-markets-api-application-boundary.md),
decision 2). The application keeps the same `msm.api` row classes and calls;
only the backend changes:

| Backend | Who uses it | What a row call does |
| --- | --- | --- |
| `runtime` (default) | the Markets deployment, its Jobs, and code that owns Markets tables | compiled SQL through the Markets runtime |
| `remote` | every other application | one call to the Markets API, which runs the same method on its runtime |

`Portfolio.get_by_uid(uid)`, `Asset.upsert(...)` or `CurrencySpot.upsert(...)`
are the same calls under both.

## Selecting The Remote Backend

```python
from msm.api.remote import use_remote_backend
from msm.client import MarketsClient

use_remote_backend(MarketsClient.from_environment().backend)
```

or `use_remote_backend(LazyRemoteBackend())`, which finds the Markets API on
the first row call so a process that never touches a Markets registry never
needs to see it, or set `MSM_API_BACKEND=remote` (lazy as well) before the
first row call. The choice is process-wide and applies only to row classes whose table lives in the Markets
namespace. A provider's own row classes, over tables in the provider's
namespace, keep the runtime backend, so one provider process writes its own
tables with MetaTables and Markets registries through the API.

Under `remote`, `start_engine()` on a Markets row class attaches nothing.
Remove `msm.start_engine(models=[...])` calls for Markets tables from such an
application; it holds no grant on `mainsequence.markets`. When it attaches its
own tables, a Markets table that is only a foreign-key target of one of them is
referenced by physical name and not attached; a provider's own row classes
should list only its own tables in `__required_tables__`.

## Finding The Markets API

`MarketsClient.from_environment()` finds the deployment the way
MetaTables' `api_endpoint_scope` finds MetaTables: the FastAPI release named `api` (from
`source_path: api/main.py`) of the `MainSequenceMarkets` CodeRepository in the
caller's Environment, authenticated with the release token that
`ResourceRelease.resolve_runtime_access` returns. A 401 refreshes the token
once. The calling workload sees the release when its workflow grants it
`reader` on that repository's branch:

```yaml
access:
  branches:
    - repository: MainSequenceMarkets
      policy: reader
```

| Variable | Effect |
|---|---|
| `MARKETS_API_URL` | Call this URL instead of discovering one (local development). |
| `MARKETS_API_TOKEN` | Bearer token for `MARKETS_API_URL`; without it the caller's platform session is sent. |
| `MARKETS_API_RELEASE_UID` | Use this release instead of searching. |
| `MARKETS_API_RELEASE_NAME`, `MARKETS_API_REPOSITORY_NAME` | Search for another release or repository name. |

## Writes

Every create, upsert, update and delete runs through the Markets API's
`registry_write`, which records the acting identity on the API's audit log. Any
workload the platform admits to the Markets API may write; a refused operation
(`403`) raises `msm.api.remote.MarketsAccessError`, a `PermissionError`.

A table row class's remote `delete` runs the resource's service delete, with
its preflight checks, and exists only for `asset`, `asset-category`,
`calendar`, `index` and `portfolio-group`; other table row classes raise
`MarketsOperationUnsupported`. The account-history rows
(`AccountHoldingsSet`, `AccountTargetAllocation`, `PositionSet`, `VirtualFund`,
`VirtualFundHoldingsSet`) raise it under the runtime backend too, and delete
nothing: an account's history goes only with the account, through
`Account.delete` (ADR 0049, ADR 0050). `Portfolio` raises it under both
backends as well: a portfolio is deleted with its seven datasets only through
`DELETE /api/v1/portfolio/{uid}/` and `POST /api/v1/portfolio/bulk-delete/`,
which `delete_portfolio` and `bulk_delete_portfolios` call (ADR 0049,
[Portfolio Deletion](#portfolio-deletion)). Composites that implement `delete`
themselves, such as `Curve` and the pricing market-data bindings, delete
remotely as they do under the runtime backend. `CalendarSessionRule` and
`CalendarException` are among them: deleting a `user` exception is how a
calendar gets the library's answer back for a date
([Calendars](../calendars/index.md)). `AssetCalendar` is another: its `delete`
removes an asset's trading calendar link, and
`AssetCalendar.link_many(asset_identifiers, calendar_identifier=...)` links many
assets in one call.

The remote backend covers the `msm.api` rows, the `msm_portfolios.api`
metadata rows (`SignalMetadata`, `PortfolioMetadata`,
`RebalanceStrategyMetadata`) and the `msm_pricing.api` composites (curves,
curve building details, index conventions, market-data sets and bindings,
asset pricing details).

## Errors

| Markets API status | Raised by the row call |
|---|---|
| 400, 422 | `ValueError` (or `TypeError` for wrong arguments) |
| 401, 403 | `MarketsAccessError` (`PermissionError`) |
| 404 | `LookupError`; gets return `None` as under the runtime backend |
| 409 | `MarketsConflictError` (`ValueError`) |
| 501 | `MarketsOperationUnsupported` (`NotImplementedError`) |
| 500 with `error_type` `InvalidStatementError` | `MarketsInvalidStatementError` (`MarketsApiError`) |
| 502, 503 with `error_type` `UpstreamApiError` | `MarketsUpstreamError` (`MarketsApiError`) |
| any other status | `MarketsApiError` (`RuntimeError`) |

Code that catches `ValueError` or `LookupError` behaves the same under both
backends.

`MarketsUpstreamError` means the Markets API's own call to an API it depends on,
normally MetaTables, was refused or failed. It is not a fault of the arguments
checked by the Markets API, so it is not a `ValueError`. Its message carries the
reason that API gave, for example
`The upstream API answered 422: body.statement.sql: String should have at most 1000000 characters`.
`status_code` is `502` when the upstream API refused the call: the same call
will be refused again. It is `503`, and `retryable` is `True`, when the upstream
API failed or could not be reached. A `502` or `503` without that `error_type`
comes from a proxy in front of the Markets API and raises plain `MarketsApiError`.

`MarketsInvalidStatementError` means MetaTables rejected a statement the Markets
API compiled as invalid, for example a database error running it. The fault is the
Markets API's, not the arguments' or MetaTables': the same call fails the same way
again, so `retryable` is `False` and `status_code` is `500`. Its message names the
fault and carries MetaTables' reason. It is not a `MarketsUpstreamError`; a `500`
without its `error_type` raises plain `MarketsApiError`.

## Set-Based Operations

Every table row class offers the same set-based calls under both backends, so a
provider never loops over rows through the API:

```python
Asset.upsert_many([{"unique_identifier": "ACME", "asset_type": "equity"}, ...])
AccountHoldingsSet.filter(account_uid=uid, order_by="-time_index", limit=50, offset=0)
AccountHoldingsSet.count(account_uid=uid)
Asset.filter(unique_identifier__in=["A", "B"])
CalendarException.filter(calendar_uid=uid, local_date__gte=start, local_date__lte=end)
```

`upsert_many` validates each payload through the row module's `<Row>Upsert`
model and upserts them on `__upsert_keys__`. An existing row is
updated only when a value differs, so an unchanged row is not rewritten; every
payload's row still comes back, in order. Under the runtime backend,
`msm.repositories.crud.upsert_model` and `bulk_upsert_model` also give each row
an `upsert_status` of `inserted`, `updated` or `unchanged`.

A list of any length is accepted. A short list is one statement. A longer one
goes to MetaTables in several statements, each inside its limits; see
[Bulk upserts of any length](../repositories/index.md#bulk-upserts-of-any-length)
for the limits. Each statement is its own transaction, so a list that needs
several is not written atomically: when a statement fails, the rows of the
statements before it stay written and the error is raised. Call again with the
same list to finish; the rows already written come back unchanged.

`filter` takes
equality, `<field>_contains`, `<field>__in` and `<field>__gte`/`__gt`/`__lte`/
`__lt` filters, `order_by` (`-column` for descending), `limit` and `offset`;
`count` takes the same filters. Remote values are typed by the row model's
field, so a date bound arrives as a date.

The typed asset composites batch as well: `CurrencySpot.upsert_many` and
`Future.upsert_many` upsert the assets, then their details, each as one list,
and `CurrencySpot.filter(asset_uids=, base_currency_uids=, quote_currency_uids=)`
and `Future.filter(asset_uids=, underlying_index_uids=, kinds=)` read them with
their details.

## Holdings And Asset Snapshots

Account holdings and asset snapshots are Markets tables that applications
publish into rather than write:

```python
from msm.api.accounts import AccountHoldingsSnapshots
from msm.api.assets import AssetSnapshots

AccountHoldingsSnapshots.publish(
    account_uid=account_uid,
    holdings_date=as_of,
    positions=[{"asset_identifier": "ACME", "quantity": "10", "extra_details": {"source": "feed"}}],
    overwrite=True,
)
latest = AccountHoldingsSnapshots.get(account_uid=account_uid)
history = AccountHoldingsSnapshots.get_many(account_uid=account_uid, limit=10)
published = AssetSnapshots.publish(
    [{"asset_identifier": "ACME", "time_index": as_of, "name": "Acme"}]
)
current = AssetSnapshots.latest(tickers=["ACME"])
```

`AssetSnapshots.publish` writes only the rows that change their asset's
snapshot at their `time_index` and returns an `AssetSnapshotPublication`
(`written`, `skipped`). Republishing an unchanged asset writes nothing, and a
`(time_index, asset_identifier)` already stored with different values is
refused with `ValueError` (`400` from the Markets API).

A connector that registers a brokerage account, and syncs its holdings, makes one
call instead ([ADR 0051](../../../ADR/0051-account-registration-in-one-transaction.md)):

```python
client = MarketsClient.from_environment()
registered = client.register_account(
    account={"unique_identifier": "venue::account-1", "account_name": "Venue account",
             "is_paper": True, "account_is_active": True},
    assets=[{"unique_identifier": "venue::ACME",
             "asset_type": {"asset_type": "venue_equity", "display_name": "Venue equity"},
             "snapshot": {"name": "Acme Corp.", "ticker": "ACME"}}],
    cash_currency="USD",
    holdings_date=as_of,
    positions=[{"asset_identifier": "venue::ACME", "quantity": "10"},
               {"asset_identifier": "USD", "quantity": "2500"}],
)
account_uid = registered.account.uid
```

Markets creates the missing asset types, assets and cash currency asset, writes
the snapshots whose values changed, creates or updates the account and writes
the holdings, all in one transaction. A repeat with the same positions at the
same `holdings_date` writes nothing; different positions there need
`overwrite=True`. An existing asset of another type is refused with
`MarketsConflictError`. `Asset.get_or_create_currency("USD")` gets or creates
just a currency asset, with its `currency` type.

`AssetSnapshots.latest` takes exactly one of `asset_identifiers`, `asset_uids`
or `tickers` and returns each existing asset with its latest snapshot
(`AssetSnapshotReference`: name, ticker, exchange code, snapshot time; `None`
without a snapshot). `tickers` selects the assets that ever had one of those
tickers; compare the latest `ticker` to keep the ones that still carry it.

## Account Targets And Virtual-Fund Allocation

An account's target has typed client methods,
so a caller never builds their paths:

```python
client = MarketsClient.from_environment()
client.add_account_target_positions(
    account_uid,
    target_positions_date=rebalanced_at,
    positions=[{"target_type": "portfolio", "target_uid": p, "portfolio_uid": p,
                "weight_notional_exposure": 0.25}],
)
target = client.account_target_positions(account_uid)
last_five = client.account_target_positions_history(account_uid, limit=5).items
client.clear_account_target_positions(account_uid, target_positions_date=closed_at)
```

The target methods return `AccountTargetPositionsSnapshotResponse`, and the
history a page of them. Read several snapshots with
`account_target_positions_history`, which is one request, not with one
`account_target_positions` call each. A clear writes an empty snapshot, so the
history records it, and sets the account's target allocation inactive: the
current target is then empty, and the history still has the clear and what came
before it.

[Sizing Targets And Allocating](../accounts/sizing_and_allocation.md) is the
step-by-step guide for an application that sizes targets and allocates through
this client.

The allocation of an account's holdings to its virtual funds has typed methods
too ([ADR 0053](../../../ADR/0053-virtual-fund-allocation-routes-and-described-policies.md),
[ADR 0054](../../../ADR/0054-account-exposure-and-sized-fund-targets.md)). The
target states exposure, as a share of NAV. The caller sizes it into
units with its own prices and sends the units; no price or valuation is sent:

```python
(policy,) = client.virtual_fund_allocation_policies()
description = client.virtual_fund_allocation_policy(policy.id)   # arguments as JSON Schema

sized_targets = [
    {
        "target_type": "portfolio",
        "target_uid": portfolio_uid,
        "positions": [{"asset_uid": asset_uid, "quantity": 1_200, "direction": 1}],
    }
]
plan = client.plan_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    sized_targets=sized_targets,
)
for line in plan.lines:
    print(line.owner, line.asset_identifier, line.target, line.assigned, line.delta)

result = client.allocate_account_virtual_funds(
    account_uid,
    position_set_uid=target.position_set_uid,
    valuation_time=holdings_time,
    sized_targets=sized_targets,
    plan_digest=plan.plan_digest,
)
```

`plan_account_virtual_funds` writes nothing. Each line gives an owner's `target`,
what it is `assigned` and `delta = target - assigned`; `plan.account_deltas`
gives each asset's total target minus what the account holds.
`allocate_account_virtual_funds` plans again and writes in one transaction: every
fund of the target gets its holdings set, and the allocation's lines record the
sized target and the assigned units of every owner, fund or direct.
`account_virtual_fund_allocation(account_uid)` reads those lines back with each
`delta`, for the latest sync or for the one at `valuation_time`. With `plan_digest` it raises `MarketsConflictError`
when the target, its sizing or the holdings changed since that plan. A shortfall
is not refused: to write only a complete allocation, allocate only when no delta
is positive. The same plan again
writes nothing and answers `already_applied`; a different allocation of the same
snapshot raises `MarketsConflictError`.

## Portfolio Retirement

A portfolio that should no longer be used is retired, not deleted
([ADR 0049](../../../ADR/0049-portfolio-lifecycle-and-account-history.md)):

```python
page = client.portfolio_account_targets(portfolio_uid, limit=100, offset=0)
for target in page.items:
    ...  # write each account's target without the portfolio first
client.retire_portfolio(portfolio_uid)
client.reinstate_portfolio(portfolio_uid)
```

`portfolio_account_targets` returns a `ResourceCollection[PortfolioAccountTarget]`
of the accounts whose current target names the portfolio. `retire_portfolio`
returns the `Portfolio` with `retired_at` and raises `MarketsConflictError`
while that list is not empty; `reinstate_portfolio` clears it.
`bulk_retire_portfolios` retires several in one call and returns a
`PortfolioBulkRetireResponse`: the retired portfolios in `retired`, and each one a
current target names, or that does not exist, with the reason, in `failed`.

## Portfolio Deletion

A portfolio that nothing references is deleted with its rows in its seven
datasets ([Delete Portfolio](../../../fast_api/v1/portfolio.md#delete-portfolio)):

```python
deleted = client.delete_portfolio(portfolio_uid)
deleted.deleted_rows  # rows removed per dataset
client.bulk_delete_portfolios([first_uid, second_uid])
```

`delete_portfolio` deletes in one transaction and returns a
`PortfolioDeleteResponse`. It raises `LookupError`
for a missing portfolio, and `MarketsConflictError`, deleting nothing, while
account history or another application's table references it. A portfolio that
accounts referenced is retired instead.

`bulk_delete_portfolios` deletes every selected portfolio that may go, together in
one transaction, and returns a `PortfolioBulkDeleteResponse`: the deleted ones in
`deleted`, and each one that is missing or refused, with the reason, in `failed`. A
refused portfolio never stops the others, and nothing is raised for it.

## Provider Time Series

Markets reads and writes only its own tables (ADR 0060). Signal weights,
portfolio weights and portfolio values are published: an application sends
their rows to `SignalWeightsSeries`, `PortfolioWeightsSeries` and
`PortfolioValuesSeries` (`msm_portfolios.api`) and reads them back the same
way; it keeps no table for them. A signal it computes is the exception: that
signal is its own node, which writes the application's own signal table and
publishes the same rows. Under the remote backend each operation is
`POST /api/v1/rows/{resource}/{operation}/`:

```python
from msm_portfolios.api import PortfolioValuesSeries, SignalWeightsSeries

SignalWeightsSeries.publish(signal_uid, rows)        # only the signal's manager
bounds = SignalWeightsSeries.bounds([signal_uid])
page = PortfolioValuesSeries.window([portfolio_identifier], start=start)
frame = page.frame()
```

`msm_portfolios.recipes` builds on them: `publish_signal_weights`,
`signal_history`, `portfolio_history`, `weights_as_of`, `portfolio_preflight`,
`run_portfolios`, `run_portfolio`, `end_signal`, `end_signals` and `delete_private_series`. Only a row's
manager publishes to it (`managed_by`, recorded by Markets; any other caller
gets `MarketsAccessError`, HTTP 403). See
[Published Series](../../msm_portfolios/portfolios/index.md#published-series).

Other time series a provider produces live in its own namespace.
`msm.storage_instances.configured_time_index_instance` builds an instance of a
Markets time-index storage (discount curves, index fixings, pricing details,
index values, orders, trades ...) with the core storage's columns, foreign keys
and grain index, under the provider's `namespace`, `storage_app` and Alembic
`base`, all three required; the provider binds its updater with `output_table=`. Pricing
market-data bindings carry such an instance's `storage_table_uid`, and the Index
dataset catalog its table uid. `msm.storage_copies.copy_time_index_rows` copies
rows between two tables with the operator's own access, writing only the rows
the target lacks and verifying every key; `TableSeriesMove` adds the rollback
(`msm series move|rollback`). Markets takes no part in a copy.

## Portfolio Time Series

Read portfolio values and weights through the Markets API, which reads its own
tables:

```python
client = MarketsClient.from_environment()
values = client.portfolio_values([portfolio_uid], start_date=start, as_pandas=True)
weights = client.portfolio_weights([portfolio_uid], as_pandas=True)
```

Both return the `core.tabular_frame@v1` frame, or a pandas DataFrame with
`as_pandas=True`. One values request returns at most 5,000 rows; a larger
`limit` is read in pages with `offset` and returned as one frame.

Persisted calendar schedules (`PersistedCalendarSchedule`, used by
calendar-relative rebalancing) read a window with one `Calendar.sessions` call,
so they run under either backend. Under `remote` the Markets API computes the
sessions from the calendar's rules and exceptions; see
[Calendars](../calendars/index.md).

## How It Works

Each public class method of a Markets row class is wrapped when the class is
defined (`msm.api.remote.install_remote_dispatch`). Under `runtime` the
original method runs unchanged. Under `remote` the wrapper sends the bound
arguments to `POST /api/v1/rows/{resource}/{operation}/`; the Markets API runs
the same method on its runtime backend and returns the result, which the
client validates into the method's return type. `GET /api/v1/rows/` lists every
resource and operation. Because the remote operations are the row classes'
own methods, the two backends cannot drift apart.

## Related Concepts

- [Assets](../assets/index.md)
- [Models](../models/index.md)
- [Repositories](../repositories/index.md)
