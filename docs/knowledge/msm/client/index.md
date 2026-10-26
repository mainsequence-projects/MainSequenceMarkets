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

or set `MSM_API_BACKEND=remote` before the first row call. The choice is
process-wide and applies only to row classes whose table lives in the Markets
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
`metatables.endpoint` finds MetaTables: the FastAPI release named `api` (from
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

## Writes And The Registry Write Policy

Every create, upsert, update and delete runs through the Markets API's
`registry_write`, so the registry write policy applies: an application may
write a resource only when the Environment's `MARKETS_REGISTRY_WRITERS`
constant lists its workload User uid for that resource or for `"*"`. A refused
write raises `msm.api.remote.MarketsAccessError`, a `PermissionError`. See
[the FastAPI guide](../../../fast_api/v1/index.md) for the constant's format.

A table row class's remote `delete` runs the resource's service delete, with
its preflight checks, and exists only for `asset`, `asset-category`,
`calendar`, `index`, `portfolio` and `portfolio-group`; other table row classes
raise `MarketsOperationUnsupported`. Composites that implement `delete`
themselves, such as `Curve` and the pricing market-data bindings, delete
remotely as they do under the runtime backend.

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

Code that catches `ValueError` or `LookupError` behaves the same under both
backends.

## Set-Based Operations

Every table row class offers the same set-based calls under both backends, so a
provider never loops over rows through the API:

```python
Asset.upsert_many([{"unique_identifier": "ACME", "asset_type": "equity"}, ...])
AccountHoldingsSet.filter(account_uid=uid, order_by="-time_index", limit=50, offset=0)
AccountHoldingsSet.count(account_uid=uid)
Asset.filter(unique_identifier__in=["A", "B"])
```

`upsert_many` validates each payload through the row module's `<Row>Upsert`
model and writes them in one statement on `__upsert_keys__`. `filter` takes
equality, `<field>_contains` and `<field>__in` filters, `order_by` (`-column`
for descending), `limit` and `offset`; `count` takes the same filters.

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
AssetSnapshots.publish([{"asset_identifier": "ACME", "time_index": as_of, "name": "Acme"}])
```

Their write-policy resources are `account-holdings` and `asset-snapshots`.

## Portfolio Time Series

Time series are not row calls. Read portfolio values and weights from the
catalogued instance tables through the Markets API:

```python
client = MarketsClient.from_environment()
values = client.portfolio_values([portfolio_uid], start_date=start, as_pandas=True)
weights = client.portfolio_weights([portfolio_uid], as_pandas=True)
```

Both return the `core.tabular_frame@v1` frame, or a pandas DataFrame with
`as_pandas=True`.

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
