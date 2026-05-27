# 0013. API v1 Index Route Plan

## Status

Proposed

## Context

`apps/v1` already exposes a simple asset list route at
`GET /api/v1/asset/` and the broader asset-category surface. The next required
addition is a simple index registry route built with the same list-style
boundary, but backed by the index reference model rather than `AssetTable`.

The underlying model already exists in this repository as
`src/msm/models/indices.py::IndexTable`, and the typed library row API already
exists as `src/msm/api/indices.py::Index`.

The new route must follow the existing `apps/v1` standards:

- `apps/v1` is a resolver layer only;
- reusable logic belongs under `src/`;
- every endpoint must declare an explicit response model;
- the route must be documented through FastAPI metadata and OpenAPI.

This ADR is intentionally narrow. It plans only the simple list endpoint for
indexes, not a full index CRUD or detail surface.

## Decision

`apps/v1` will add a simple list route for indexes:

- `GET /api/v1/index/`

This route will mirror the current `GET /api/v1/asset/` boundary:

- accepts `response_format=frontend_list`
- accepts `search`, `limit`, and `offset`
- returns a plain JSON array of list rows
- rejects unsupported `response_format` values with `400`

### Route Mapping

| Pattern source | API v1 route | Purpose |
| --- | --- | --- |
| `GET /orm/api/assets/asset/?response_format=frontend_list&search=&limit=&offset=` | `GET /api/v1/index/?response_format=frontend_list&search=&limit=&offset=` | Reuse the existing asset-list route shape for the index reference registry. |

### Contract Plan

The route will add an explicit list-row schema under `apps/v1/schemas/`:

- `IndexListRow`
  - `uid`
  - `unique_identifier`
  - `display_name`
  - `description`
  - `provider`

Response shape:

- `GET /api/v1/index/` returns `IndexListRow[]`

`metadata_json` from `IndexTable` is intentionally not part of the first list
contract. This route is meant to stay small and predictable, like the current
asset list route. If the frontend later needs provider-specific metadata, that
should be added explicitly as a follow-up contract change rather than exposed
implicitly.

### Search Semantics

The route will support case-insensitive search across:

- `uid`
- `unique_identifier`
- `display_name`
- `description`
- `provider`

Pagination semantics will match the asset list route exactly:

- `limit` and `offset` are accepted as query parameters
- the response remains a plain list rather than a pagination wrapper

### Implementation Boundary

The HTTP boundary belongs under `apps/v1`, while the index catalog resolution
must live under `src/`.

Planned boundary:

- `apps/v1/main.py`
  - router registration only
- `apps/v1/routers/indices.py`
  - route declaration and HTTP parameter validation
- `apps/v1/schemas/indices.py`
  - `IndexListRow`
- `apps/v1/services/indices.py`
  - thin adapter from the router into `src/`
- `src/msm/services/...`
  - reusable index catalog listing and search projection

Because the current `apps/v1` catalog composition already lives in
`src/msm/services/asset_master_lists.py`, the initial implementation may add a
`list_index_catalog_rows(...)` helper there instead of creating a brand-new
module immediately.

### Compatibility Rules

- `GET /api/v1/index/` must accept `response_format=frontend_list`
- unsupported `response_format` values must fail with a clear `400`
- the route must not invent fields that are not backed by `IndexTable`
- the route must not model indexes as assets

## Implementation Plan

- [ ] Add `IndexListRow` under `apps/v1/schemas/indices.py`.
- [ ] Add `apps/v1/routers/indices.py`.
- [ ] Register the router in `apps/v1/main.py`.
- [ ] Add a reusable `src/` helper that reads and filters index rows.
- [ ] Add focused tests under `tests/msm/fastapi/v1/test_indices.py`.
- [ ] Verify `/openapi.json` exposes the route and contract clearly.
- [ ] Update `docs/fast_api/v1/index.md` after the route is implemented.

## Open Questions

- whether the initial list route should expose `metadata_json` at all;
- whether the first implementation should reuse `msm.api.indices.Index.filter`
  directly or add a dedicated `src/msm/services` helper around the underlying
  table access;
- whether a future `POST /api/v1/index/query/` compatibility route will be
  needed, or whether the simple `GET` list route is enough for the client.

## Consequences

This plan keeps the index API addition deliberately small. It follows the
existing `apps/v1` asset-list boundary instead of introducing a larger index
surface prematurely, while still preserving the core rule that HTTP resolution
stays in `apps/v1` and reusable behavior stays under `src/`.
