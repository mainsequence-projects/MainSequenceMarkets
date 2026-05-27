# FastAPI v1

The local `apps/v1` FastAPI app exposes the migrated public asset registry
surface for this repository.

## Scope

This API is intentionally thin:

- route declarations, validation, and OpenAPI metadata live under `apps/v1`
- reusable catalog and category workflows live under `src/msm/services`
- the current route composition is backed by
  `src/msm/services/asset_master_lists.py`

## Implemented Routes

### Assets

- `GET /api/v1/asset/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, `offset`
  - supports `categories__uid` for nested category asset tables
  - returns paginated asset rows in the migrated list contract

### Asset Categories

- `GET /api/v1/asset-category/`
  - supports `response_format=frontend_list`
  - returns the frontend rows wrapper with `search`, `rows`, and `pagination`
- `GET /api/v1/asset-category/{uid}/`
  - supports `response_format=frontend_detail`
  - returns `selected_category`, `details`, `actions`, and `assets_list`
- `POST /api/v1/asset-category/`
  - creates a category
  - derives `unique_identifier` from `display_name` when omitted
  - replaces memberships when `assets` are supplied
- `PATCH /api/v1/asset-category/{uid}/`
  - updates category metadata
  - replaces memberships when `assets` are supplied
- `DELETE /api/v1/asset-category/{uid}/`
  - deletes a single category
  - returns `null` on success
- `POST /api/v1/asset-category/bulk-delete/`
  - deletes by explicit `uids`
  - also supports compatibility filters with `select_all=true`

## Compatibility Notes

The category detail payload advertises:

- `list_endpoint: /api/v1/asset/`
- `query_endpoint: /api/v1/asset/query/`

The nested category detail page in the current Command Center client uses the
`GET /api/v1/asset/` path with `categories__uid`. The dedicated
`POST /api/v1/asset/query/` route is still future work for this local API.

## Validation

The focused FastAPI coverage for this surface lives under:

- `tests/msm/fastapi/v1/`

Use `/openapi.json`, `/docs`, and `/redoc` from the local app for contract
inspection.
