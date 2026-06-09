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

