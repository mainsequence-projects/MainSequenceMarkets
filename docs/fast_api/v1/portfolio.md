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
- Signal weights resolve from nullable `Portfolio.signal_uid`, which points to
  `SignalMetadataTable.signal_uid`. The API does not recompute signal identity
  from the DataNode build configuration or by scanning shared signal storage.

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
      "signal_uid": null,
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
    "signal_uid": null,
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

The summary includes PortfolioTable pointer fields as inline code fields.
Summary badges, inline fields, highlight fields, and stats can carry a
nullable `link_url` field. The response does not use a separate summary
`links` array; frontend navigation belongs on the actual row being rendered.

```json
{
  "key": "calendar_uid",
  "label": "Calendar UID",
  "value": "calendar-uid",
  "kind": "code",
  "icon": null,
  "link_url": "/api/v1/calendar/calendar-uid/"
}
```

Portfolio summaries attach `link_url` to the calendar field, published-index
badge/field, portfolio-weights node field, signal-weights node field, and
portfolio-values node field when the backing UID exists. `extensions` keeps
page-specific resolved metadata for consumers that need more than a field URL.

```json
{
  "badges": [
    {
      "key": "published_index",
      "label": "Published Index",
      "tone": "info",
      "link_url": "/api/v1/index/index-uid/"
    }
  ],
  "inline_fields": [
    {
      "key": "calendar_uid",
      "label": "Calendar UID",
      "value": "calendar-uid",
      "kind": "code",
      "icon": null,
      "link_url": "/api/v1/calendar/calendar-uid/"
    },
    {
      "key": "portfolio_weights_data_node_uid",
      "label": "Portfolio Weights Node",
      "value": "weights-node-uid",
      "kind": "code",
      "icon": null,
      "link_url": "/api/v1/portfolio/portfolio-uid/weights/?order=desc&limit=1&include_asset_detail=true"
    },
    {
      "key": "signal_weights_data_node_uid",
      "label": "Signal Weights Node",
      "value": "signal-node-uid",
      "kind": "code",
      "icon": null,
      "link_url": "/api/v1/portfolio/portfolio-uid/signals_weights/?order=desc&limit=100"
    },
    {
      "key": "portfolio_data_node_uid",
      "label": "Portfolio Values Node",
      "value": "values-node-uid",
      "kind": "code",
      "icon": null,
      "link_url": "/api/v1/portfolio/portfolio-uid/portfolio_values/?order=desc&limit=100"
    }
  ],
  "highlight_fields": [
    {
      "key": "calendar",
      "label": "Calendar",
      "value": "Example Calendar",
      "kind": "text",
      "icon": "calendar",
      "link_url": "/api/v1/calendar/calendar-uid/"
    }
  ],
  "extensions": {
    "calendar": {
      "uid": "calendar-uid",
      "label": "Example Calendar",
      "display_name": "Example Calendar",
      "unique_identifier": "EXAMPLE_CALENDAR",
      "detail_url": "/api/v1/calendar/calendar-uid/",
      "dates_url": "/api/v1/calendar/calendar-uid/dates/",
      "sessions_url": "/api/v1/calendar/calendar-uid/sessions/",
      "events_url": "/api/v1/calendar/calendar-uid/events/"
    },
    "nodes": {
      "portfolio_weights": {
        "uid": "weights-node-uid",
        "label": "Portfolio weights",
        "url": "/api/v1/portfolio/portfolio-uid/weights/?order=desc&limit=1&include_asset_detail=true"
      },
      "signal_weights": {
        "uid": "signal-node-uid",
        "signal_uid": "canonical-signal-uid",
        "label": "Signal weights",
        "url": "/api/v1/portfolio/portfolio-uid/signals_weights/?order=desc&limit=100"
      },
      "portfolio_values": {
        "uid": "values-node-uid",
        "label": "Portfolio values",
        "url": "/api/v1/portfolio/portfolio-uid/portfolio_values/?order=desc&limit=100"
      }
    },
    "pointers": {
      "portfolio_weights_data_node_uid": "weights-node-uid",
      "signal_weights_data_node_uid": "signal-node-uid",
      "signal_uid": "canonical-signal-uid",
      "portfolio_data_node_uid": "values-node-uid"
    }
  }
}
```

`signal_uid` is nullable for portfolios created before a signal workflow has run.
When present, it is the canonical `SignalMetadataTable.signal_uid` used by
`GET /api/v1/portfolio/{uid}/signals_weights/`. The signal-weights endpoint
does not infer the signal by scanning shared signal-weight storage.

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

Deletes the portfolio identity row plus historical `PortfolioWeightsStorage`
and `PortfoliosStorage` rows resolved through:

```text
Portfolio.uid
  -> Portfolio.unique_identifier
  -> PortfolioWeightsStorage.portfolio_identifier
  -> PortfoliosStorage.portfolio_identifier
```

Returns:

```json
{
  "detail": "Portfolio deleted.",
  "deleted_count": 1,
  "deleted_weights_count": 4,
  "deleted_values_count": 4
}
```

If protected rows, such as virtual funds or account target-position history,
reference the portfolio, the route returns 409 and does not delete the
portfolio.

Storage cleanup uses each storage table's
`TimeIndexMetaTable.delete_after_date(None, dimension_filters=...)` API, scoped
by `Portfolio.unique_identifier`. The delete route does not delete
`PortfolioMetadataTable` rows.

## Delete Portfolio Weights

```text
DELETE /api/v1/portfolio/{uid}/weights/?weights_date=2026-06-07T10:30:00Z
```

Deletes `PortfolioWeightsStorage` rows for the portfolio identifier through the
storage table's `TimeIndexMetaTable.delete_after_date(...)` API. If
`weights_date` is omitted, all weight rows for that portfolio identifier are
deleted by calling `delete_after_date(None, dimension_filters=...)` with the
portfolio scope. If `weights_date` is provided, rows at or after that timestamp
are deleted.

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

Weight deletion itself is scoped by `Portfolio.unique_identifier`; the API never
calls `delete_after_date(None)` without that dimension scope. Protected
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
