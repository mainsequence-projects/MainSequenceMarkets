# Indexes

Route group for the index registry. Covers index identity lists, single-record
reads, a non-destructive delete-impact preflight that reports blocking
dependencies, and index delete.

- `GET /api/v1/index/`
  - supports `response_format=frontend_list`
  - supports `search`, `limit`, and `offset`
  - returns the library `msm.api.indices.Index` contract
- `GET /api/v1/index/{uid}/`
  - returns one index registry record by `uid`
  - always includes `index_type` and includes `metadata_json` when present on
    the underlying row
- `GET /api/v1/index/{uid}/delete-impact/`
  - returns a non-destructive preflight summary for deleting one index
  - serializes through the shared `DeleteImpactResponse` contract from
    `apps/v1/schemas/delete_impact.py`
  - reports dependent row counts, delete effects, and whether the individual
    `DELETE /api/v1/index/{uid}/` route is currently blocked
  - treats `FutureAssetDetailsTable.underlying_index_uid`,
    `IndexFixingsStorage.index_identifier`, and
    `PricingMarketDataSetCurveBindingTable` index selectors as blocking
    dependencies when matching rows exist
  - reports non-blocking side effects for
    `PortfolioTable.published_index_uid` (`SET NULL`) and
    `IndexConventionDetailsTable.index_uid` (`CASCADE`)
- `DELETE /api/v1/index/{uid}/`
  - deletes one index registry record
  - should be preceded by `GET /api/v1/index/{uid}/delete-impact/` when called
    from interactive clients
  - returns `null` on success

## Related Concepts

- [Indices knowledge](../../knowledge/msm/indices/index.md)
