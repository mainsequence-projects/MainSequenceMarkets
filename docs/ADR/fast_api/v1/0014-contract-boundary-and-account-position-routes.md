# 0014. API v1 Contract Boundary And Account Position Routes

## Status

Proposed

## Context

`apps/v1` is adding account position endpoints for holdings and target
positions:

- `GET /api/v1/account/{account_uid}/holdings/`
- `GET /api/v1/account/{account_uid}/target-positions/`

Before adding those routes, the API boundary must be explicit. The repository
already has first-class typed library contracts under `src/msm/api`, and the
FastAPI app already has presentation-oriented Pydantic contracts under
`apps/v1/schemas`.

Those two contract layers are not the same thing:

- `src/msm/api` is the library API. It represents reusable markets concepts,
  typed row APIs, and create/update payloads that should be valid outside
  FastAPI.
- `apps/v1/schemas` is the HTTP presentation layer. It represents frontend list
  rows, wrapper responses, detail cards, compatibility payloads, and other
  response shapes that exist because this FastAPI surface needs them.

The account position routes need both layers. They must be backed by existing
library objects and storage contracts, but their response shapes are frontend
snapshot contracts. Those response shapes do not belong in `src/msm/api` unless
the same contract is needed as a first-class library API outside this FastAPI
surface.

## Decision

FastAPI-specific contracts remain in `apps/v1/schemas`.

Do not move presentation contracts into `src/msm/api`.

Do not create new `src/msm/api` models just to satisfy the FastAPI OpenAPI
schema. `src/msm/api` may only be extended when the project needs a true
library-level contract independent of `apps/v1`.

For list and detail endpoints over a single core library resource, `apps/v1`
should prefer the existing `src/msm/api` model even when that breaks an earlier
frontend projection contract. The API should not create or preserve a local
projection only to rename fields, hide fields, or keep a legacy table shape.

Local FastAPI schemas are still allowed, but only for HTTP-specific wrappers,
frontend-only UI contracts, multi-resource composed views, action payloads, and
compatibility envelopes that cannot be represented by a single `src/msm/api`
model.

When a local FastAPI response model is still needed, its implementation must
clearly derive from existing `src/msm/api` rows, storage declarations, or
reusable services.

### Current Contract Boundary

Under the core-first assumption, the boundary is:

| Route or contract | Preferred response model | Local schema allowed? | Reason |
| --- | --- | --- | --- |
| `GET /api/v1/account/` | `AccountListResponse` with `results: msm.api.accounts.Account[]` | Yes, wrapper only | `{ count, results }` is HTTP pagination/list metadata, but each row is the core `Account`. |
| `GET /api/v1/account/{uid}/` if added | `msm.api.accounts.Account` | No | Direct detail should return the library account row. |
| `GET /api/v1/account/{uid}/summary/` | `FrontEndDetailSummary` | Yes | This is a UI summary card, not an account row. |
| `GET /api/v1/asset/` | `msm.api.assets.Asset[]` | Only for wrapper/envelope | The legacy enriched `AssetListRow` projection is removed from this route under core-first rules. |
| `GET /api/v1/asset/{uid}/` if added | `msm.api.assets.Asset` | No | Direct detail should return the library asset row. |
| `GET /api/v1/asset/{uid}/summary/` | `FrontEndDetailSummary` | Yes | This is a UI summary card. |
| `GET /api/v1/asset/{uid}/get_pricing_details/` | `msm_pricing.api.AssetCurrentPricingDetails` | Adapter only if required by FastAPI serialization | Pricing already has a first-class API contract. |
| `GET /api/v1/asset-category/` | Prefer `msm.api.assets.AssetCategory[]` or wrapper with `results: AssetCategory[]` | Wrapper only | `number_of_assets`, actions, and nested-list metadata are presentation enrichments; plain list rows should prefer the core category row. |
| `GET /api/v1/asset-category/{uid}/` | Prefer `msm.api.assets.AssetCategory` | Only if explicitly returning a UI detail payload | Direct detail should not be a composed `selected_category/details/actions/assets_list` payload unless the route is explicitly a frontend detail route. |
| `POST /api/v1/asset-category/` | `msm.api.assets.AssetCategory` | Request wrapper allowed | The request may include membership replacement, but the created category response should prefer the core category row. |
| `PATCH /api/v1/asset-category/{uid}/` | `msm.api.assets.AssetCategory` | Request wrapper allowed | The request may include membership replacement, but the updated category response should prefer the core category row. |
| `POST /api/v1/asset-category/bulk-delete/` | `BulkDeleteAssetCategoriesResponse` | Yes | Bulk actions are not represented by one core row. |
| `GET /api/v1/index/` | `msm.api.indices.Index[]` | Wrapper only if pagination metadata is required | The legacy `IndexListRow` projection is removed under core-first rules. |
| `GET /api/v1/index/{uid}/` | `msm.api.indices.Index` | No | Direct detail should return the library index row. |
| `DELETE /api/v1/index/{uid}/` | deleted `msm.api.indices.Index` row or `null` | Yes, route decision | Delete responses are action semantics, not pure row lookup. |
| `Catalog*` | `apps/v1/schemas/catalog.py` | Yes | Catalogue maintenance has no `src/msm/api` equivalent. |
| `ErrorResponse` | `apps/v1/schemas/common.py` | Yes | FastAPI error envelope. |

This means the migration priority changes: first remove list/detail projections
that merely hide, rename, or subset core fields; then keep only wrappers and
true composed UI responses.

### Holdings Route Contract Analysis

`GET /api/v1/account/{account_uid}/holdings/` supports:

- latest snapshot:
  `?order=desc&limit=1&include_asset_detail=true`
- exact date snapshot:
  `?holdings_date=<iso>&limit=1&include_asset_detail=true`

The response contract belongs in `apps/v1/schemas/accounts.py` because it is a
FastAPI/frontend snapshot shape, not a first-class `src/msm/api` row model.

Source-backed fields:

- `related_account_uid`
- `holdings_date`, from `AccountHoldingsStorage.time_index`
- `holdings_set_uid`
- `is_trade_snapshot`
- `target_trade_time`
- `unique_identifier`
- `quantity`
- `extra_details`
- enriched asset object when `include_asset_detail=true`:
  - `asset.uid`
  - `asset.figi`
  - `asset.current_snapshot.name`
  - `asset.current_snapshot.ticker`

Fields not source-backed by the current holdings storage contract:

- numeric `id`
- numeric `asset_id`
- real `snapshot_uid`
- `price`
- `nav`
- `related_expected_asset_exposure_df`
- exact decimal precision strings, because holdings storage uses `Float`

Compatibility fields that are not source-backed must be nullable or omitted
according to the final frontend contract. The API must not fabricate numeric IDs
or prices.

If there is no holdings data, the route returns `200` with an empty snapshot:

```json
{
  "id": null,
  "snapshot_uid": null,
  "holdings_set_uid": null,
  "holdings_date": null,
  "nav": null,
  "related_account_uid": null,
  "is_trade_snapshot": false,
  "target_trade_time": null,
  "related_expected_asset_exposure_df": [],
  "holdings": []
}
```

### Target Positions Route Contract Analysis

`GET /api/v1/account/{account_uid}/target-positions/` supports:

- latest snapshot:
  `?order=desc&limit=1&include_asset_detail=true`
- exact date snapshot:
  `?target_positions_date=<iso>&limit=1&include_asset_detail=true`

The response contract belongs in `apps/v1/schemas/accounts.py` because it is a
FastAPI/frontend snapshot shape, not a first-class `src/msm/api` row model.

Source-backed fields:

- `related_account_uid`
- `target_positions_date`, from `PositionSet.position_set_time`
- `position_set_uid`, from `TargetPositionsStorage.position_set_uid` pointing to
  `PositionSet.uid`
- `unique_identifier`
- exactly one of:
  - `weight_notional_exposure`
  - `constant_notional_exposure`
  - `single_asset_quantity`
- enriched asset object when `include_asset_detail=true`:
  - `asset.uid`
  - `asset.figi`
  - `asset.current_snapshot.name`
  - `asset.current_snapshot.ticker`

Fields not source-backed:

- numeric asset `id`
- price or NAV fields
- exact decimal precision strings, because target-position storage uses `Float`

If there is no target-position data, the route returns `200` with an empty
snapshot:

```json
{
  "related_account_uid": "account-uid",
  "target_positions_date": null,
  "position_set_uid": null,
  "positions": []
}
```

## Implementation Plan

- [ ] Keep existing FastAPI presentation models in `apps/v1/schemas`.
- [ ] Do not move `FrontEndDetailSummary*` into `src/msm/api`.
- [ ] Do not move list wrappers or frontend detail contracts into
      `src/msm/api`.
- [ ] Remove local list/detail projections for account, asset, asset category,
      and index routes when a single core `src/msm/api` model can represent the
      response.
- [ ] Keep local schemas only for wrappers, UI summaries, composed views, action
      payloads, and compatibility envelopes.
- [ ] Prefer direct use of `msm_pricing.api.AssetCurrentPricingDetails` for the
      asset pricing details route; keep a local adapter only if FastAPI cannot
      serialize that external Pydantic model directly.
- [ ] Add holdings and target-position response models under
      `apps/v1/schemas/accounts.py`.
- [ ] Add reusable account position resolver logic under `src/msm/services`,
      using existing account, assignment, storage, asset, and OpenFIGI contracts.
- [ ] Add thin route handlers under `apps/v1/routers/accounts.py`.
- [ ] Return `200` empty snapshots when position data is absent.
- [ ] Add focused tests under `tests/msm/fastapi/v1/`.
- [ ] Verify `/openapi.json` documents the new contracts and routes.

## Open Questions

- Whether non-empty holdings should expose `snapshot_uid` as `null` or as an
  explicit alias of `holdings_set_uid`.
- Whether compatibility fields such as `price`, `nav`, and `missing_price`
  should be present as nullable values or excluded until source-backed data
  exists.
- Whether `limit > 1` should be rejected initially or should return a
  `{ "results": [...] }` wrapper. The current frontend request shape asks for
  `limit=1`, and a single snapshot object is the cleanest first contract.
- Whether `include_asset_detail=false` should return `asset: null`, omit the
  asset field, or return only `asset.uid`.

## Consequences

This decision keeps the FastAPI surface honest: route responses can be tailored
for the frontend, but they must remain backed by real library objects and
storage contracts.

It also prevents `src/msm/api` from becoming polluted with route-specific
presentation models. Future API v1 work should repeat this distinction before
adding or moving any contract.
