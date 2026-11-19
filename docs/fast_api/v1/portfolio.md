# Portfolio Routes

The `apps/v1` portfolio routes expose portfolio identity rows, detail-page
composition, latest portfolio weights, the accounts whose current target names
a portfolio, retirement, and delete operations.

The routes do not create or update portfolios. Portfolio construction remains a
library workflow outside this API surface: an application publishes a
portfolio's weights and values through the series row operations
([Row Operations](rows.md#published-series)). ADR 0047 adds the
multi-portfolio frames and the batch lookup described below.

!!! note "Pre-3.0 field names"
    Through ms-markets 3.x every response that carries a `*_table_update_uid` portfolio pointer also
    repeats it under its pre-3.0 `*_data_node_uid` name, which OpenAPI marks
    deprecated, and requests accept either name. ms-markets 4.0 removes the
    pre-3.0 names ([ADR 0048](../../ADR/0048-time-index-vocabulary-rename.md)).

## Runtime Sources

- Portfolio identity uses `msm.api.portfolios.Portfolio`.
- Optional descriptive metadata uses
  `msm_portfolios.api.portfolios.PortfolioMetadata`.
- Latest weights use
  `msm_portfolios.time_index.portfolios.storage.PortfolioWeightsStorage`.
- Weight row asset labels use `AssetSnapshotsStorage`; OpenFIGI is not used for
  portfolio weight labels.
- Signal weights resolve from nullable `Portfolio.signal_uid`, which points to
  `SignalMetadataTable.signal_uid`. The API does not recompute signal identity
  from the TimeIndexTableUpdater build configuration or by scanning shared signal storage.
- Values, weights and signal-weight reads read Markets' own `PortfoliosTS`,
  `PortfolioWeightsTS` and `SignalWeightsTS` tables, whichever application
  published the rows. Markets reads no other application's table (ADR 0060, see
  the
  [portfolios knowledge page](../../knowledge/msm_portfolios/portfolios/index.md#published-series)).

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
GET /api/v1/portfolio/?search=&calendar_uid=&include_retired=false&limit=50&offset=0
```

Portfolio rows always include a non-null `calendar_uid` that references a
persisted `CalendarTable` row. Retired portfolios are left out unless
`include_retired=true`; every row carries `retired_at`, null while the
portfolio is live (see [Retire Portfolio](#retire-portfolio)).

Returns `command-center.resource_collection@v1` and exposes
`GET /api/v1/portfolio/discovery/`:

```json
{
  "items": [
    {
      "uid": "portfolio-uid",
      "unique_identifier": "example-sleeve",
      "calendar_uid": "00000000-0000-0000-0000-000000000001",
      "published_index_uid": "index-uid",
      "portfolio_weights_table_update_uid": null,
      "signal_weights_table_update_uid": null,
      "signal_uid": null,
      "portfolio_table_update_uid": null,
      "backtest_table_price_column_name": "close",
      "retired_at": null
    }
  ],
  "pageInfo": {
    "pageIndex": 0,
    "pageSize": 50,
    "totalItems": 1,
    "hasNextPage": false,
    "hasPreviousPage": false
  }
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
    "portfolio_weights_table_update_uid": null,
    "signal_weights_table_update_uid": null,
    "signal_uid": null,
    "portfolio_table_update_uid": null,
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
      "key": "portfolio_weights_table_update_uid",
      "label": "Portfolio Weights Node",
      "value": "weights-node-uid",
      "kind": "code",
      "icon": null,
      "link_url": "/api/v1/portfolio/portfolio-uid/weights/?order=desc&limit=1&include_asset_detail=true"
    },
    {
      "key": "signal_weights_table_update_uid",
      "label": "Signal Weights Node",
      "value": "signal-node-uid",
      "kind": "code",
      "icon": null,
      "link_url": "/api/v1/portfolio/portfolio-uid/signals_weights/?order=desc&limit=100"
    },
    {
      "key": "portfolio_table_update_uid",
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
      "rules_url": "/api/v1/calendar/calendar-uid/rules/",
      "exceptions_url": "/api/v1/calendar/calendar-uid/exceptions/"
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
      "portfolio_weights_table_update_uid": "weights-node-uid",
      "signal_weights_table_update_uid": "signal-node-uid",
      "signal_uid": "canonical-signal-uid",
      "portfolio_table_update_uid": "values-node-uid"
    }
  }
}
```

`signal_uid` is nullable for portfolios created before a signal workflow has run.
When present, it is the canonical `SignalMetadataTable.signal_uid` used by
`GET /api/v1/portfolio/{uid}/signals_weights/`. The signal-weights endpoint
does not infer the signal by scanning shared signal-weight storage.

## Batch Lookup By Uid

```text
GET /api/v1/portfolio/by-uids/?uid__in=<uid>&uid__in=<uid>
```

Returns the matching `Portfolio` rows in request order inside a
`ResourceCollection`. `uid__in` is repeated or comma-separated, at most 500;
unknown uids are omitted. A bounded lookup, not a browsable collection: no
`limit`, `offset`, search or discovery route. A row carries `managed_by`, the
principal that publishes to the portfolio's series. Data an application keeps
about a portfolio is read from that application.

## Values Frame For Several Portfolios

```text
GET /api/v1/portfolio/values/?portfolio_uid__in=<uid>&portfolio_uid__in=<uid>&start_date=&end_date=&order=desc&limit=500&offset=0
```

Returns one `core.tabular_frame@v1` with columns `time_index`,
`portfolio_identifier`, `portfolio_uid`, `close`, `return`, `calculated_close`
and `close_time` for every requested portfolio, read from Markets' own
`PortfoliosTS` table, so comparing portfolios published by two different
applications is one call. `order` sorts by
`time_index` across all portfolios and `limit` (1 to 5000) bounds the merged
result; `offset` skips that many rows of the merged order, so a longer window
is read in pages (`MarketsClient.portfolio_values` pages for a larger
`limit`). Every uid must be a portfolio (`404` otherwise); `source.context`
names the requested uids and the window.

## Weights Frame For Several Portfolios

```text
GET /api/v1/portfolio/weights/?portfolio_uid__in=<uid>&weights_date=&as_of=true
```

Returns one `core.tabular_frame@v1` with one weight snapshot per portfolio:
the latest snapshot, the latest at or before `weights_date` with `as_of=true`,
or the exact `weights_date` snapshot with `as_of=false`. Columns are
`time_index`, `portfolio_identifier`, `portfolio_uid`, `asset_identifier`,
`weight`, `weight_before`, `price_current`, `price_before`, `volume_current`
and `volume_before`, read from Markets' own `PortfolioWeightsTS` table.

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

## Accounts Whose Current Target Names The Portfolio

```text
GET /api/v1/portfolio/{uid}/account-targets/?limit=100&offset=0
```

`listPortfolioAccountTargets` pages the accounts whose current target has a
portfolio row for this portfolio, ordered by account uid. The current target is
the snapshot `GET /api/v1/account/{account_uid}/target-positions/` reads: the
latest `PositionSet` across the account's active target allocations. An account
that named the portfolio only in an earlier snapshot, or whose target was
cleared, is not listed. The read is one query that starts from the
`TargetPositionsStorage.portfolio_uid` index.

Returns `command-center.resource_collection@v1` and exposes
`GET /api/v1/portfolio/{uid}/account-targets/discovery/`; an unknown portfolio
is a `404`:

```json
{
  "items": [
    {
      "account_uid": "account-uid",
      "account_target_allocation_uid": "allocation-uid",
      "position_set_uid": "position-set-uid",
      "target_positions_date": "2026-11-09T15:00:00Z",
      "weight_notional_exposure": null,
      "constant_notional_exposure": "250000"
    }
  ],
  "pageInfo": {"pageIndex": 0, "pageSize": 100, "totalItems": 1, "hasNextPage": false, "hasPreviousPage": false}
}
```

The exposure is the portfolio row's `weight_notional_exposure` or
`constant_notional_exposure`; portfolio rows never use `single_asset_quantity`.
`position_set_uid` identifies the snapshot read, so a caller that rewrites the
account's target afterwards can tell whether it changed in between. The route
returns the same accounts as the other account routes: per-account scoping
waits for the ownership policies of
[ADR 0047](../../ADR/0047-markets-api-application-boundary.md).
`MarketsClient.portfolio_account_targets(...)` calls it.

## Retire Portfolio

```text
POST /api/v1/portfolio/{uid}/retire/
POST /api/v1/portfolio/{uid}/reinstate/
```

A portfolio that should no longer be used is retired, not deleted
([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md)).
`retirePortfolio` sets `retired_at` to the time of the request and returns the
portfolio. Nothing is deleted: account target snapshots, virtual funds and their
holdings, and the portfolio's weights and values stay, and reads of them still
resolve the portfolio.

- The route answers `409` while any account's current target names the
  portfolio; the account-targets read above lists those accounts. The update
  checks this in the same statement, and a second read afterwards undoes the
  retirement if a target write that named the portfolio committed meanwhile.
- Retiring a retired portfolio returns it unchanged.
- While retired, no target snapshot may name the portfolio, whatever its date
  (`409` from `add-target-positions`); applying a virtual-fund allocation for a
  snapshot at or after `retired_at` is refused (`409`); the portfolio list and
  the target-candidate search leave it out unless `include_retired=true`; and
  the portfolio updaters write nothing dated at or after `retired_at`.

`reinstatePortfolio` clears `retired_at`. Target snapshots may name the
portfolio again, and the updaters fill the retired period on their next run.
Both routes are registry writes, and their acting-identity records are the only
record of when a portfolio was retired. `MarketsClient.retire_portfolio(...)`
and `reinstate_portfolio(...)` call them.

## Delete Portfolio

```text
DELETE /api/v1/portfolio/{uid}/
```

Deletes the portfolio with its rows in its seven Markets datasets, in one
MetaTables transaction
([ADR 0049](../../ADR/0049-portfolio-lifecycle-and-account-history.md),
[issue 93](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/93)).
This route and [Bulk Delete Portfolios](#bulk-delete-portfolios) are the only
portfolio deletes: `Portfolio.delete` raises `MarketsOperationUnsupported`
under both backends, and `POST /api/v1/rows/portfolio/delete/` answers `501`.
`MarketsClient.delete_portfolio(...)` and `bulk_delete_portfolios(...)` call the
two routes.
Each dataset references `Portfolio.unique_identifier` with `RESTRICT`:

| `deleted_rows` key | Storage | Contract |
|---|---|---|
| `weights` | `PortfolioWeightsStorage` | `PortfolioWeightsTS` |
| `values` | `PortfoliosStorage` | `PortfoliosTS` |
| `rebalance_state` | `PortfolioRebalanceStateStorage` | `PortfolioRebalanceStateTS` |
| `analytics` | `PortfolioAnalyticsStorage` | `PortfolioAnalyticsTS` |
| `event_ledger` | `PortfolioEventLedgerStorage` | `PortfolioEventLedgerTS` |
| `state` | `PortfolioStateStorage` | `PortfolioStateTS` |
| `cash_flows` | `PortfolioCashFlowsStorage` | `PortfolioCashFlowsTS` |

The statements delete the portfolio's rows in each dataset and then the
portfolio row, in that order. The last one deletes the row only while it still
has the `unique_identifier` read before and no virtual fund or account target
row names it. If any statement fails, nothing is deleted. The portfolio's
group memberships go with the row through their own `CASCADE` key.
`PortfolioMetadataTable` rows are not deleted.

Each dataset table has an index that leads with `portfolio_identifier`
(Alembic revision 0026 for the weights, 0031 for the six others), so the delete's
statements, the read that counts its rows and the portfolio row's `RESTRICT`
checks read the portfolio's own rows, not the whole tables
([issue 96](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/96)).

Returns:

```json
{
  "detail": "Portfolio 'example-sleeve' deleted with its datasets.",
  "uid": "portfolio-uid",
  "unique_identifier": "example-sleeve",
  "deleted_count": 1,
  "deleted_rows": {
    "weights": 4,
    "values": 4,
    "rebalance_state": 2,
    "analytics": 0,
    "event_ledger": 6,
    "state": 3,
    "cash_flows": 1
  }
}
```

`deleted_rows` counts the portfolio's rows in each dataset just before the
delete ran.

Before it sends anything, the route checks what would refuse the delete and
deletes nothing when:

- **the caller does not manage the portfolio:** only the principal in
  `Portfolio.managed_by` deletes it, and nobody does while it has no manager.
  The route answers `403`
  ([ADR 0060](../../ADR/0060-producers-publish-markets-reads-only-its-own-tables.md)).
- **account history names the portfolio:** virtual funds
  (`VirtualFundTable.target_portfolio_uid`) or account target rows
  (`TargetPositionsStorage.portfolio_uid`). The route answers `409` and names
  the table and key. No route removes that history: retire the portfolio
  instead ([Retire Portfolio](#retire-portfolio)).

Markets reads and deletes only its own tables. An application's own table whose
`RESTRICT` key references the portfolio is neither discovered nor counted: the
database applies the key when the statements run, and a key that refuses
answers `409` with the database's message, which on PostgreSQL names the
constraint. Nothing is deleted. The application deletes its own rows first
(`msm_portfolios.recipes.delete_private_series`). A portfolio that no longer
exists when the delete runs answers `404`; one renamed in between answers
`409`.

The statements are plain deletes. After the statement list commits, MetaTables
rebuilds the update statistics it stores for each time-index table the list
changed, so the deleted portfolio's progress goes with its rows
([MetaTables#117](https://github.com/mainsequence-projects/MetaTables/issues/117),
`mainsequence-metatable` 0.1.69 and later; ms-markets requires 0.1.71). The account
delete relies on the same.

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

Only the portfolio's manager may delete its weights; any other caller gets
`403` and nothing is deleted.

## Bulk Delete Portfolios

```text
POST /api/v1/portfolio/bulk-delete/preflight/
POST /api/v1/portfolio/bulk-delete/
```

Both take the Command Center bulk-action request with explicit uids:

```json
{
  "selection": {"mode": "explicit", "uids": ["portfolio-uid-1", "portfolio-uid-2"]},
  "options": {}
}
```

The preflight runs the delete's checks without deleting: one read counts every
selected portfolio's rows per dataset and the account history that names it,
and reads its manager; a portfolio the caller does not manage is a blocker.
Each count reads only that portfolio's
rows, through its dataset's index on `(portfolio_identifier, time_index)`
([issue 96](https://github.com/mainsequence-projects/MainSequenceMarkets/issues/96)).
It returns the MetaTables impact, the blockers, and per portfolio the rows the
delete removes:

```json
{
  "allowed": false,
  "detail": "The portfolio selection cannot be deleted as submitted.",
  "matched_count": 2,
  "blockers": [
    "Portfolio 'protected-sleeve': 1 virtual fund target it (VirtualFundTable.target_portfolio_uid, ON DELETE RESTRICT)."
  ],
  "warnings": [
    "Account history is kept for as long as the account exists (ADR 0049); retire the portfolio instead."
  ],
  "impact": null,
  "portfolios": [
    {
      "uid": "portfolio-uid-1",
      "unique_identifier": "example-sleeve",
      "row_counts": {"weights": 4, "values": 4, "rebalance_state": 0, "analytics": 0, "event_ledger": 0, "state": 0, "cash_flows": 0},
      "blockers": []
    },
    {
      "uid": "portfolio-uid-2",
      "unique_identifier": "protected-sleeve",
      "row_counts": {"weights": 2, "values": 2, "rebalance_state": 0, "analytics": 0, "event_ledger": 0, "state": 0, "cash_flows": 0},
      "blockers": ["1 virtual fund target it (VirtualFundTable.target_portfolio_uid, ON DELETE RESTRICT)."]
    }
  ]
}
```

The bulk delete runs the preflight and answers `409` when it reports a blocker.
Otherwise it deletes each portfolio as `DELETE /api/v1/portfolio/{uid}/` does,
each in its own transaction, with the preflight's checks: the request counts the
selection once, and each portfolio's `deleted_rows` are its preflight
`row_counts`. It returns every deleted portfolio:

```json
{
  "detail": "Deleted 1 portfolio with its datasets.",
  "deleted_count": 1,
  "deleted": [
    {
      "detail": "Portfolio 'example-sleeve' deleted with its datasets.",
      "uid": "portfolio-uid-1",
      "unique_identifier": "example-sleeve",
      "deleted_count": 1,
      "deleted_rows": {"weights": 4, "values": 4, "rebalance_state": 0, "analytics": 0, "event_ledger": 0, "state": 0, "cash_flows": 0}
    }
  ],
  "failed": []
}
```

A portfolio refused after the preflight, for example by a reference written in
between, is listed in `failed` with its `detail`, and the route answers `409`
naming it. The other portfolios are still deleted.
