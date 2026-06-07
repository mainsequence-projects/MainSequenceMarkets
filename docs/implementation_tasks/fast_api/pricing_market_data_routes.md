# FastAPI v1 Pricing Market Data Routes Implementation Plan

## Scope

Build a new FastAPI v1 route group under:

```text
/api/v1/pricing/market_data/
```

The route group lets the frontend operate the pricing market-data registry used by
`msm_pricing` pricing workflows:

- `PricingMarketDataSet`: named source sets such as `default`, `eod`, `live`, or
  scenario-specific market-data configurations.
- `PricingMarketDataSetBinding`: binding rows that map one set and one pricing
  concept to the DataNode storage UID that pricing engines should use.

The FastAPI route must remain a resolver layer only. Row behavior must be
implemented through `msm_pricing.api`; route handlers should not issue direct
repository operations unless `msm_pricing.api` is first extended.

## Current Source API Inventory

The following public API classes already exist in
`src/msm_pricing/api/market_data_bindings.py` and are exported from
`msm_pricing.api`:

- `PricingMarketDataSet`
- `PricingMarketDataSetCreate`
- `PricingMarketDataSetUpsert`
- `PricingMarketDataSetUpdate`
- `PricingMarketDataSetBinding`
- `PricingMarketDataSetBindingCreate`
- `PricingMarketDataSetBindingUpsert`
- `PricingMarketDataSetBindingUpdate`

Available operations on `PricingMarketDataSet`:

- `create(payload | **kwargs)`
- `upsert(payload | **kwargs)`
- `update(uid, payload | **kwargs)`
- `get_by_uid(uid)`
- `get_by_key(set_key)`
- `filter(limit=500, **filters)`
- `resolve_uid(market_data_set=None)`
- `delete(uid)`

Available operations on `PricingMarketDataSetBinding`:

- `create(payload | **kwargs)`
- `upsert(payload | **kwargs)`
- `update(uid, payload | **kwargs)`
- `get_by_uid(uid)`
- `get_by_set_and_concept(market_data_set_uid, concept_key)`
- `resolve_data_node_uid(market_data_set=None, concept_key=...)`
- `filter(limit=500, **filters)`
- `delete(uid)`

## Gaps To Resolve Before Full CRUD

Full CRUD source methods are now exposed by `msm_pricing.api`. Source list
methods now support reusable pagination through `list(limit, offset, **filters)`.
Remaining source API decision is search support.

List limitations:

- `filter(...)` remains a capped-list helper for source API callers that do not
  need pagination.
- `list(...)` is the method FastAPI must use for paginated responses.
- There is no search operation across display fields.
- Search is not required for the first UI release; FastAPI does not expose a
  `search` query parameter for this route group yet.

Pagination standard:

- FastAPI list endpoints must use the reusable common envelope from
  `apps/v1/schemas/common.py`: `PaginatedResponse[T]`.
- The response shape is the Django REST Framework-style limit-offset envelope:
  `{count, next, previous, results}`.
- `count` must represent the total rows matching the filters, not the current
  page length.
- Do not create resource-specific list envelopes when `PaginatedResponse[T]`
  can represent the contract.

DELETE source API status:

- `PricingMarketDataSet.delete(uid)` exists in
  `src/msm_pricing/api/market_data_bindings.py`.
- `PricingMarketDataSetBinding.delete(uid)` exists in
  `src/msm_pricing/api/market_data_bindings.py`.
- FastAPI routes must call these `msm_pricing.api` delete methods, not the
  repository directly.

## Proposed Route Shape

Use one router file:

```text
apps/v1/routers/pricing_market_data.py
```

Use one service adapter file only if needed to keep route handlers thin:

```text
apps/v1/services/pricing_market_data.py
```

Use local schemas only for HTTP envelopes and discoverability cards. Use
`msm_pricing.api` models directly for row response models.

### Discoverability

```text
GET /api/v1/pricing/market_data/
```

Purpose:

- Return a small API card explaining the two managed resources, supported
  operations, and endpoint links.
- This is a frontend-only composed response, so a local `apps/v1/schemas`
  Pydantic contract is appropriate.

Suggested response fields:

```json
{
  "resource": "pricing_market_data",
  "description": "Manage pricing market-data sets and concept bindings.",
  "resources": [
    {
      "key": "sets",
      "model": "PricingMarketDataSet",
      "list_url": "/api/v1/pricing/market_data/sets/",
      "create_url": "/api/v1/pricing/market_data/sets/",
      "upsert_url": "/api/v1/pricing/market_data/sets/upsert/"
    },
    {
      "key": "bindings",
      "model": "PricingMarketDataSetBinding",
      "list_url": "/api/v1/pricing/market_data/bindings/",
      "create_url": "/api/v1/pricing/market_data/bindings/",
      "upsert_url": "/api/v1/pricing/market_data/bindings/upsert/"
    }
  ]
}
```

### Pricing Market Data Sets

```text
GET /api/v1/pricing/market_data/sets/
```

Wrapper:

- `PricingMarketDataSet.list(limit=limit, offset=offset, status=status, set_key=set_key)`

Initial query parameters:

- `limit`
- `offset`
- `status`
- `set_key`

Response:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
      "set_key": "default",
      "display_name": "Default pricing market data",
      "description": null,
      "status": "ACTIVE",
      "metadata_json": null
    }
  ]
}
```

```text
GET /api/v1/pricing/market_data/sets/{uid}/
```

Wrapper:

- `PricingMarketDataSet.get_by_uid(uid)`

Response:

- `PricingMarketDataSet`

404 behavior:

- Return 404 if the API method returns `None`.

```text
GET /api/v1/pricing/market_data/sets/by-key/{set_key}/
```

Wrapper:

- `PricingMarketDataSet.get_by_key(set_key)`

Response:

- `PricingMarketDataSet`

```text
POST /api/v1/pricing/market_data/sets/
```

Wrapper:

- `PricingMarketDataSet.create(PricingMarketDataSetCreate)`

Request body:

- `PricingMarketDataSetCreate`

Response:

- `PricingMarketDataSet`

```text
POST /api/v1/pricing/market_data/sets/upsert/
```

Wrapper:

- `PricingMarketDataSet.upsert(PricingMarketDataSetUpsert)`

Reason:

- The source API has first-class upsert by `set_key`; expose it explicitly for
  idempotent UI setup flows instead of overloading `POST /sets/`.

Response:

- `PricingMarketDataSet`

```text
PATCH /api/v1/pricing/market_data/sets/{uid}/
```

Wrapper:

- `PricingMarketDataSet.update(uid, PricingMarketDataSetUpdate)`

Response:

- `PricingMarketDataSet`

```text
DELETE /api/v1/pricing/market_data/sets/{uid}/
```

Wrapper:

- `PricingMarketDataSet.delete(uid)`

Status:

- Source API support exists; FastAPI can wrap `PricingMarketDataSet.delete(uid)`.

Expected FastAPI response:

```json
{
  "detail": "Deleted pricing market-data set.",
  "uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
  "deleted_count": 1
}
```

### Pricing Market Data Bindings

```text
GET /api/v1/pricing/market_data/bindings/
```

Wrapper:

- `PricingMarketDataSetBinding.list(limit=limit, offset=offset, market_data_set_uid=..., concept_key=...)`

Initial query parameters:

- `limit`
- `offset`
- `market_data_set_uid`
- `concept_key`

Response:

```json
{
  "count": 2,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "binding-uid",
      "market_data_set_uid": "7f958bbf-44cc-4cb9-ad19-b41b5aa28d60",
      "concept_key": "discount_curves",
      "data_node_uid": "storage-table-uid",
      "storage_table_identifier": "DiscountCurvesStorage",
      "source": "example",
      "metadata_json": null
    }
  ]
}
```

```text
GET /api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/
```

Wrapper:

- `PricingMarketDataSetBinding.list(limit=limit, offset=offset, market_data_set_uid=market_data_set_uid)`

Purpose:

- Let the UI open one market-data set detail page and display all concept
  bindings owned by that set.

Response:

- same binding list envelope as `GET /bindings/`.

```text
GET /api/v1/pricing/market_data/bindings/{uid}/
```

Wrapper:

- `PricingMarketDataSetBinding.get_by_uid(uid)`

Response:

- `PricingMarketDataSetBinding`

```text
GET /api/v1/pricing/market_data/bindings/resolve/
```

Wrapper:

- `PricingMarketDataSetBinding.resolve_data_node_uid(market_data_set=..., concept_key=...)`

Query parameters:

- `market_data_set`: optional set key or UID. Defaults to pricing default when omitted.
- `concept_key`: required.

Response:

```json
{
  "market_data_set": "default",
  "concept_key": "discount_curves",
  "data_node_uid": "storage-table-uid"
}
```

Purpose:

- Give the UI and debugging tools an explicit way to see which storage table a
  pricing concept resolves to.

```text
POST /api/v1/pricing/market_data/bindings/
```

Wrapper:

- `PricingMarketDataSetBinding.create(PricingMarketDataSetBindingCreate)`

Request body:

- `PricingMarketDataSetBindingCreate`

Response:

- `PricingMarketDataSetBinding`

```text
POST /api/v1/pricing/market_data/bindings/upsert/
```

Wrapper:

- `PricingMarketDataSetBinding.upsert(PricingMarketDataSetBindingUpsert)`

Reason:

- The source API has first-class upsert by `(market_data_set_uid, concept_key)`.

Response:

- `PricingMarketDataSetBinding`

```text
PATCH /api/v1/pricing/market_data/bindings/{uid}/
```

Wrapper:

- `PricingMarketDataSetBinding.update(uid, PricingMarketDataSetBindingUpdate)`

Response:

- `PricingMarketDataSetBinding`

```text
DELETE /api/v1/pricing/market_data/bindings/{uid}/
```

Wrapper:

- `PricingMarketDataSetBinding.delete(uid)`

Status:

- Source API support exists; FastAPI can wrap `PricingMarketDataSetBinding.delete(uid)`.

Expected FastAPI response:

```json
{
  "detail": "Deleted pricing market-data binding.",
  "uid": "binding-uid",
  "deleted_count": 1
}
```

## Runtime Attachment Plan

The current `apps/v1` runtime bootstrap attaches core `msm` models through
`msm.start_engine(...)`. Pricing row APIs use the pricing runtime from
`msm_pricing.bootstrap`.

Required runtime work:

1. Add an `apps/v1` pricing runtime bootstrap helper that calls
   `msm_pricing.bootstrap.attach_pricing_schemas(...)`.
2. Use `MSM_AUTO_REGISTER_NAMESPACE` consistently with the existing v1 runtime.
3. Attach at least these pricing models:
   - `PricingMarketDataSet`
   - `PricingMarketDataSetBinding`
4. Do not create schemas at route runtime.
5. Do not seed or replace default bindings automatically from route handlers.
6. Startup should fail clearly if pricing MetaTables are not migrated and
   registered.

Open decision:

- Either call pricing runtime attachment from the app lifespan when the router is
  included, or from a thin service dependency before pricing row operations.
  Prefer lifespan attachment for clear startup failure.

## Implementation Task Checklist

### Source API TODOs

- [x] Add `PricingMarketDataSet.delete(uid)` to
  `src/msm_pricing/api/market_data_bindings.py`.
- [x] Add `PricingMarketDataSetBinding.delete(uid)` to
  `src/msm_pricing/api/market_data_bindings.py`.
- [x] Add focused unit tests proving both delete methods call the pricing active
  runtime and delete the correct backing table by UID.
- [x] Decide whether the frontend needs true total-count pagination for the first
  release.
- [x] Add `PricingMarketDataSet.list(limit, offset, **filters)`
  in `src/msm_pricing/api/market_data_bindings.py`.
- [x] Add `PricingMarketDataSetBinding.list(limit, offset, **filters)` in
  `src/msm_pricing/api/market_data_bindings.py`.
- [x] Add repository support for filtered row counts and offset-backed searches.
- [x] Decide whether `search` is required for the first UI release.
- [x] Search is not required for the first UI release, so do not expose a
  `search` query parameter from FastAPI yet.

### FastAPI Contracts

- [x] Add reusable `PaginatedResponse[T]` to `apps/v1/schemas/common.py`.
- [x] Create `apps/v1/schemas/pricing_market_data.py`.
- [x] Add `PricingMarketDataResourceLink` for discoverability card resources.
- [x] Add `PricingMarketDataCardResponse` for
  `GET /api/v1/pricing/market_data/`.
- [x] Use `PaginatedResponse[PricingMarketDataSet]` for dataset list responses.
- [x] Add `PricingMarketDataSetDeleteResponse` with `detail`, `uid`, and
  `deleted_count`.
- [x] Use `PaginatedResponse[PricingMarketDataSetBinding]` for binding list
  responses.
- [x] Add `PricingMarketDataSetBindingDeleteResponse` with `detail`, `uid`, and
  `deleted_count`.
- [x] Add `PricingMarketDataBindingResolveResponse` with `market_data_set`,
  `concept_key`, and `data_node_uid`.
- [x] Do not duplicate `PricingMarketDataSet`, `PricingMarketDataSetCreate`,
  `PricingMarketDataSetUpsert`, `PricingMarketDataSetUpdate`,
  `PricingMarketDataSetBinding`, `PricingMarketDataSetBindingCreate`,
  `PricingMarketDataSetBindingUpsert`, or `PricingMarketDataSetBindingUpdate`
  in `apps/v1/schemas`; import them from `msm_pricing.api`.

### Runtime Attachment

- [x] Add a pricing runtime helper in `apps/v1/runtime_bootstrap.py` or a new
  adjacent module.
- [x] The helper must call `msm_pricing.bootstrap.attach_pricing_schemas(...)`,
  not `create_pricing_schemas(...)`.
- [x] The helper must respect `MSM_AUTO_REGISTER_NAMESPACE`, matching the
  existing v1 app behavior.
- [x] The helper must attach at least `PricingMarketDataSet` and
  `PricingMarketDataSetBinding`.
- [x] Decide whether to attach pricing runtime in app lifespan or lazily from the
  pricing service adapter.
- [x] Prefer app lifespan attachment if missing pricing MetaTables should fail
  startup clearly.
- [x] Do not seed default market-data bindings from route handlers.
- [x] Do not replace default market-data bindings from route handlers.

### Service Adapter

- [x] Create `apps/v1/services/pricing_market_data.py`.
- [x] Add `pricing_market_data_card()` returning the discoverability payload.
- [x] Add `list_pricing_market_data_sets(limit, offset, status, set_key)` wrapping
  `PricingMarketDataSet.list(...)`.
- [x] Add `get_pricing_market_data_set(uid)` wrapping
  `PricingMarketDataSet.get_by_uid(uid)`.
- [x] Add `get_pricing_market_data_set_by_key(set_key)` wrapping
  `PricingMarketDataSet.get_by_key(set_key)`.
- [x] Add `create_pricing_market_data_set(payload)` wrapping
  `PricingMarketDataSet.create(payload)`.
- [x] Add `upsert_pricing_market_data_set(payload)` wrapping
  `PricingMarketDataSet.upsert(payload)`.
- [x] Add `update_pricing_market_data_set(uid, payload)` wrapping
  `PricingMarketDataSet.update(uid, payload)`.
- [x] Add `delete_pricing_market_data_set(uid)` wrapping
  `PricingMarketDataSet.delete(uid)`.
- [x] Add `list_pricing_market_data_bindings(limit, offset, market_data_set_uid, concept_key)`
  wrapping `PricingMarketDataSetBinding.list(...)`.
- [x] Add `list_pricing_market_data_set_bindings(market_data_set_uid, limit, offset)`
  wrapping `PricingMarketDataSetBinding.list(...)`.
- [x] Add `get_pricing_market_data_binding(uid)` wrapping
  `PricingMarketDataSetBinding.get_by_uid(uid)`.
- [x] Add `resolve_pricing_market_data_binding(market_data_set, concept_key)`
  wrapping `PricingMarketDataSetBinding.resolve_data_node_uid(...)`.
- [x] Add `create_pricing_market_data_binding(payload)` wrapping
  `PricingMarketDataSetBinding.create(payload)`.
- [x] Add `upsert_pricing_market_data_binding(payload)` wrapping
  `PricingMarketDataSetBinding.upsert(payload)`.
- [x] Add `update_pricing_market_data_binding(uid, payload)` wrapping
  `PricingMarketDataSetBinding.update(uid, payload)`.
- [x] Add `delete_pricing_market_data_binding(uid)` wrapping
  `PricingMarketDataSetBinding.delete(uid)`.

### Router

- [x] Create `apps/v1/routers/pricing_market_data.py`.
- [x] Add router prefix `/pricing/market_data` and tag `pricing-market-data`.
- [x] Add `GET /api/v1/pricing/market_data/`.
- [x] Add `GET /api/v1/pricing/market_data/sets/`.
- [x] Add `GET /api/v1/pricing/market_data/sets/{uid}/`.
- [x] Add `GET /api/v1/pricing/market_data/sets/by-key/{set_key}/`.
- [x] Add `POST /api/v1/pricing/market_data/sets/`.
- [x] Add `POST /api/v1/pricing/market_data/sets/upsert/`.
- [x] Add `PATCH /api/v1/pricing/market_data/sets/{uid}/`.
- [x] Add `DELETE /api/v1/pricing/market_data/sets/{uid}/`.
- [x] Add `GET /api/v1/pricing/market_data/bindings/`.
- [x] Add `GET /api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/`.
- [x] Add `GET /api/v1/pricing/market_data/bindings/{uid}/`.
- [x] Add `GET /api/v1/pricing/market_data/bindings/resolve/`.
- [x] Add `POST /api/v1/pricing/market_data/bindings/`.
- [x] Add `POST /api/v1/pricing/market_data/bindings/upsert/`.
- [x] Add `PATCH /api/v1/pricing/market_data/bindings/{uid}/`.
- [x] Add `DELETE /api/v1/pricing/market_data/bindings/{uid}/`.
- [x] Every route must declare `response_model`.
- [x] Every route must declare `summary`.
- [x] Every route must have an explicit `operation_id`.
- [x] Every route must document 404 behavior where row lookup can return `None`.
- [x] Every route must document 400 behavior for invalid payloads or unsupported
  source API state.

### App Registration

- [x] Import the pricing market-data router in `apps/v1/main.py`.
- [x] Add an `API_TAGS` entry for `pricing-market-data`.
- [x] Include the router with prefix `/api/v1`.
- [x] Verify `/openapi.json` includes all pricing market-data paths.

### Tests

- [x] Create `tests/msm/fastapi/v1/test_pricing_market_data.py`.
- [x] Test the discoverability endpoint response.
- [x] Test dataset list wraps `PricingMarketDataSet.list(...)`.
- [x] Test dataset detail returns the row from `get_by_uid(...)`.
- [x] Test dataset detail returns 404 when `get_by_uid(...)` returns `None`.
- [x] Test dataset lookup by key wraps `get_by_key(...)`.
- [x] Test dataset create wraps `PricingMarketDataSet.create(...)`.
- [x] Test dataset upsert wraps `PricingMarketDataSet.upsert(...)`.
- [x] Test dataset update wraps `PricingMarketDataSet.update(...)`.
- [x] Test dataset delete after source API delete exists.
- [x] Test binding global list wraps `PricingMarketDataSetBinding.list(...)`.
- [x] Test binding nested list filters by `market_data_set_uid`.
- [x] Test binding detail returns the row from `get_by_uid(...)`.
- [x] Test binding detail returns 404 when `get_by_uid(...)` returns `None`.
- [x] Test binding resolve wraps `resolve_data_node_uid(...)`.
- [x] Test binding create wraps `PricingMarketDataSetBinding.create(...)`.
- [x] Test binding upsert wraps `PricingMarketDataSetBinding.upsert(...)`.
- [x] Test binding update wraps `PricingMarketDataSetBinding.update(...)`.
- [x] Test binding delete after source API delete exists.
- [x] Extend `tests/msm/fastapi/v1/test_openapi.py` for pricing market-data
  paths, operation IDs, tags, and response schemas.

### Documentation

- [x] After implementation, update `docs/fast_api/v1/` with the pricing
  market-data route contracts.
- [x] Include response JSON examples for dataset list/detail and binding
  list/detail/resolve.
- [x] Document delete availability only after source API delete support is
  implemented.
- [x] Document that pricing list endpoints use `PaginatedResponse[T]` with
  `count`, `next`, `previous`, and `results`.

### Validation

- [x] Run `uv run --extra dev python -m pytest tests/msm/fastapi/v1/test_pricing_market_data.py tests/msm/fastapi/v1/test_openapi.py`.
- [x] Run `uv run --extra dev python -m ruff check apps/v1 src/msm_pricing/api tests/msm/fastapi/v1`.
- [x] Run `git diff --check`.
- [x] If `docs/fast_api/v1/` or MkDocs navigation changes, run
  `uv run --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site`.

## Test Plan

Add focused tests in:

```text
tests/msm/fastapi/v1/test_pricing_market_data.py
```

Required tests:

- OpenAPI includes pricing market-data routes and response models.
- Discoverability endpoint returns the operation card.
- Dataset list wraps `PricingMarketDataSet.filter(...)`.
- Dataset detail returns 404 when `get_by_uid(...)` returns `None`.
- Dataset create/upsert/update call the matching `msm_pricing.api` payload
  models.
- Dataset delete is covered after delete exists in `msm_pricing.api`.
- Binding list supports global and nested set-scoped listing.
- Binding resolve wraps `resolve_data_node_uid(...)`.
- Binding create/upsert/update call the matching `msm_pricing.api` payload
  models.
- Binding delete is covered after delete exists in `msm_pricing.api`.

Validation commands:

```bash
uv run --extra dev python -m pytest tests/msm/fastapi/v1/test_pricing_market_data.py tests/msm/fastapi/v1/test_openapi.py
uv run --extra dev python -m ruff check apps/v1 src/msm_pricing/api tests/msm/fastapi/v1
git diff --check
```

If implementation adds or changes written API docs:

```bash
uv run --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site
```

## Success Criteria

The task is complete when:

- The frontend can discover the pricing market-data route group.
- The frontend can list, inspect, create, upsert, and update
  `PricingMarketDataSet` rows through FastAPI wrappers.
- The frontend can list, inspect, create, upsert, update, and resolve
  `PricingMarketDataSetBinding` rows through FastAPI wrappers.
- DELETE routes exist only after delete methods are available in
  `msm_pricing.api`.
- All route handlers remain thin wrappers over `msm_pricing.api`.
- Tests prove route behavior without requiring live platform state.
