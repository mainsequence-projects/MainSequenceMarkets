# Provider adapter HTTP toolkit

`ms-markets` ships its provider-neutral FastAPI contracts and helpers in the
installable `msm.api.http` package. Connector repositories should import this
package instead of copying collection, discovery, bulk-preflight,
tabular-frame, operation, or structured-error models from the `apps/v1` source
tree.

## Public import boundary

```python
from msm.api.http import (
    InMemoryOperationStore,
    ResourceCollection,
    api_http_error,
    build_resource_discovery_spec,
    build_resource_collection,
    resource_column,
)
```

The package is part of the `msm` wheel. The project `apps/v1` FastAPI app
imports it directly; it has no re-export modules of its own.

## Collections and discovery

`ResourceCollection[T]`, `ResourcePageInfo`, and
`build_resource_collection(...)` implement
`command-center.resource_collection@v1`. The builder accepts an already
paginated row sequence and calculates exact page metadata. Invalid limits,
offsets, totals, or oversized pages fail instead of emitting an ambiguous
envelope.

`build_resource_discovery_spec(...)` builds strict
`command-center.resource_discovery@v1` metadata. Provider adapters supply only
their resource identity, columns, semantic filters, and authorized actions.
`resolve_resource_discovery(...)` rejects presentation query keys such as
`limit`, `offset`, and `ordering`, along with undeclared semantic keys.

## Tabular frames

`TabularFrameResponse` and `build_tabular_frame(...)` implement
`core.tabular_frame@v1`, the payload generic Command Center table, chart, and
transform consumers read. A route that returns a frame declares it with
`openapi_extra={"x-ui-contract": CORE_TABULAR_FRAME_CONTRACT}`; Adapter from API
discovery reads the contract from that declaration only.

The contract models omit unset optional fields instead of serializing them as
`null`, which the Command Center schemas reject, so a route does not need
`response_model_exclude_none`. `null` cell values in `rows` are kept. The
bulk-action and resource-collection models follow the same rule.

## Bulk actions and preflight

The public package contains the Command Center execution and preflight models,
safe relative-endpoint validation, explicit UUID selection normalization, and
the standard destructive-action descriptor. Provider services still own the
authorization checks, dependency inspection, and domain mutation itself.

## Structured errors

`api_http_error(...)` preserves already-formed `HTTPException` instances, maps
expected lookup and input failures to structured `404` and `400` responses,
and converts unexpected dependency failures to a sanitized retryable `503`.
It never includes the unexpected exception text in the public response.

Existing `apps/v1` routes that publish plain-text error details retain the
compatible `ErrorResponse` model. New provider adapters can use
`ApiErrorResponse` for machine-readable `{code, message, retryable}` details.

## Observable operations

`ObservableOperation[RequestT, ResultT]` defines the owner-pollable operation
wire shape, including steps, terminal errors, timestamps, and polling cadence.
`InMemoryOperationStore` supplies validated create, start, advance, succeed,
fail, and owner-scoped read transitions for local development and one-worker
applications.

The in-memory store is not restart-safe and must not be presented as durable.
A multi-worker or restart-safe provider deployment should persist the same
`ObservableOperation` model in a shared provider-owned repository while
preserving owner filtering on every read.

## Example

[`examples/msm/http_provider_contracts.py`](https://github.com/mainsequence-projects/MainSequenceMarkets/blob/main/examples/msm/http_provider_contracts.py)
constructs resource discovery metadata and a queued owner-scoped operation
without platform I/O.

## Verification

The public models are checked against the vendored Command Center SDK `0.1.13`
schemas and fixtures. Focused tests also cover discovery query rejection,
unexpected-error sanitization, operation transitions, and owner isolation.
