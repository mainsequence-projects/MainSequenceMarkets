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

## Delete Impact

```text
GET /api/v1/pricing/curves/{uid}/delete-impact/?delete_values=false&delete_curve_selections=false
```

Previews whether one pricing curve can be deleted and which related rows would
block or be affected.

Query parameters:

- `delete_values`: when `true`, preview deletion of timestamped
  `DiscountCurvesStorage` observations whose `curve_identifier` matches the
  curve.
- `delete_curve_selections`: when `true`, preview deletion of
  `PricingMarketDataSetCurveBindingTable` rows that point to the curve.

Response model: `DeleteImpactResponse`

Response:

```json
{
  "resource_type": "pricing_curve",
  "uid": "curve-uid",
  "identifier": "USD-SOFR-3M-DISCOUNT",
  "display_name": "USD SOFR 3M Discount Curve",
  "can_delete": false,
  "blocking_count": 12,
  "affected_count": 14,
  "delete_endpoint": "/api/v1/pricing/curves/curve-uid/",
  "relationships": [
    {
      "key": "curve_building_details",
      "label": "Curve building details",
      "model": "CurveBuildingDetailsTable",
      "column": "curve_uid",
      "relationship_type": "direct",
      "on_delete": "CASCADE",
      "count": 1,
      "effect": "cascade_delete",
      "severity": "destructive",
      "blocks_delete": false,
      "description": "Curve-owned build details are keyed by this curve and cascade when the curve row is deleted."
    },
    {
      "key": "pricing_curve_selections",
      "label": "Pricing curve selections",
      "model": "PricingMarketDataSetCurveBindingTable",
      "column": "curve_uid",
      "relationship_type": "direct",
      "on_delete": "RESTRICT",
      "count": 2,
      "effect": "blocks_delete",
      "severity": "blocking",
      "blocks_delete": true,
      "description": "Market-data-set curve-selection rows point at this curve. They must be removed or explicitly deleted before deleting the curve."
    },
    {
      "key": "discount_curve_observations",
      "label": "Discount curve observations",
      "model": "DiscountCurvesStorage",
      "column": "curve_identifier",
      "relationship_type": "direct",
      "on_delete": "RESTRICT",
      "count": 10,
      "effect": "blocks_delete",
      "severity": "blocking",
      "blocks_delete": true,
      "description": "Timestamped discount-curve rows reference this curve by curve_identifier. Cleanup uses TimeIndexMetaTable.delete_after_date with a scoped curve_identifier dimension filter."
    }
  ],
  "warnings": [
    "Delete is blocked while pricing curve-selection rows point at this curve.",
    "Delete is blocked while discount-curve observations reference this curve.",
    "Curve building details will be deleted by database cascade."
  ]
}
```

Returns `404` when the curve `uid` does not exist.

## Delete Curve

```text
DELETE /api/v1/pricing/curves/{uid}/?delete_values=false&delete_curve_selections=false
```

Deletes one pricing curve registry row.

Cleanup semantics:

- `CurveBuildingDetailsTable` rows are deleted by the database cascade on
  `curve_uid`.
- `PricingMarketDataSetCurveBindingTable` rows are deleted only when
  `delete_curve_selections=true`.
- `DiscountCurvesStorage` observations are deleted only when
  `delete_values=true`.
- Discount-curve value cleanup must remain scoped to the curve identifier:
  `TimeIndexMetaTable.delete_after_date(None, dimension_filters={"curve_identifier": [curve_identifier]})`.
- `PricingMarketDataSetBindingTable` source bindings are not deleted by this
  endpoint.

Response model: `CurveDeleteResponse`

Response:

```json
{
  "detail": "Pricing curve deleted.",
  "uid": "curve-uid",
  "curve_identifier": "USD-SOFR-3M-DISCOUNT",
  "deleted_count": 1,
  "deleted_values_count": 10,
  "deleted_curve_selections_count": 2,
  "deleted_curve_building_details_count": 1,
  "delete_values": true,
  "delete_curve_selections": true,
  "storage_cleanups": [
    {
      "data_node_uid": "discount-curves-data-node-uid",
      "storage_table_identifier": "DiscountCurvesStorage",
      "deleted_count": 10,
      "table_empty": false
    }
  ]
}
```

Returns:

- `404` when the curve `uid` does not exist.
- `409` when dependent rows still block deletion because the requested cleanup
  flags do not cover them.

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
