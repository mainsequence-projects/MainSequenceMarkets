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
application; it holds no grant on `mainsequence.markets`.

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

Remote deletes run the resource's service delete, with its preflight checks,
and exist only for `asset`, `asset-category`, `calendar`, `index`, `portfolio`
and `portfolio-group`; other row classes raise
`MarketsOperationUnsupported`.

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
