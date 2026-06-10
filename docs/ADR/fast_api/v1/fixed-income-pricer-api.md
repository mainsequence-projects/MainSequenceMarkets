# FastAPI v1 Fixed Income Pricer API

## Status

Implemented

The fixed-income pricer API route surface, operation registry, support
discovery, typed request/response contracts, OpenAPI assertions, route tests,
and core execution tests are implemented.

Current curve-preview and fixings-availability endpoints are implemented as
method-backed diagnostics. Decompressed curve nodes and effective curve dates
are already exposed by the dedicated pricing curve route:

```text
GET /api/v1/pricing/curves/{uid}/discount-curve/
```

The asset pricer route should not duplicate that curve-storage endpoint.

## Context

The frontend needs to become a full fixed income pricing workbench for priceable
bond assets. The backend already stores current instrument terms through
`AssetCurrentPricingDetails` and can rebuild Python pricing instruments with:

```python
from msm_pricing import Instrument

instrument = Instrument.load_from_asset(asset)
instrument.set_valuation_date(valuation_date)
```

Supported bond instrument classes exported by `msm_pricing` include:

```text
FixedRateBond
CallableFixedRateBond
AmortizingFixedRateBond
ZeroCouponBond
FloatingRateBond
AmortizingFloatingRateBond
```

Implemented bond methods include:

```text
price(...)
analytics(...)
duration(...)
z_spread(...)
get_cashflows(...)
get_cashflows_df()
get_net_cashflows()
get_yield(...)
carry_roll_down(...)
get_ql_bond(...)
```

The existing FastAPI endpoint:

```text
GET /api/v1/asset/{uid}/get_pricing_details/
```

currently returns only the persisted pricing details row. That is useful but not
enough for a frontend pricer, because the frontend also needs to know which
pricing operations are available for the attached instrument type and how to
call them.

## Decision

Build the fixed income pricer API as a registry-driven API with explicit
operation endpoints.

The API must not expose arbitrary Python method names or generic reflection.
Only operations registered by `src/msm_pricing/api` are executable.

The architecture is:

```text
AssetCurrentPricingDetails
  -> instrument_type
  -> pricing operation registry
  -> discovery payload on get_pricing_details
  -> explicit pricing operation endpoints
  -> typed response contracts
```

`apps/v1` remains only the HTTP resolver layer. All loading, registry
resolution, pricing execution, result normalization, and diagnostics must live
under `src/msm_pricing/api`.

## Discovery Endpoint

Enhance the existing pricing details endpoint with additive discovery metadata:

```text
GET /api/v1/asset/{uid}/get_pricing_details/
```

The endpoint continues to return the current pricing details row. It also adds
`pricing_support`, which tells the frontend whether this asset can be used in
the fixed income pricer and which operation endpoints are available.

Example response shape:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "instrument_dump": {},
  "pricing_details_date": "2026-06-09T00:00:00Z",
  "serialization_format": "json",
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
        "request_model": "BondPricingOperationRequest",
        "response_model": "BondPriceResponse"
      },
      {
        "key": "analytics",
        "label": "Analytics",
        "method": "POST",
        "url": "/api/v1/pricing/assets/asset-uid/analytics/",
        "requires_valuation_date": true,
        "supports_market_data_set": true,
        "request_model": "BondPricingOperationRequest",
        "response_model": "BondAnalyticsResponse"
      }
    ]
  }
}
```

Unsupported or missing pricing details should not invent capabilities:

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

## Operation Endpoints

Expose explicit endpoints under:

```text
/api/v1/pricing/assets/{asset_uid}/
```

Initial scope includes all fixed income pricer operations needed by the frontend.
There is no deferred second phase for yield, z-spread, carry/roll-down, curve
preview, or fixings availability.

Required endpoints:

```text
POST /api/v1/pricing/assets/{asset_uid}/price/
POST /api/v1/pricing/assets/{asset_uid}/analytics/
POST /api/v1/pricing/assets/{asset_uid}/duration/
POST /api/v1/pricing/assets/{asset_uid}/yield/
POST /api/v1/pricing/assets/{asset_uid}/z-spread/
POST /api/v1/pricing/assets/{asset_uid}/cashflows/
POST /api/v1/pricing/assets/{asset_uid}/net-cashflows/
POST /api/v1/pricing/assets/{asset_uid}/carry-roll-down/
POST /api/v1/pricing/assets/{asset_uid}/curve-preview/
POST /api/v1/pricing/assets/{asset_uid}/fixings-availability/
```

Each endpoint must:

1. load the asset by `asset_uid`;
2. rebuild the instrument through `Instrument.load_from_asset(asset)`;
3. set the valuation date;
4. apply the selected `market_data_set`;
5. execute only the registered operation;
6. return a declared Pydantic response model.

## Common Request Contract

Most operations share the same boundary:

```json
{
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "parameters": {}
}
```

Rules:

- `valuation_date` is required for all pricing operations.
- `market_data_set` is required for market-data-backed operations and should
  accept a set key or set uid.
- operation-specific inputs live under `parameters`.
- the request must be strict: reject unknown fields at the HTTP boundary.

## Operation Contracts

### Price

Python source:

```python
instrument.price(market_data_set="eod")
```

Request parameters:

```json
{
  "with_yield": null,
  "flat_compounding": null,
  "flat_frequency": null
}
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "price": 101.25,
  "currency": null,
  "units": "npv"
}
```

### Analytics

Python source:

```python
instrument.analytics(market_data_set="eod")
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "analytics": {
    "clean_price": 100.75,
    "dirty_price": 101.25,
    "accrued_amount": 0.5
  }
}
```

### Duration

Python source:

```python
instrument.duration(market_data_set="eod")
```

Request parameters:

```json
{
  "with_yield": null,
  "duration_type": "Modified",
  "flat_compounding": null,
  "flat_frequency": null
}
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "duration_type": "Modified",
  "duration": 4.82
}
```

### Yield

Python source:

```python
instrument.get_yield(...)
```

Request parameters:

```json
{
  "override_clean_price": null
}
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "yield": 0.0525
}
```

### Z-Spread

Python source:

```python
instrument.z_spread(target_dirty_ccy=101.25, market_data_set="eod")
```

Request parameters:

```json
{
  "target_dirty_ccy": 101.25,
  "use_quantlib": true,
  "tol": 1e-12,
  "max_iter": 200
}
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "target_dirty_ccy": 101.25,
  "z_spread": 0.0042,
  "units": "decimal"
}
```

### Cashflows

Python source:

```python
instrument.get_cashflows(market_data_set="eod")
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
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
    "floating": [],
    "redemption": [
      {
        "payment_date": "2030-06-09",
        "amount": 100.0
      }
    ]
  }
}
```

### Net Cashflows

Python source:

```python
instrument.get_net_cashflows()
```

The API must not return a pandas `Series`. It must serialize to rows:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "cashflows": [
    {
      "payment_date": "2026-12-09",
      "net_cashflow": 2.5
    },
    {
      "payment_date": "2030-06-09",
      "net_cashflow": 102.5
    }
  ]
}
```

### Carry/Roll-Down

Python source:

```python
instrument.price(market_data_set="eod")
instrument.carry_roll_down(...)
```

`carry_roll_down(...)` requires the bond to be priced first. The API operation
must handle that internally and must not require the frontend to call `price`
first.

Request parameters:

```json
{
  "horizon_days": 30,
  "clean": true
}
```

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "horizon_days": 30,
  "metrics": {
    "p0_dirty_per100": 101.25,
    "p0_clean_per100": 100.75,
    "p1_dirty_per100_unchanged_curve": 101.6,
    "p1_dirty_per100_const_yield": 101.4,
    "cr_dirty": 0.35,
    "carry_const_dirty": 0.15,
    "roll_down_dirty": 0.2,
    "coupons_between_ccy": 0.0,
    "cr_plus_coupons_dirty": 0.35
  }
}
```

### Curve Preview

Curve preview is a frontend diagnostic for the market data used by the pricer.
It must stay asset/instrument-oriented and method-backed.

Decompressed discount curve observations are not part of this endpoint because
they already have a dedicated pricing curve route:

```text
GET /api/v1/pricing/curves/{uid}/discount-curve/?market_data_set=eod&valuation_date=2026-06-09T00:00:00Z
```

If the frontend needs curve nodes, it should use that existing pricing curve
endpoint once it knows the relevant curve uid. Future asset-pricer diagnostics
may expose curve references or links, but should not duplicate the curve node
payload.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FixedRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "curves": [],
  "diagnostics": {
    "pricing_engine_id": "engine-id"
  }
}
```

If the current pricing library does not expose a public helper that identifies
the curve identities required by an instrument, add that helper under
`src/msm_pricing/api`. Do not inspect private instrument attributes in
`apps/v1`.

### Fixings Availability

Fixings availability is a frontend diagnostic for floating-rate instruments. It
should show whether the required historical fixings exist for the instrument's
index references and valuation context.

Response:

```json
{
  "asset_uid": "asset-uid",
  "instrument_type": "FloatingRateBond",
  "valuation_date": "2026-06-09T00:00:00Z",
  "market_data_set": "eod",
  "fixings": [
    {
      "index_uid": "index-uid",
      "index_identifier": "USD-SOFR-3M",
      "required_start_date": "2025-06-09",
      "required_end_date": "2026-06-09",
      "available_start_date": "2025-06-09",
      "available_end_date": "2026-06-09",
      "missing_count": 0,
      "status": "complete"
    }
  ]
}
```

If fixed-rate instruments do not need fixings, return an empty list with status
metadata rather than failing.

## Unsupported Direct Methods

Do not expose `get_ql_bond(...)` directly. It returns a QuantLib object and is
not an HTTP response contract.

Do not expose `get_cashflows_df()` directly. It returns a pandas DataFrame. The
API should expose normalized cashflow rows instead.

## Core Registry

Add a pricing operation registry under `src/msm_pricing/api`, for example:

```text
src/msm_pricing/api/asset_pricing_operations.py
```

The registry owns:

- supported instrument classes;
- operation definitions;
- required request parameters;
- response model keys;
- method dispatch;
- serialization of Python objects into JSON-safe payloads;
- pricing diagnostics for curves and fixings.

The registry must be explicit. Example conceptual shape:

```text
FixedRateBond
  price
  analytics
  duration
  yield
  z-spread
  cashflows
  net-cashflows
  carry-roll-down
  curve-preview
  fixings-availability

FloatingRateBond
  price
  analytics
  duration
  yield
  z-spread
  cashflows
  net-cashflows
  carry-roll-down
  curve-preview
  fixings-availability
```

The frontend gets dynamic discovery from this registry, but execution remains
strict and endpoint-specific.

## Error Semantics

Use clear HTTP error mapping:

- `404`: asset not found or pricing details not found.
- `400`: operation is not supported for the instrument type.
- `422`: request body is invalid or required operation parameters are missing.
- `409`: pricing details exist, but market data, curves, fixings, or bindings
  are incomplete for the requested valuation.
- `500`: unexpected pricing runtime failure only.

Do not convert missing market-data dependencies into empty pricing results.

## Implementation Tasks

- [x] Add `src/msm_pricing/api/asset_pricing_operations.py`.
- [x] Add explicit operation registry for all exported bond instrument classes.
- [x] Add core helper to build pricing support metadata for one asset.
- [x] Enhance `AssetCurrentPricingDetails` API output with additive
      `pricing_support`.
- [x] Add core operation execution helper that loads the asset, rebuilds the
      instrument, sets valuation date, applies market-data set, and executes one
      registered operation.
- [x] Add strict request and response Pydantic contracts under `apps/v1/schemas`.
- [x] Add `apps/v1` router endpoints under `/api/v1/pricing/assets/{asset_uid}/`.
- [x] Implement `price` endpoint.
- [x] Implement `analytics` endpoint.
- [x] Implement `duration` endpoint.
- [x] Implement `yield` endpoint.
- [x] Implement `z-spread` endpoint.
- [x] Implement `cashflows` endpoint.
- [x] Implement `net-cashflows` endpoint.
- [x] Implement `carry-roll-down` endpoint with internal pre-pricing.
- [x] Implement `curve-preview` endpoint as method-backed pricing diagnostics.
- [x] Implement `fixings-availability` endpoint as method-backed pricing
      diagnostics.
- [x] Add OpenAPI assertions for every new route and response model.
- [x] Add focused route tests under `tests/msm/fastapi/v1`.
- [x] Add core registry and execution tests under `tests/msm_pricing/api`.
- [x] Document the frontend handoff under `docs/fast_api/v1`.

## Follow-Up Tasks

- [ ] If the instrument/pricing engine exposes the selected curve uid, add that
      curve reference or link to `curve-preview` so the frontend can call the
      existing pricing curve discount-curve endpoint.
- [ ] Enhance `fixings-availability` to return per-index required ranges,
      available ranges, missing count, and status from index fixing storage.
- [ ] Enforce non-null `market_data_set` for operations whose instrument method
      requires market-data-backed pricing.

## Success Criteria

This decision is complete when:

- the frontend can discover supported fixed income pricing operations from
  `GET /api/v1/asset/{uid}/get_pricing_details/`;
- every discovered operation has a matching explicit endpoint;
- price, analytics, duration, yield, z-spread, cashflows, net cashflows,
  carry/roll-down, curve preview, and fixings availability are all included in
  the initial implementation;
- every endpoint has a strict request and response model;
- no endpoint exposes raw QuantLib or pandas objects;
- missing pricing details, unsupported instruments, missing curves, missing
  fixings, and missing market-data bindings produce clear typed errors;
- all implementation tests, OpenAPI checks, app import sanity checks, ruff, and
  documentation builds pass.
