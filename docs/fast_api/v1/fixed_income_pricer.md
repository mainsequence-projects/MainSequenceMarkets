# Fixed Income Pricer Routes

The fixed income pricer route group is exposed under:

```text
/api/v1/pricing/assets/
```

These endpoints execute registered bond pricing operations for assets that have
current pricing details attached through `msm_pricing.api.AssetCurrentPricingDetails`.

The route layer does not implement pricing formulas. Each operation delegates to
the rebuilt instrument method:

```python
instrument = Instrument.load_from_asset(asset)
instrument.set_valuation_date(valuation_date)
instrument.price(...)
```

## Discovery

```text
GET /api/v1/asset/{uid}/get_pricing_details/
```

Returns the current pricing details row and an additive `pricing_support`
section.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "instrument_dump": {},
  "pricing_details_date": "2026-06-09T00:00:00Z",
  "serialization_format": "msm_pricing.instrument.v1",
  "pricing_package_version": "4.3.14",
  "source": "example",
  "metadata_json": {},
  "pricing_support": {
    "supported": true,
    "instrument_type": "FixedRateBond",
    "operations": [
      {
        "key": "price",
        "label": "Price",
        "method": "POST",
        "url": "/api/v1/pricing/assets/asset-uid/price/",
        "requires_valuation_date": true,
        "supports_market_data_set": true,
        "requires_market_data_set": true,
        "request_model": "AssetPricingOperationRequest",
        "response_model": "BondPriceResponse",
        "response_contract": "provider-native-json",
        "app_component": {
          "output_root": "response:$",
          "flat_outputs": ["price", "units"]
        },
        "parameters": [
          {
            "key": "curve_quote_side",
            "required": false
          },
          {
            "key": "flat_compounding",
            "required": false
          },
          {
            "key": "flat_frequency",
            "required": false
          },
          {
            "key": "with_yield",
            "required": false
          }
        ],
        "response_mappings": []
      }
    ]
  }
}
```

Unsupported instrument response:

```json
{
  "pricing_support": {
    "supported": false,
    "instrument_type": "UnsupportedInstrument",
    "operations": [],
    "reason": "Instrument type is not registered for the fixed income pricer API."
  }
}
```

## Common Request

All operation endpoints use the same request envelope:

```json
{
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "parameters": {}
}
```

`valuation_date` is required. `market_data_set` accepts the pricing market-data
set selector passed to the instrument operation. Current registered fixed income
operations require `market_data_set`; missing or blank values return `422` before
the instrument is loaded. Unknown top-level request fields are rejected. Unknown
operation parameters are rejected by the core operation registry before dispatch.

Curve-dependent operations can carry `curve_quote_side`. Z-spread can also carry
benchmark-specific selection fields:

```json
{
  "parameters": {
    "target_dirty_ccy": 101.25,
    "benchmark_curve_role_key": "z_spread_base",
    "benchmark_curve_quote_side": "mid",
    "benchmark_curve_uid": null,
    "benchmark_curve_unique_identifier": null,
    "benchmark_expected_curve_type": "discount"
  }
}
```

`benchmark_rate_index_uid` stored on an instrument is only an index selector.
For z-spread, the backend resolves the curve through
`PricingMarketDataSetCurveBinding.resolve_index_curve_uid(...)` using the
requested market-data set, `role_key`, `benchmark_rate_index_uid`, and quote
side. That user API hides the generic persisted selector fields.

## Command Center Rendering Contracts

The pricing operation endpoints return provider-native business JSON. Their
OpenAPI schemas include AppComponent binding metadata such as:

```json
{
  "x-command-center-consumer": "app-component",
  "x-ui-output-root": "response:$",
  "x-ui-response-mode": "provider-native-json",
  "x-ui-flat-outputs": ["price", "units"]
}
```

These operation responses are not `editable-form` or `notification` payloads.
Those `x-ui-role` values are reserved for SDK models that render as
response-side editable forms or banner notifications.

For table-shaped cashflow outputs, the API also exposes direct Command Center
frame endpoints using the SDK `core.tabular_frame@v1` contract:

```text
POST /api/v1/pricing/assets/{asset_uid}/cashflows/frame/
POST /api/v1/pricing/assets/{asset_uid}/net-cashflows/frame/
```

The original cashflow endpoints still return provider-native pricing JSON and
carry `x-response-mappings` metadata for frontend/editor context. The frame
endpoints are the routes to bind directly into generic table, chart, curve,
transform, or agent-facing Command Center consumers.

## Price

```text
POST /api/v1/pricing/assets/{asset_uid}/price/
```

Delegates to:

```python
instrument.price(market_data_set=market_data_set, **parameters)
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "price",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "price": 101.25,
  "units": "npv"
}
```

## Analytics

```text
POST /api/v1/pricing/assets/{asset_uid}/analytics/
```

Delegates to:

```python
instrument.analytics(market_data_set=market_data_set, **parameters)
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "analytics",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "analytics": {
    "clean_price": 100.75,
    "dirty_price": 101.25,
    "accrued_amount": 0.5
  }
}
```

## Duration

```text
POST /api/v1/pricing/assets/{asset_uid}/duration/
```

Delegates to:

```python
instrument.duration(market_data_set=market_data_set, **parameters)
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "duration",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "duration_type": "Modified",
  "duration": 4.82
}
```

## Yield

```text
POST /api/v1/pricing/assets/{asset_uid}/yield/
```

Delegates to:

```python
instrument.get_yield(**parameters)
```

If `market_data_set` is provided, the implementation first runs
`instrument.analytics(market_data_set=market_data_set)` so the instrument is
priced against the selected market-data set before yield is read.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "yield",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "yield": 0.0525
}
```

## Z-Spread

```text
POST /api/v1/pricing/assets/{asset_uid}/z-spread/
```

Delegates to:

```python
instrument.z_spread(market_data_set=market_data_set, **parameters)
```

Required parameter:

```json
{
  "target_dirty_ccy": 101.25,
  "curve_quote_side": "offer",
  "benchmark_curve_role_key": "z_spread_base",
  "benchmark_curve_quote_side": "mid",
  "benchmark_curve_uid": null,
  "benchmark_curve_unique_identifier": null,
  "benchmark_expected_curve_type": "discount",
  "use_quantlib": true,
  "tol": 1e-12,
  "max_iter": 200
}
```

If the instrument has `benchmark_rate_index_uid`, omitted
`benchmark_curve_quote_side` uses `curve_quote_side` when supplied; otherwise it
requests the default quote-side binding. A missing
`z_spread_base:index:<uid>:<quote_side>` binding is returned as a pricing
dependency error instead of being treated as a clean fallback.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "z-spread",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "target_dirty_ccy": 101.25,
  "z_spread": 0.0042,
  "units": "decimal"
}
```

## Cashflows

```text
POST /api/v1/pricing/assets/{asset_uid}/cashflows/
```

Delegates to:

```python
instrument.get_cashflows(market_data_set=market_data_set, **parameters)
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "cashflows",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "legs": {
    "fixed": [
      {
        "payment_date": "2026-12-09",
        "rate": 0.05,
        "amount": 2.5
      }
    ],
    "redemption": [
      {
        "payment_date": "2030-06-09",
        "amount": 100.0
      }
    ]
  }
}
```

Canonical frame endpoint:

```text
POST /api/v1/pricing/assets/{asset_uid}/cashflows/frame/
```

Frame response:

```json
{
  "status": "ready",
  "error": null,
  "columns": ["leg", "payment_date", "amount", "rate"],
  "rows": [
    {
      "leg": "fixed",
      "payment_date": "2026-12-09",
      "amount": 2.5,
      "rate": 0.05
    }
  ],
  "fields": [
    {
      "key": "leg",
      "label": "Leg",
      "description": null,
      "type": "string",
      "nullable": null,
      "nativeType": null,
      "provenance": "manual",
      "reason": null,
      "derivedFrom": null,
      "warnings": null
    }
  ],
  "meta": null,
  "source": {
    "kind": "api",
    "id": null,
    "label": "Fixed income cashflows",
    "updatedAtMs": null,
    "context": {
      "asset_uid": "asset-uid",
      "instrument_type": "FixedRateBond",
      "operation": "cashflows",
      "valuation_date": "2026-06-09T00:00:00Z",
      "market_data_set": "eod"
    }
  }
}
```

## Net Cashflows

```text
POST /api/v1/pricing/assets/{asset_uid}/net-cashflows/
```

Delegates to:

```python
instrument.get_net_cashflows(market_data_set=market_data_set, **parameters)
```

The API serializes the returned series-like object into rows.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "net-cashflows",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "cashflows": [
    {
      "payment_date": "2026-12-09",
      "net_cashflow": 2.5
    }
  ]
}
```

Canonical frame endpoint:

```text
POST /api/v1/pricing/assets/{asset_uid}/net-cashflows/frame/
```

Frame response:

```json
{
  "status": "ready",
  "error": null,
  "columns": ["payment_date", "net_cashflow"],
  "rows": [
    {
      "payment_date": "2026-12-09",
      "net_cashflow": 2.5
    }
  ],
  "fields": [
    {
      "key": "payment_date",
      "label": "Payment Date",
      "description": null,
      "type": "date",
      "nullable": null,
      "nativeType": null,
      "provenance": "manual",
      "reason": null,
      "derivedFrom": null,
      "warnings": null
    }
  ],
  "meta": null,
  "source": {
    "kind": "api",
    "id": null,
    "label": "Fixed income net cashflows",
    "updatedAtMs": null,
    "context": {
      "asset_uid": "asset-uid",
      "instrument_type": "FixedRateBond",
      "operation": "net-cashflows",
      "valuation_date": "2026-06-09T00:00:00Z",
      "market_data_set": "eod"
    }
  }
}
```

## Carry/Roll-Down

```text
POST /api/v1/pricing/assets/{asset_uid}/carry-roll-down/
```

Delegates to:

```python
instrument.price(market_data_set=market_data_set)
instrument.carry_roll_down(horizon_days, clean=clean)
```

Required parameter:

```json
{
  "horizon_days": 30
}
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "carry-roll-down",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "horizon_days": 30,
  "metrics": {
    "cr_dirty": 0.35,
    "roll_down_dirty": 0.2
  }
}
```

## Curve Preview

```text
POST /api/v1/pricing/assets/{asset_uid}/curve-preview/
```

This endpoint is intentionally method-backed. It prices the instrument and
returns pricing-engine diagnostics without reading curve storage directly from
the FastAPI layer. When the instrument exposes an index-backed selected curve,
the response includes a link to the existing pricing curve endpoint that returns
decompressed nodes and the effective curve date.

For floating-rate projection curves, pass `curve_quote_side`. For benchmark
z-spread curves, pass `benchmark_curve_quote_side`; the response reports that
side as `binding_quote_side`.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "operation": "curve-preview",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "curves": [
    {
      "role": "discount",
      "curve_uid": "curve-uid",
      "curve_identifier": "USD-SOFR-DISCOUNT",
      "curve_type": "discount",
      "index_uid": "index-uid",
      "binding_quote_side": "mid",
      "source": "example",
      "discount_curve_url": "/api/v1/pricing/curves/curve-uid/discount-curve/",
      "discount_curve_query_params": {
        "market_data_set": "eod",
        "valuation_date": "2026-06-09T00:00:00Z"
      }
    }
  ],
  "diagnostics": {
    "pricing_engine_id": "engine-id"
  }
}
```

To fetch the actual decompressed curve nodes, call:

```text
GET /api/v1/pricing/curves/{curve_uid}/discount-curve/?market_data_set=eod&valuation_date=2026-06-09T00:00:00Z
```

## Fixings Availability

```text
POST /api/v1/pricing/assets/{asset_uid}/fixings-availability/
```

This endpoint reports whether the instrument's index references have historical
fixings in the requested market-data set. It does not require a successful
`price(...)` call; missing curve or fixing storage bindings still surface as
typed API errors.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FloatingRateBond",
  "operation": "fixings-availability",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "status": "partial",
  "fixings": [
    {
      "index_uid": "index-uid",
      "index_identifier": "USD-SOFR-3M",
      "required_start_date": "2025-06-09",
      "required_end_date": "2026-06-09",
      "available_start_date": "2025-06-09",
      "available_end_date": "2026-06-06",
      "missing_count": 1,
      "status": "partial"
    }
  ]
}
```

Fixed-rate instruments that do not require index fixings return:

```json
{
  "status": "not_required",
  "fixings": []
}
```

## Errors

- `404`: asset or pricing details were not found.
- `400`: the operation is not supported for the instrument type.
- `422`: the request shape or operation parameters are invalid.
- `409`: the instrument exists but required market-data dependencies are missing
  or inconsistent.
