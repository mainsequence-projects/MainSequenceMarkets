# Command Center resource contracts

The FastAPI v1 resource surface is a strict consumer of
`@dev-mainsequence/command-center-sdk` `0.1.13`, pinned to Git commit
`f11c0ea8c5d3fc267997e476aa1522c798fdaced`. The package manifest, JSON Schemas,
and valid and invalid fixtures are the wire-contract authority.

## Collections

Every list route declares `command-center.resource_collection@v1` and returns
only canonical rows plus authoritative pagination:

```json
{
  "items": [],
  "pageInfo": {
    "pageIndex": 0,
    "pageSize": 25,
    "totalItems": 0,
    "hasNextPage": false,
    "hasPreviousPage": false
  }
}
```

`limit` is the requested `pageSize`; `offset` must be a non-negative multiple
of `limit`, and `pageIndex` is `offset / limit`. Counts are calculated from the
complete filtered query before the requested page is fetched. The API does not
publish the retired `count`/`next`/`previous`/`results` envelope or a
`response_format` selector.

## Discovery

Every collection has a sibling `GET {collection-path}/discovery/` route that
declares `command-center.resource_discovery@v1`. Discovery is authoritative for:

- ordered UI identity fields;
- search, filter, and ordering controls;
- ordered columns and safe generic value bindings; and
- authorized bulk actions.

Discovery accepts only semantic scope used by that collection. Presentation
state such as `limit`, `offset`, `page`, `page_size`, `ordering`, or `sort` is
rejected. Migrated clients must not call a separate `/bulk-actions/` endpoint
or inspect collection metadata as a fallback.

## Complete collection inventory

| Collection | Discovery |
| --- | --- |
| `/api/v1/account/` | `/api/v1/account/discovery/` |
| `/api/v1/account/target-allocation/targets/` | `/api/v1/account/target-allocation/targets/discovery/` |
| `/api/v1/asset/` | `/api/v1/asset/discovery/` |
| `/api/v1/asset/{uid}/related-meta-tables/` | `/api/v1/asset/{uid}/related-meta-tables/discovery/` |
| `/api/v1/asset-category/` | `/api/v1/asset-category/discovery/` |
| `/api/v1/calendar/` | `/api/v1/calendar/discovery/` |
| `/api/v1/calendar/{calendar_uid}/dates/` | `/api/v1/calendar/{calendar_uid}/dates/discovery/` |
| `/api/v1/calendar/{calendar_uid}/sessions/` | `/api/v1/calendar/{calendar_uid}/sessions/discovery/` |
| `/api/v1/calendar/{calendar_uid}/events/` | `/api/v1/calendar/{calendar_uid}/events/discovery/` |
| `/api/v1/index-type/` | `/api/v1/index-type/discovery/` |
| `/api/v1/index/` | `/api/v1/index/discovery/` |
| `/api/v1/index/{uid}/formulas/` | `/api/v1/index/{uid}/formulas/discovery/` |
| `/api/v1/index/{uid}/datasets/` | `/api/v1/index/{uid}/datasets/discovery/` |
| `/api/v1/index/{uid}/related-meta-tables/` | `/api/v1/index/{uid}/related-meta-tables/discovery/` |
| `/api/v1/portfolio-group/` | `/api/v1/portfolio-group/discovery/` |
| `/api/v1/portfolio-group/by-portfolio/{portfolio_uid}/` | `/api/v1/portfolio-group/by-portfolio/{portfolio_uid}/discovery/` |
| `/api/v1/portfolio-group/{uid}/portfolios/` | `/api/v1/portfolio-group/{uid}/portfolios/discovery/` |
| `/api/v1/portfolio-signal/` | `/api/v1/portfolio-signal/discovery/` |
| `/api/v1/portfolio/` | `/api/v1/portfolio/discovery/` |
| `/api/v1/virtualfund/` | `/api/v1/virtualfund/discovery/` |
| `/api/v1/pricing/curves/` | `/api/v1/pricing/curves/discovery/` |
| `/api/v1/pricing/curves/{uid}/curve-selections/` | `/api/v1/pricing/curves/{uid}/curve-selections/discovery/` |
| `/api/v1/pricing/market_data/sets/` | `/api/v1/pricing/market_data/sets/discovery/` |
| `/api/v1/pricing/market_data/bindings/` | `/api/v1/pricing/market_data/bindings/discovery/` |
| `/api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/` | `/api/v1/pricing/market_data/sets/{market_data_set_uid}/bindings/discovery/` |

## Detail, summary, and action boundaries

The SDK does not publish a generic detail or summary wire schema. Canonical row
detail endpoints therefore return the resource-specific Pydantic model, while
the existing `FrontEndDetailSummary` endpoints remain application-owned view
models. Accounts and pricing curves expose distinct row and summary operations:

- `getAccount` at `/api/v1/account/{uid}/` and `getAccountSummary` at
  `/api/v1/account/{uid}/summary/`;
- `getPricingCurve` at `/api/v1/pricing/curves/{uid}/` and
  `getPricingCurveSummary` at `/api/v1/pricing/curves/{uid}/summary/`.

Asset-category, portfolio, and virtual-fund detail endpoints retain their
resource-specific composed detail models because those models carry tabs and
relationship links in addition to a canonical row.

Bulk-action definitions for asset categories, portfolios, and portfolio groups
are embedded in their resource discovery responses. Preflight and execution
share `command-center.bulk_action_execution@v1`; preflight returns
`command-center.bulk_action_preflight@v1`. The legacy `/bulk-actions/`
discovery paths do not exist.

## Verification

The test suite vendors the complete SDK `0.1.13` contract bundle under
`tests/contracts/command-center-sdk-v0.1.13/`. It compiles every manifest-selected
schema, accepts every official valid fixture, rejects every official invalid
fixture, validates all 25 discovery documents, and asserts that OpenAPI exposes
one discovery route for every collection route.
