# 0012. API v1 Asset Category Route Plan

## Status

Proposed

## Context

`apps/v1` currently exposes only `GET /api/v1/asset/`. The next API surface
needed by the client is the legacy asset-category workflow that used to live
under `/orm/api/assets/asset-category/...`.

The new `apps/v1` API must preserve the client-facing route semantics and
response shapes, but it must follow the `apps/v1` standards established for
this repository:

- `apps/v1` is a resolver layer only;
- reusable business logic belongs under `src/`;
- every endpoint must declare documented Pydantic contracts;
- the generated OpenAPI output must be usable as real API documentation.

The category detail view also depends on a nested assets table. In the new
surface that table should not become a separate nested route. It should remain
the asset list endpoint with a `categories__uid` filter.

## Decision

`apps/v1` will add the asset-category surface under `/api/v1/asset-category/`
and will extend `GET /api/v1/asset/` with category filtering.

### Route Mapping

| Legacy route | API v1 route | Purpose |
| --- | --- | --- |
| `GET /orm/api/assets/asset-category/?response_format=frontend_list&search=&limit=&offset=` | `GET /api/v1/asset-category/?response_format=frontend_list&search=&limit=&offset=` | List asset categories for the frontend table view. |
| `GET /orm/api/assets/asset-category/{uid}/?response_format=frontend_detail` | `GET /api/v1/asset-category/{uid}/?response_format=frontend_detail` | Return the category detail payload used by the detail screen. |
| `POST /orm/api/assets/asset-category/` | `POST /api/v1/asset-category/` | Create an asset category. |
| `PATCH /orm/api/assets/asset-category/{uid}/` | `PATCH /api/v1/asset-category/{uid}/` | Update category metadata and membership. |
| `DELETE /orm/api/assets/asset-category/{uid}/` | `DELETE /api/v1/asset-category/{uid}/` | Delete a single category. |
| `POST /orm/api/assets/asset-category/bulk-delete/` | `POST /api/v1/asset-category/bulk-delete/` | Delete multiple categories using explicit selection or compatibility filters. |
| `GET /orm/api/assets/asset/?response_format=frontend_list&categories__uid={uid}&limit=&offset=` | `GET /api/v1/asset/?response_format=frontend_list&categories__uid={uid}&limit=&offset=` | Nested assets table for a selected category, reusing the asset list contract. |

### Contract Plan

The asset-category rollout will add explicit FastAPI contracts under
`apps/v1/schemas/`:

- `AssetCategoryListRow`
  - `uid`
  - `unique_identifier`
  - `display_name`
  - `description`
  - `number_of_assets`
- `AssetCategoryRecord`
  - canonical create/update/delete response model
  - includes category identity and editable fields
  - membership projection must be normalized explicitly rather than returned as
    an untyped payload
- `AssetCategoryDetailResponse`
  - `selected_category`
  - `details`
  - `actions`
  - `assets_list`
- `CreateAssetCategoryRequest`
  - `display_name`
  - `description`
  - `unique_identifier`
  - `assets`
- `PatchAssetCategoryRequest`
  - `display_name`
  - `description`
  - `assets`
- `BulkDeleteAssetCategoriesRequest`
  - `uids`
  - `select_all`
  - `current_url`
  - compatibility search/filter fields needed to reproduce legacy bulk-delete
    behavior
- `BulkDeleteAssetCategoriesResponse`
  - `detail`
  - `deleted_count`

The nested assets table must continue to return `AssetListRow[]`.

### Implementation Boundary

The HTTP surface belongs under `apps/v1`, but reusable behavior must be moved
into `src/` before or during this rollout.

Planned boundary:

- `apps/v1/main.py`
  - app bootstrap and router registration only
- `apps/v1/routers/asset_categories.py`
  - route declarations and HTTP-level parameter handling
- `apps/v1/routers/assets.py`
  - extend existing asset list route with `categories__uid`
- `apps/v1/schemas/asset_categories.py`
  - request and response contracts for category endpoints
- `src/msm/...`
  - reusable category query, membership mutation, compatibility mapping, and
    asset filtering logic

The existing asset list implementation in `apps/v1/services/assets.py` should
be treated as transitional. Reusable asset query logic should be extracted into
`src/` instead of expanding route-side logic further.

### Compatibility Rules

- `GET /api/v1/asset-category/` must accept
  `response_format=frontend_list`.
- `GET /api/v1/asset-category/{uid}/` must accept
  `response_format=frontend_detail`.
- `GET /api/v1/asset/` must continue to support the current `frontend_list`
  shape while adding `categories__uid`.
- Unsupported `response_format` values should fail with clear `400` errors.
- Missing category records should fail explicitly unless legacy behavior proves
  that a nullable success response is required for a specific route.

## Implementation Plan

- [ ] Extract reusable asset query and category CRUD behavior into `src/`.
- [ ] Add `AssetCategoryListRow`, `AssetCategoryRecord`,
      `AssetCategoryDetailResponse`, create/patch request models, and bulk
      delete request/response models under `apps/v1/schemas/`.
- [ ] Add `apps/v1/routers/asset_categories.py` and register it in
      `apps/v1/main.py`.
- [ ] Extend `GET /api/v1/asset/` to support `categories__uid`.
- [ ] Add focused tests under `tests/msm/fastapi/v1/` for list, detail,
      create, patch, delete, bulk delete, and asset list category filtering.
- [ ] Verify `/openapi.json` documents every new route and contract.
- [ ] If written endpoint documentation is added beyond OpenAPI, place it under
      `docs/fast_api/v1/`.

## Open Questions

The following points should be confirmed against legacy behavior before final
implementation:

- whether `DELETE /api/v1/asset-category/{uid}/` should return a deleted record,
  `null`, or `404` when the target does not exist;
- the exact typed shape of `details[]` and `actions` in the detail response;
- whether `PATCH .../asset-category/{uid}/` treats `assets` as full membership
  replacement or as a partial mutation command;
- whether `number_of_assets` is a direct membership count or requires a
  distinct-asset aggregation;
- whether `current_url` in bulk delete is only compatibility metadata or must
  still drive server-side filter reconstruction.

## Consequences

This plan keeps the new public API close to the old frontend contract without
repeating the legacy package boundary. It also forces the asset-category work to
clean up the current `apps/v1` boundary by pushing reusable logic into `src/`
instead of growing more route-local implementation.

The rollout will increase the number of explicit contracts in `apps/v1`, but
that is the correct cost for making `/openapi.json` and the route behavior
usable by both humans and tooling.
