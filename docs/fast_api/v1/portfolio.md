# Portfolio Routes

The `apps/v1` portfolio routes expose portfolio identity rows, detail-page
composition, latest portfolio weights, and delete operations.

The routes do not create or update portfolios. Portfolio construction remains a
library workflow outside this API surface.

## Runtime Sources

- Portfolio identity uses `msm.api.portfolios.Portfolio`.
- Optional descriptive metadata uses
  `msm_portfolios.api.portfolios.PortfolioMetadata`.
- Latest weights use
  `msm_portfolios.data_nodes.portfolios.storage.PortfolioWeightsStorage`.
- Weight row asset labels use `AssetSnapshotsStorage`; OpenFIGI is not used for
  portfolio weight labels.
- Signal weights resolve from the runtime update state of
  `Portfolio.signal_weights_data_node_uid`. The API does not recompute signal
  identity from the DataNode build configuration.

Latest weights resolve through:

```text
Portfolio.uid
  -> Portfolio.unique_identifier
  -> PortfolioWeightsStorage.portfolio_identifier
```

The optional `published_index_uid` field is not used for latest-weight
resolution. It is publication metadata only.

## List Portfolios

```text
GET /api/v1/portfolio/?response_format=frontend_list&search=&calendar_uid=&limit=50&offset=0
```

Portfolio rows always include a non-null `calendar_uid` that references a
persisted `CalendarTable` row.

Returns `PaginatedResponse[Portfolio]`:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "portfolio-uid",
      "unique_identifier": "example-sleeve",
      "calendar_uid": "00000000-0000-0000-0000-000000000001",
      "published_index_uid": "index-uid",
      "portfolio_weights_data_node_uid": null,
      "signal_weights_data_node_uid": null,
      "portfolio_data_node_uid": null,
      "backtest_table_price_column_name": "close"
    }
  ]
}
```

## Portfolio Detail

```text
GET /api/v1/portfolio/{uid}/
```

Returns the core portfolio row, optional metadata, detail-page tabs, and route
links:

```json
{
  "portfolio": {
    "uid": "portfolio-uid",
    "unique_identifier": "example-sleeve",
    "calendar_uid": "00000000-0000-0000-0000-000000000001",
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

Missing metadata does not make the detail route return 404. Only a missing
portfolio row returns 404.

## Portfolio Summary

```text
GET /api/v1/portfolio/{uid}/summary/
```

Returns the shared `FrontEndDetailSummary` contract. The summary `entity.id`
is the portfolio `uid` string.

The summary includes the PortfolioTable pointer fields as inline code fields
and as a structured `extensions.pointers` object:

```json
{
  "extensions": {
    "pointers": {
      "portfolio_weights_data_node_uid": "weights-node-uid",
      "signal_weights_data_node_uid": "signal-node-uid",
      "portfolio_data_node_uid": "values-node-uid"
    }
  }
}
```

## Latest Portfolio Weights

```text
GET /api/v1/portfolio/{uid}/weights/?order=desc&limit=1&include_asset_detail=true
```

Returns one `PortfolioWeightsSnapshotResponse`:

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

## Portfolio Weights By Date

```text
GET /api/v1/portfolio/{uid}/weights/?weights_date=2026-06-07T10:30:00Z&include_asset_detail=true
```

`weights_date` selects the exact `PortfolioWeightsStorage.time_index`
snapshot and takes precedence over `order`.

If the portfolio exists but no rows exist for the requested timestamp, the
response is 200 with an empty `weights` list:

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

## Delete Portfolio

```text
DELETE /api/v1/portfolio/{uid}/
```

Deletes the portfolio identity row and historical
`PortfolioWeightsStorage` rows resolved through:

```text
Portfolio.uid
  -> Portfolio.unique_identifier
  -> PortfolioWeightsStorage.portfolio_identifier
```

Returns:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1,
  "deleted_weights_count": 4
}
```

If protected rows, such as virtual funds or account target-position history,
reference the portfolio, the route returns 409 and does not delete the
portfolio.

The delete route does not delete `PortfoliosStorage` value history or metadata
rows.

## Delete Portfolio Weights

```text
DELETE /api/v1/portfolio/{uid}/weights/?weights_date=2026-06-07T10:30:00Z
```

Deletes only `PortfolioWeightsStorage` rows for the portfolio identifier. If
`weights_date` is omitted, all weight rows for that portfolio identifier are
deleted. If `weights_date` is provided, only the exact
timestamp is deleted.

Returns:

```json
{
  "detail": "Portfolio weights deleted.",
  "portfolio_uid": "portfolio-uid",
  "portfolio_identifier": "example-sleeve",
  "weights_date": "2026-06-07T10:30:00Z",
  "deleted_count": 4
}
```

Weight deletion itself is scoped by `Portfolio.unique_identifier`; protected
portfolio references only matter for deleting the portfolio identity row.

## Bulk Delete Portfolios

```text
POST /api/v1/portfolio/bulk-delete/
```

Request:

```json
{
  "uids": ["portfolio-uid-1", "portfolio-uid-2"]
}
```

Response:

```json
{
  "detail": "Deleted 1 portfolio; 1 portfolio could not be deleted.",
  "deleted_count": 1,
  "deleted_weights_count": 4,
  "failed": [
    {
      "uid": "protected-portfolio-uid",
      "reason": "Portfolio is referenced by target positions."
    }
  ]
}
```
