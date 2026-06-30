# Assets

Route group for the asset registry and asset categories. Asset routes cover
identity lists, the Command Center monitor frame, detail and summary
composition, current pricing details, and identity delete. Asset category routes
cover category lists, detail composition, and membership-aware create, update,
and delete operations.

## Assets

- `GET /api/v1/asset/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, `offset`
  - supports `categories__uid` for nested category asset tables
  - returns the library `msm.api.assets.Asset` contract:
    `uid`, `unique_identifier`, and `asset_type`
- `GET /api/v1/asset/monitor/frame/`
  - supports `search`, `limit`, `offset`, optional `asset_type`, and repeated
    `unique_identifiers`
  - returns a Command Center `TabularFrameResponse`
  - exposes the `core.tabular_frame@v1` contract for
    `main-sequence-markets__asset-screener`
  - publishes `AssetTable.unique_identifier` as the ms-markets stable asset key
    without adding a synthetic `Symbol` column
- `GET /api/v1/asset/{uid}/`
  - supports `response_format=frontend_detail`
  - resolves the asset by `uid`
  - returns `AssetDetailResponse` with top-level `uid`, `unique_identifier`,
    `asset_type`, and `current_snapshot`
  - `current_snapshot` is the latest `AssetSnapshotsStorage` row for the
    asset `unique_identifier` / snapshot `asset_identifier`
  - does not use numeric asset IDs for asset identity
- `GET /api/v1/asset/{uid}/summary/`
  - returns a reusable `FrontEndDetailSummary` response for detail-page
    summary cards
  - resolves the asset by `uid`
  - includes asset identity, badges, inline fields, highlight fields, label
    management placeholders, and page-specific extensions
- `GET /api/v1/asset/{uid}/get_pricing_details/`
  - returns the current pricing details row for one asset
  - response mirrors `msm_pricing.api.AssetCurrentPricingDetails`
  - reads `AssetCurrentPricingDetailsTable`, not the timestamped
    `AssetPricingDetail` DataNode
  - returns 404 when no current pricing details row exists for the asset
- `DELETE /api/v1/asset/{uid}/`
  - deletes one asset identity row by `uid`
  - returns 200 with `null` on success
  - returns 404 when the asset `uid` does not exist
  - related rows are governed by backend table constraints

## Asset Categories

- `GET /api/v1/asset-category/`
  - supports `response_format=frontend_list`
  - returns the library `msm.api.assets.AssetCategory` contract
- `GET /api/v1/asset-category/{uid}/`
  - supports `response_format=frontend_detail`
  - returns `AssetCategoryDetailResponse` with category display fields,
    membership-backed `number_of_assets`, and an `assets_list` configuration
    whose default filter is `categories__uid=<category_uid>`
- `POST /api/v1/asset-category/`
  - creates a category
  - derives `unique_identifier` from `display_name` when omitted
  - replaces memberships when `assets` are supplied
  - returns the created library `msm.api.assets.AssetCategory` row
- `PATCH /api/v1/asset-category/{uid}/`
  - updates category metadata
  - replaces memberships when `assets` are supplied
  - returns the updated library `msm.api.assets.AssetCategory` row
- `DELETE /api/v1/asset-category/{uid}/`
  - deletes a single category
  - returns `null` on success
- `POST /api/v1/asset-category/bulk-delete/`
  - deletes by explicit `uids`
  - also supports compatibility filters with `select_all=true`

## Related Concepts

- [Assets knowledge](../../knowledge/msm/assets/index.md)
