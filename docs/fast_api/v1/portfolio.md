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

Latest weights resolve through:

```text
Portfolio.uid
  -> Portfolio.portfolio_index_uid
  -> Index.uid
  -> Index.unique_identifier
  -> PortfolioWeightsStorage.portfolio_index_identifier
```

If a portfolio has no `portfolio_index_uid`, the weights endpoint returns 200
with an empty `weights` list and a `resolution_warning`.

## List Portfolios

```text
GET /api/v1/portfolio/?response_format=frontend_list&search=&calendar_uid=&calendar_name=&limit=50&offset=0
```

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
      "calendar_name": "CRYPTO_24_7",
      "calendar_uid": null,
      "portfolio_index_uid": "index-uid",
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
    "calendar_name": "CRYPTO_24_7",
    "calendar_uid": null,
    "portfolio_index_uid": "index-uid",
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

## Latest Portfolio Weights

```text
GET /api/v1/portfolio/{uid}/weights/?order=desc&limit=1&include_asset_detail=true
```

Returns one `PortfolioWeightsSnapshotResponse`:

```json
{
  "portfolio_uid": "portfolio-uid",
  "portfolio_unique_identifier": "example-sleeve",
  "portfolio_index_uid": "index-uid",
  "portfolio_index_identifier": "example-sleeve-index",
  "weights_date": "2026-06-07T10:30:00Z",
  "resolution_warning": null,
  "weights": [
    {
      "time_index": "2026-06-07T10:30:00Z",
      "portfolio_index_identifier": "example-sleeve-index",
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
  "portfolio_index_uid": "index-uid",
  "portfolio_index_identifier": "example-sleeve-index",
  "weights_date": null,
  "resolution_warning": null,
  "weights": []
}
```

## Delete Portfolio

```text
DELETE /api/v1/portfolio/{uid}/
```

Returns:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1
}
```

If protected rows, such as account target-position history, reference the
portfolio, the route returns 409 and does not delete the portfolio.

The delete route does not delete historical `PortfolioWeightsStorage`,
`PortfoliosStorage`, or metadata rows.

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
  "failed": [
    {
      "uid": "protected-portfolio-uid",
      "reason": "Portfolio is referenced by target positions."
    }
  ]
}
```
