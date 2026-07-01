# Pricing Curve Routes

The pricing curve registry route group is exposed under:

```text
/api/v1/pricing/curves/
```

These routes list `CurveTable` registry rows through `msm_pricing.api.Curve`.
They do not return timestamped `DiscountCurvesStorage` observations or
compressed curve payloads.

## List Curves

```text
GET /api/v1/pricing/curves/?limit=25&offset=0&search=SOFR&curve_type=discount&source=example
```

Query parameters:

- `limit`: maximum rows to return, default `25`, max `500`
- `offset`: zero-based row offset, default `0`
- `search`: optional contains search on `unique_identifier`
- `curve_type`: optional exact curve type filter
- `source`: optional exact source filter

Response:

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "uid": "curve-uid",
      "unique_identifier": "USD-SOFR-3M-DISCOUNT",
      "display_name": "USD SOFR 3M Discount Curve",
      "curve_type": "discount",
      "interpolation_method": "log_linear_discount",
      "compounding": "compounded_annual",
      "source": "example",
      "metadata_json": {}
    }
  ]
}
```

The response uses the shared v1 limit-offset envelope:

```json
{
  "count": 0,
  "next": null,
  "previous": null,
  "results": []
}
```

## Curve Summary

```text
GET /api/v1/pricing/curves/{uid}/summary/
```

Gets the reusable detail summary card payload for one pricing curve registry
row by `uid`.

Response model: `FrontEndDetailSummary`

Response:

```json
{
  "entity": {
    "id": "curve-uid",
    "type": "pricing_curve",
    "title": "USD SOFR 3M Discount Curve"
  },
  "badges": [
    {
      "key": "curve_type",
      "label": "discount",
      "tone": "info"
    }
  ],
  "inline_fields": [
    {
      "key": "uid",
      "label": "UID",
      "value": "curve-uid",
      "kind": "code",
      "icon": null
    },
    {
      "key": "unique_identifier",
      "label": "Identifier",
      "value": "USD-SOFR-3M-DISCOUNT",
      "kind": "code",
      "icon": null
    },
    {
      "key": "curve_selection_count",
      "label": "Curve Selections",
      "value": 2,
      "kind": "number",
      "icon": null,
      "link_url": "/api/v1/pricing/curves/curve-uid/curve-selections/"
    }
  ],
  "highlight_fields": [
    {
      "key": "display_name",
      "label": "Display Name",
      "value": "USD SOFR 3M Discount Curve",
      "kind": "text",
      "icon": "database"
    },
    {
      "key": "curve_type",
      "label": "Curve Type",
      "value": "discount",
      "kind": "code",
      "icon": "line-chart"
    }
  ],
  "stats": [],
  "label_management": null,
  "summary_warning": null,
  "extensions": {
    "curve": {
      "uid": "curve-uid",
      "unique_identifier": "USD-SOFR-3M-DISCOUNT",
      "display_name": "USD SOFR 3M Discount Curve",
      "curve_type": "discount",
      "interpolation_method": "log_linear_discount",
      "compounding": "compounded_annual",
      "source": "example",
      "metadata_json": {}
    },
    "curve_selection_count": 2,
    "curve_selections_url": "/api/v1/pricing/curves/curve-uid/curve-selections/",
    "metadata_json": {}
  }
}
```

Returns `404` when the curve `uid` does not exist.

## Curve Selections

```text
GET /api/v1/pricing/curves/{uid}/curve-selections/
```

Returns market-data-set curve-selection bindings that point to this curve.
This is a reverse lookup over `PricingMarketDataSetCurveBindingTable`; it does
not imply that the curve owns the index or selector.

Response model: `CurveSelectionsResponse`

Response:

```json
{
  "curve": {
    "uid": "curve-uid",
    "unique_identifier": "USD-SOFR-OFFER-BENCHMARK",
    "display_name": "USD SOFR offer benchmark",
    "curve_type": "discount"
  },
  "count": 1,
  "results": [
    {
      "binding_uid": "binding-uid",
      "market_data_set": {
        "uid": "market-data-set-uid",
        "set_key": "eod",
        "display_name": "End of day"
      },
      "role_key": "z_spread_base",
      "quote_side": "offer",
      "selector": {
        "type": "index",
        "selector_key": "index-uid",
        "index_uid": "index-uid",
        "index_identifier": "USD-SOFR",
        "display_name": "USD SOFR"
      },
      "status": "ACTIVE",
      "source": "example"
    }
  ]
}
```

Returns `404` when the curve `uid` does not exist.

## Discount Curve Nodes

```text
GET /api/v1/pricing/curves/{uid}/discount-curve/?market_data_set=eod&valuation_date=2026-06-01T00:00:00Z
```

Reads discount-curve nodes for one curve through `MSDataInterface`.

Query parameters:

- `market_data_set`: required pricing market-data set selector. Accepts a set
  uid or set key.
- `valuation_date`: optional ISO datetime. When omitted, the endpoint returns
  the latest available discount-curve observation for the curve.

Response model: `DiscountCurveResponse`

`nodes` is the normalized decompressed pricing curve. `key_nodes` is
producer-owned construction provenance returned as decompressed JSON; the
storage column is compressed text. Consumers may display standard fields such
as `maturity_date`, `asset_identifier`, `instrument_type`, `quote`,
`quote_type`, `quote_unit`, `quote_side`, and `yield` when present, but the API
only requires the base JSON object/list contract because source producers may
enforce stricter schemas through their DataNode validation extension.

Response:

```json
{
  "curve_uid": "curve-uid",
  "curve_identifier": "USD-SOFR-3M-DISCOUNT",
  "curve": {
    "uid": "curve-uid",
    "unique_identifier": "USD-SOFR-3M-DISCOUNT",
    "display_name": "USD SOFR 3M Discount Curve",
    "curve_type": "discount",
    "interpolation_method": "log_linear_discount",
    "compounding": "compounded_annual",
    "source": "example",
    "metadata_json": {}
  },
  "market_data_set": {
    "uid": "market-data-set-uid",
    "set_key": "eod",
    "display_name": "End of day"
  },
  "binding": {
    "uid": "binding-uid",
    "concept_key": "discount_curves",
    "data_node_uid": "discount-curves-data-node-uid",
    "storage_table_identifier": "DiscountCurvesStorage"
  },
  "valuation_date": "2026-06-01T00:00:00Z",
  "effective_date": "2026-06-01T00:00:00Z",
  "request_mode": "historical",
  "nodes": [
    {
      "days_to_maturity": 28,
      "zero": 0.11
    },
    {
      "days_to_maturity": 91,
      "zero": 0.105
    }
  ],
  "key_nodes": [
    {
      "maturity_date": "2026-06-29",
      "asset_identifier": "USD_SOFR_SWAP_1M",
      "instrument_type": "interest_rate_swap",
      "quote": 0.11,
      "quote_type": "par_rate",
      "quote_unit": "decimal",
      "quote_side": "mid"
    }
  ],
  "metadata_json": {
    "source_snapshot": "example-2026-06-01"
  }
}
```

When `valuation_date` is omitted:

```json
{
  "valuation_date": null,
  "effective_date": "2026-06-02T00:00:00Z",
  "request_mode": "latest",
  "nodes": [],
  "key_nodes": null,
  "metadata_json": null
}
```

The endpoint returns `404` when the curve, market-data set, discount-curve
binding, or requested observation does not exist.

When the curve registry row and `discount_curves` binding exist but the bound
DataNode has no rows for that curve, the response reports the missing data
state explicitly:

```json
{
  "detail": "No discount-curve data has been published for curve 'VALMER_TIIE_28' in pricing market-data set 'default'. The curve registry row and discount_curves binding exist, but bound DataNode <data-node-uid> has no latest ms_markets__discountcurvests observation for this curve_identifier."
}
```
