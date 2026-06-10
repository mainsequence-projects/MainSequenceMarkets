# FastAPI v1 Portfolio Routes Implementation Plan

## Success Condition

Build a new FastAPI v1 route group under:

```text
/api/v1/portfolio/
```

The route group lets the frontend list portfolio identity rows, open one
portfolio detail page, render a latest-weights tab, and delete portfolios. It
must not expose portfolio creation routes in this task.

The implementation is successful when:

- portfolio list/detail/delete routes exist under `apps/v1`
- latest portfolio weights are readable through a portfolio detail tab endpoint
- all route responses have explicit Pydantic response models
- core portfolio behavior and storage reads live under `src/`, not inside route
  handlers
- focused tests under `tests/msm/fastapi/v1/` pass
- OpenAPI documents every portfolio endpoint

## Scope

In scope:

- `GET /api/v1/portfolio/`
- `GET /api/v1/portfolio/{uid}/`
- `GET /api/v1/portfolio/{uid}/summary/`
- `GET /api/v1/portfolio/{uid}/weights/`
- `GET /api/v1/portfolio/{uid}/weights/?weights_date=<iso datetime>`
- `DELETE /api/v1/portfolio/{uid}/`
- `POST /api/v1/portfolio/bulk-delete/`
- source helpers needed to keep the FastAPI layer thin
- documentation under `docs/fast_api/v1/`

Out of scope:

- portfolio creation
- portfolio update
- portfolio construction runs
- signal, rebalance, virtual-fund, or price-source management
- expanding account target-position portfolio rows into asset-level exposure
- historical weight cleanup beyond the explicit delete contracts documented in
  `docs/implementation_tasks/fast_api/portfolio_delete_cleanup.md`

## Model And Relationship Analysis

### Portfolio Identity

Core portfolio identity is `msm.models.portfolios.core.PortfolioTable` and the
public row model is `msm.api.portfolios.Portfolio`.

Fields exposed by the current public row model:

- `uid`
- `unique_identifier`
- `calendar_name`
- `calendar_uid`
- `published_index_uid`
- `portfolio_weights_data_node_uid`
- `signal_weights_data_node_uid`
- `portfolio_data_node_uid`
- `backtest_table_price_column_name`

`PortfolioTable` is the source of truth for the portfolio identity and runtime
configuration pointers. A portfolio is not an asset. Do not expose portfolio
identity through `AssetTable` and do not add asset-shaped fields to portfolio
responses.

### Portfolio Metadata

Human-facing metadata lives in
`msm_portfolios.models.portfolios.metadata.PortfolioMetadataTable`, exposed as
`msm_portfolios.api.portfolios.PortfolioMetadata`.

Important boundary:

- `PortfolioMetadataTable.unique_identifier` matches
  `PortfolioTable.unique_identifier` by convention.
- There is no database foreign key between `PortfolioTable` and
  `PortfolioMetadataTable`.
- Detail composition may include metadata, but deletion of `PortfolioTable`
  must not pretend metadata was automatically cascade-deleted unless the code
  explicitly deletes it.

### Portfolio Publication Linkage

`PortfolioTable.published_index_uid` optionally points to `IndexTable.uid`.
It is publication metadata only. It is not required to read or delete portfolio
weights, portfolio values, account target expansion, or virtual-fund
allocation.

Latest weights resolve from the core portfolio identity. `PortfolioWeightsStorage`
does not use `portfolio_uid` as its dimension. It is keyed by:

```text
time_index
portfolio_identifier
asset_identifier
```

Therefore the latest-weights endpoint must resolve:

```text
PortfolioTable.uid
  -> PortfolioTable.unique_identifier
  -> PortfolioWeightsStorage.portfolio_identifier
```

If a portfolio exists, its `unique_identifier` is the weight storage coordinate.
Return 404 only when the portfolio row itself does not exist.

### Portfolio Weights Storage

`msm_portfolios.data_nodes.portfolios.storage.PortfolioWeightsStorage` stores
the latest weights tab data.

Rows expose:

- `time_index`
- `portfolio_identifier`
- `asset_identifier`
- `weight`
- `weight_before`
- `price_current`
- `price_before`
- `volume_current`
- `volume_before`

The frontend weight row should use `asset_identifier` as the stable row-level
asset key. When `include_asset_detail=true`, the response may add an `asset`
object resolved from core `AssetTable` plus latest `AssetSnapshotsStorage`
labels, following the same source rule used by account holdings and target
positions:

- `asset.uid`
- `asset.unique_identifier`
- `asset.current_snapshot.name`
- `asset.current_snapshot.ticker`

Do not use OpenFIGI as the source for name or ticker in this endpoint.

### Portfolio Values Storage

`msm_portfolios.data_nodes.portfolios.storage.PortfoliosStorage` stores
portfolio value series. It is useful for a future performance/value tab, but it
is not required for this task because the requested tab is latest weights.

### Delete Constraints

`TargetPositionsStorage.portfolio_uid` references `PortfolioTable.uid` with
`ondelete="RESTRICT"`. A portfolio that is referenced by account target-position
rows may fail deletion.

FastAPI should translate that backend failure into `409 Conflict` with a clear
message. It should not silently delete target-position history.

## Source API Inventory

Available today:

- `msm.api.portfolios.Portfolio`
  - inherits `get_by_uid(uid)`
  - inherits `get_by_unique_identifier(unique_identifier)`
  - inherits `filter(limit=500, **filters)`
  - inherits `delete(uid)`
  - exposes the core portfolio row contract
- `msm_portfolios.api.portfolios.PortfolioMetadata`
  - inherits `get_by_uid(uid)`
  - inherits `get_by_unique_identifier(unique_identifier)`
  - inherits `filter(limit=500, **filters)`
  - inherits `delete(uid)`
- `src/msm/repositories/portfolios.py`
  - has search and delete operations, but search currently only accepts
    `limit` and does not expose `offset` or total `count`
- `src/msm_portfolios/data_nodes/portfolios/storage.py`
  - declares `PortfolioWeightsStorage`, but there is no dedicated public
    latest-weights response service yet

Source gaps to close:

- add reusable source-level portfolio list support with `limit`, `offset`, and
  total count
- add reusable source-level portfolio detail composition
- add reusable source-level latest-weights snapshot resolution
- add reusable source-level portfolio delete and bulk-delete helpers with
  frontend-safe result contracts
- add or reuse a generic row pagination helper instead of building one-off list
  envelopes per route

## Runtime Bootstrap Requirements

The portfolio route must not start a second markets runtime lazily from a route
or service.

Implementation must use one startup-time runtime attachment path for the full
`apps/v1` model set. Because latest weights use `PortfolioWeightsStorage` and
metadata uses `PortfolioMetadataTable`, the runtime model set must include:

- `Portfolio`
- `Index`
- `Asset`
- `AssetSnapshotsStorage`
- `PortfolioMetadata`
- `PortfolioWeightsStorage`

Use `msm_portfolios.start_engine(...)` only as the single startup owner when
portfolio-specific models or storage are included. Do not pass unresolved
portfolio-only string names directly into `msm.start_engine(...)`; that is what
causes unknown model selector errors.

## Proposed Route Shape

Use:

```text
apps/v1/routers/portfolios.py
apps/v1/services/portfolios.py
apps/v1/schemas/portfolios.py
```

`apps/v1` remains the HTTP resolver layer. The route handlers should call
helpers under `src/` or a thin `apps/v1/services/portfolios.py` adapter that
delegates into `src/`.

### List Portfolios

```text
GET /api/v1/portfolio/
```

Query parameters:

- `response_format=frontend_list`
- `search`
- `calendar_uid`
- `calendar_name`
- `limit`
- `offset`

Response model:

```text
PaginatedResponse[msm.api.portfolios.Portfolio]
```

Example:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "portfolio-uid",
      "unique_identifier": "example-sleeve",
      "calendar_name": "CRYPTO_24_7",
      "calendar_uid": null,
      "published_index_uid": "index-uid",
      "portfolio_weights_data_node_uid": null,
      "signal_weights_data_node_uid": null,
      "portfolio_data_node_uid": null,
      "backtest_table_price_column_name": "close"
    }
  ]
}
```

Notes:

- List rows should use the core `Portfolio` public model.
- Do not create a local projection only to rename fields.
- `count` must be the total matching row count, not page length.

### Get Portfolio Detail

```text
GET /api/v1/portfolio/{uid}/
```

Response model:

```text
PortfolioDetailResponse
```

This is a composed frontend detail response, so a local schema is appropriate.

Example:

```json
{
  "portfolio": {
    "uid": "portfolio-uid",
    "unique_identifier": "example-sleeve",
    "calendar_name": "CRYPTO_24_7",
    "calendar_uid": null,
    "published_index_uid": "index-uid",
    "portfolio_weights_data_node_uid": null,
    "signal_weights_data_node_uid": null,
    "portfolio_data_node_uid": null,
    "backtest_table_price_column_name": "close"
  },
  "metadata": {
    "uid": "metadata-uid",
    "unique_identifier": "example-sleeve",
    "description": "Example sleeve portfolio."
  },
  "tabs": [
    {
      "key": "latest_weights",
      "label": "Latest Weights",
      "url": "/api/v1/portfolio/portfolio-uid/weights/?order=desc&limit=1&include_asset_detail=true"
    }
  ],
  "links": {
    "summary": "/api/v1/portfolio/portfolio-uid/summary/",
    "latest_weights": "/api/v1/portfolio/portfolio-uid/weights/",
    "delete": "/api/v1/portfolio/portfolio-uid/"
  }
}
```

404 behavior:

- return 404 when no `Portfolio` exists for `{uid}`
- do not return 404 just because metadata is missing
- do not return 404 just because latest weights are missing

### Get Portfolio Summary

```text
GET /api/v1/portfolio/{uid}/summary/
```

Response model:

```text
FrontEndDetailSummary
```

Use the existing reusable summary contract. Populate `entity.id` with the
portfolio `uid` string, never a numeric ID.

Suggested fields:

- title: `Portfolio.unique_identifier`
- inline fields: `uid`, `unique_identifier`, `calendar_uid`,
  `published_index_uid`
- highlight fields: `calendar_name`
- stats: latest weights count when cheap to resolve, otherwise omit or return
  no stats rather than issuing an expensive read
- extensions: detail and latest-weights endpoint links

### Get Latest Portfolio Weights

```text
GET /api/v1/portfolio/{uid}/weights/
```

Query parameters:

- `order=desc`
- `limit=1`
- `include_asset_detail=true`
- `weights_date=<iso datetime>` for an exact snapshot

Response model:

```text
PortfolioWeightsSnapshotResponse
```

The first implementation should mirror account snapshot behavior: the endpoint
returns one snapshot, and `limit` is constrained to `1`.

Example:

```json
{
  "portfolio_uid": "portfolio-uid",
  "portfolio_unique_identifier": "example-sleeve",
  "published_index_uid": "index-uid",
  "portfolio_identifier": "example-sleeve",
  "weights_date": "2026-06-07T10:30:00Z",
  "resolution_warning": null,
  "weights": [
    {
      "time_index": "2026-06-07T10:30:00Z",
      "portfolio_identifier": "example-sleeve",
      "asset_identifier": "example-asset-btc",
      "weight": "0.600000000000000000",
      "weight_before": "0.550000000000000000",
      "price_current": "100.0",
      "price_before": "95.0",
      "volume_current": null,
      "volume_before": null,
      "asset": {
        "uid": "asset-uid",
        "unique_identifier": "example-asset-btc",
        "current_snapshot": {
          "name": "Bitcoin",
          "ticker": "BTC"
        }
      }
    }
  ]
}
```

Empty snapshot when the portfolio exists but no weights are available:

```json
{
  "portfolio_uid": "portfolio-uid",
  "portfolio_unique_identifier": "example-sleeve",
  "published_index_uid": "index-uid",
  "portfolio_identifier": "example-sleeve",
  "weights_date": null,
  "resolution_warning": null,
  "weights": []
}
```

404 behavior:

- return 404 only when the portfolio `uid` does not exist

### Get Portfolio Weights By Date

```text
GET /api/v1/portfolio/{uid}/weights/?weights_date=<iso datetime>&include_asset_detail=true
```

This is the exact-date mode for the same weights snapshot endpoint. It must
return the weight snapshot whose `PortfolioWeightsStorage.time_index` equals the
requested ISO timestamp.

Query parameters:

- `weights_date`: required for exact-date mode; ISO 8601 timestamp
- `include_asset_detail=true`
- `limit=1`

Behavior:

- `weights_date` takes precedence over `order`
- return 200 with an empty `weights` array when the portfolio exists but there
  are no rows for the requested timestamp
- return 404 only when the portfolio `uid` does not exist

Example request:

```text
GET /api/v1/portfolio/portfolio-uid/weights/?weights_date=2026-06-07T10:30:00Z&include_asset_detail=true
```

Example response:

```json
{
  "portfolio_uid": "portfolio-uid",
  "portfolio_unique_identifier": "example-sleeve",
  "published_index_uid": "index-uid",
  "portfolio_identifier": "example-sleeve",
  "weights_date": "2026-06-07T10:30:00Z",
  "resolution_warning": null,
  "weights": [
    {
      "time_index": "2026-06-07T10:30:00Z",
      "portfolio_identifier": "example-sleeve",
      "asset_identifier": "example-asset-btc",
      "weight": "0.600000000000000000",
      "weight_before": "0.550000000000000000",
      "price_current": "100.0",
      "price_before": "95.0",
      "volume_current": null,
      "volume_before": null,
      "asset": {
        "uid": "asset-uid",
        "unique_identifier": "example-asset-btc",
        "current_snapshot": {
          "name": "Bitcoin",
          "ticker": "BTC"
        }
      }
    }
  ]
}
```

### Delete Portfolio

```text
DELETE /api/v1/portfolio/{uid}/
```

Response model:

```text
DeleteResponse
```

Example:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1,
  "deleted_weights_count": 4
}
```

Behavior:

- delete the core `PortfolioTable` row by `uid`
- delete matching `PortfolioWeightsStorage` rows through
  `Portfolio.unique_identifier -> PortfolioWeightsStorage.portfolio_identifier`
- return 404 when the portfolio does not exist
- return 409 when the portfolio is referenced by target positions or other
  protected rows
- do not delete `PortfoliosStorage` rows as part of this operation
- do not delete `PortfolioMetadataTable` by default unless the delete contract
  explicitly adds a `delete_metadata=true` option

### Bulk Delete Portfolios

```text
POST /api/v1/portfolio/bulk-delete/
```

Request model:

```json
{
  "uids": ["portfolio-uid-1", "portfolio-uid-2"]
}
```

Response model:

```text
BulkDeleteResponse
```

Example:

```json
{
  "detail": "Deleted 2 portfolios.",
  "deleted_count": 2,
  "failed": []
}
```

If some rows are protected:

```json
{
  "detail": "Deleted 1 portfolio; 1 portfolio could not be deleted.",
  "deleted_count": 1,
  "failed": [
    {
      "uid": "protected-portfolio-uid",
      "reason": "Portfolio is referenced by target positions."
    }
  ]
}
```

## Implementation Tasks

### Source Layer

- [x] Add or reuse a source-level pagination helper that returns `count` and
  page rows for row APIs backed by `MarketsMetaTableRow`.
- [x] Extend portfolio search/list support to accept `limit`, `offset`,
  `search`, `calendar_uid`, and `calendar_name`.
- [x] Ensure portfolio list count uses the same filters as portfolio list rows.
- [x] Add a reusable source helper that resolves one portfolio detail by `uid`
  and joins optional metadata by `unique_identifier`.
- [x] Add a reusable source helper that resolves
  `Portfolio.uid -> Portfolio.unique_identifier`.
- [x] Add a reusable source helper that reads one latest
  `PortfolioWeightsStorage` snapshot by `portfolio_identifier`.
- [x] Add exact-date latest weights support using `weights_date`.
- [x] Add latest weights asset-detail enrichment from `AssetTable` and latest
  `AssetSnapshotsStorage`, not OpenFIGI.
- [x] Add reusable single portfolio delete helper that maps protected-row
  failures to an explicit domain error the FastAPI route can translate to 409.
- [x] Add reusable bulk portfolio delete helper that reports deleted and failed
  rows without pretending partial failures succeeded.

### FastAPI Schemas

- [x] Add `apps/v1/schemas/portfolios.py`.
- [x] Reuse `msm.api.portfolios.Portfolio` for list row contracts.
- [x] Reuse `msm_portfolios.api.portfolios.PortfolioMetadata` for metadata
  where it is embedded in detail responses.
- [x] Add local `PortfolioDetailResponse` for composed detail, tabs, and links.
- [x] Add local `PortfolioWeightsSnapshotResponse`.
- [x] Add local `PortfolioWeightRow`.
- [x] Add local `PortfolioWeightAssetReference` matching the account target
  position asset detail pattern.
- [x] Add or reuse `DeleteResponse` and `BulkDeleteResponse` instead of raw
  untyped success dictionaries.

### FastAPI Services

- [x] Add `apps/v1/services/portfolios.py`.
- [x] Keep the service as a thin adapter around `src` helpers.
- [x] Do not issue direct SQLAlchemy or MetaTable operations from
  `apps/v1/services/portfolios.py`.
- [x] Validate that missing portfolio rows return `None` so routers can raise
  404 consistently.
- [x] Validate that missing weights return an empty snapshot, not 404.

### FastAPI Router

- [x] Add `apps/v1/routers/portfolios.py`.
- [x] Register the router in `apps/v1/main.py`.
- [x] Implement `GET /api/v1/portfolio/`.
- [x] Implement `GET /api/v1/portfolio/{uid}/`.
- [x] Implement `GET /api/v1/portfolio/{uid}/summary/`.
- [x] Implement `GET /api/v1/portfolio/{uid}/weights/`.
- [x] Implement `DELETE /api/v1/portfolio/{uid}/`.
- [x] Implement `POST /api/v1/portfolio/bulk-delete/`.
- [x] Do not implement `POST /api/v1/portfolio/`.
- [x] Do not implement `PATCH /api/v1/portfolio/{uid}/`.
- [x] Add `summary`, description, query parameter descriptions, response models,
  and operation IDs for every route.

### Runtime Bootstrap

- [x] Update `apps/v1/runtime_bootstrap.py` so the startup model set includes
  portfolio metadata and portfolio weights storage.
- [x] Use the supported `msm_portfolios.start_engine(...)` resolution path when
  portfolio-specific models are in the v1 startup set.
- [x] Ensure startup still happens once and target-position routes do not start
  a second runtime.
- [x] Add regression tests proving startup does not call incompatible
  `msm.start_engine(...)` and `msm_portfolios.start_engine(...)` sequences.

### Tests

- [x] Add focused tests in `tests/msm/fastapi/v1/test_portfolios.py`.
- [x] Test portfolio list returns `PaginatedResponse[Portfolio]`.
- [x] Test portfolio list passes `search`, `limit`, and `offset` to the source
  helper.
- [x] Test portfolio detail returns portfolio, metadata, tabs, and links.
- [x] Test portfolio detail returns 404 for missing portfolio.
- [x] Test portfolio summary uses `FrontEndDetailSummary` and string `uid` as
  `entity.id`.
- [x] Test latest weights returns one populated snapshot.
- [x] Test exact-date weights returns the requested `weights_date` snapshot.
- [x] Test latest weights returns empty snapshot when no rows exist.
- [x] Test exact-date weights returns empty snapshot when no rows exist for the
  requested timestamp.
- [x] Test latest weights asset details use `AssetSnapshotsStorage` name and
  ticker.
- [x] Test single delete returns success.
- [x] Test single delete returns 404 for missing portfolio.
- [x] Test single delete returns 409 for protected portfolio references.
- [x] Test bulk delete reports deleted and failed UIDs.
- [x] Extend `tests/msm/fastapi/v1/test_openapi.py` for portfolio route paths,
  operation IDs, tags, and response schemas.

### Documentation

- [x] Add portfolio route documentation under `docs/fast_api/v1/`.
- [x] Update `docs/fast_api/v1/index.md` route inventory.
- [x] Document that portfolio routes do not create portfolios.
- [x] Document latest weights resolution through
  `Portfolio.unique_identifier -> PortfolioWeightsStorage.portfolio_identifier`.
- [x] Document exact-date portfolio weights requests with `weights_date`.
- [x] Document that missing latest weights return 200 with an empty `weights`
  array.
- [x] Document delete conflict behavior for portfolios referenced by account
  target positions.

### Validation

- [x] Run `uv run --extra dev python -m pytest tests/msm/fastapi/v1/test_portfolios.py tests/msm/fastapi/v1/test_openapi.py`.
- [x] Run `uv run --extra dev python -m pytest tests/msm/fastapi/v1/test_runtime_bootstrap.py`.
- [x] Run `uv run --extra dev python -m ruff check apps/v1 src/msm src/msm_portfolios tests/msm/fastapi/v1`.
- [x] Run `git diff --check`.
- [x] If `docs/fast_api/v1/` changes, run
  `uv run --extra dev mkdocs build --strict --site-dir /private/tmp/msmarkets-docs-site`.

## Open Questions For Implementation

- Should single delete optionally delete matching `PortfolioMetadataTable` by
  `unique_identifier`, or should metadata deletion stay a separate explicit
  route?
- Should the latest weights endpoint paginate weight rows for very large
  portfolios, or should the first version mirror account snapshots and return
  all rows in the latest snapshot?
- Should a future portfolio value/performance tab use `PortfoliosStorage`, or
  remain out of this route until requested?
