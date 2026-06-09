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
GET /api/v1/pricing/curves/?limit=25&offset=0&search=SOFR&curve_type=discount&index_uid=...&source=example
```

Query parameters:

- `limit`: maximum rows to return, default `25`, max `500`
- `offset`: zero-based row offset, default `0`
- `search`: optional contains search on `unique_identifier`
- `curve_type`: optional exact curve type filter
- `index_uid`: optional exact index uid filter
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
      "index_uid": "index-uid",
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
      "key": "index_uid",
      "label": "Index UID",
      "value": "index-uid",
      "kind": "code",
      "icon": null
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
      "index_uid": "index-uid",
      "interpolation_method": "log_linear_discount",
      "compounding": "compounded_annual",
      "source": "example",
      "metadata_json": {}
    },
    "metadata_json": {}
  }
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
    "index_uid": "index-uid",
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
  ]
}
```

When `valuation_date` is omitted:

```json
{
  "valuation_date": null,
  "effective_date": "2026-06-02T00:00:00Z",
  "request_mode": "latest",
  "nodes": []
}
```

The endpoint returns `404` when the curve, market-data set, discount-curve
binding, or requested observation does not exist.
