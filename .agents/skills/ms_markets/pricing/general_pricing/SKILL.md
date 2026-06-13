---
name: mainsequence-markets-general-pricing
description: Use this skill when changing, reviewing, or documenting the generic msm_pricing package surface, including pricing runtime attachment, asset pricing details persistence, market-data set bindings, priceable instrument payload boundaries, and in-memory valuation baskets. This skill does not own fixed-income curve/index/fixing construction details; use the fixed-income curve-building skill for those.
---

# Main Sequence Markets General Pricing

Use this skill for generic `msm_pricing` work: package boundaries, pricing
runtime attachment, instrument persistence, market-data-set selection, and
transient instrument-plus-units valuation.

## Route First

Use the fixed-income curve-building skill when the task is specifically about:

- `IndexConventionDetails`
- `Curve`
- `DiscountCurvesNode`
- `FixingRatesNode`
- QuantLib index/curve resolver behavior
- bond or swap examples that depend on curve and fixing setup

Use the asset model extension skill when the task changes canonical asset rows
or bond asset detail tables.

## This Skill Owns

- `msm_pricing.bootstrap.attach_pricing_schemas(...)` as the attach-only pricing
  runtime startup entrypoint.
- `AssetCurrentPricingDetails`, timestamped pricing details, and
  `add_many_pricing_details(...)` persistence workflows.
- `load_instruments_from_assets(...)` for batch loading current priceable
  instruments from already-resolved `Asset` rows.
- `PricingMarketDataSet` and `PricingMarketDataSetBinding` as the source
  selection layer for pricing concepts.
- `InstrumentModel` payload boundaries: instrument payloads contain pricing
  terms, not asset identity.
- `ValuationLine` and `ValuationPosition` as transient valuation baskets for
  `instrument + units + valuation_date + market_data_set`.
- The rule that `msm_pricing` does not own durable account or portfolio
  positions.

## Read First

Inspect the local files relevant to the request:

1. `src/msm_pricing/bootstrap.py`
2. `src/msm_pricing/api/pricing_details.py`
3. `src/msm_pricing/api/instruments.py`
4. `src/msm_pricing/api/market_data_bindings.py`
5. `src/msm_pricing/instruments/base_instrument.py`
6. `src/msm_pricing/valuation.py`
7. `src/msm_pricing/meta_tables.py`
8. `docs/knowledge/msm_pricing/index.md`
9. `docs/ADR/0026-explicit-pricing-market-data-sets.md`
10. `docs/ADR/0033-pricing-valuation-position-boundary.md`

## Runtime Startup

Attach pricing tables explicitly before pricing row operations:

```python
from msm_pricing.bootstrap import attach_pricing_schemas

attach_pricing_schemas(
    models=[
        "Asset",
        "IndexType",
        "Index",
        "IndexConventionDetails",
        "Curve",
        "AssetCurrentPricingDetails",
        "PricingMarketDataSet",
        "PricingMarketDataSetBinding",
    ],
    seed_default_market_data_bindings=False,
)
```

Do not add schema-creation shortcuts or direct registration calls. Pricing
startup attaches already migrated and registered MetaTables.

## Instrument Persistence

Persist one asset/instrument relationship with:

```python
instrument.attach_to_asset(asset, pricing_details_date=valuation_date)
```

For large universes, use batch persistence:

```python
from msm_pricing.api import add_many_pricing_details, load_instruments_from_assets

add_many_pricing_details(
    [
        {"asset": asset, "instrument": instrument, "pricing_details_date": as_of}
        for asset, instrument in asset_instrument_pairs
    ],
    batch_size=1000,
)
```

Explicit dated writes must reconcile the current projection: update current
only when there is no current row or when the new date is newer than the
current `pricing_details_date`.

When a caller already has asset rows and needs their current priceable
instruments, use:

```python
instruments_by_asset_uid = load_instruments_from_assets(assets, batch_size=1000)
```

## Valuation Baskets

Use `ValuationPosition` for in-memory valuation of instruments with unit
multipliers:

```python
from msm_pricing.valuation import ValuationLine, ValuationPosition

position = ValuationPosition(
    valuation_date=valuation_date,
    market_data_set="eod",
    lines=[
        ValuationLine(instrument=bond, units=25.0, asset_uid=asset.uid),
    ],
)

value = position.price()
breakdown = position.price_breakdown()
```

Rules:

- `ValuationPosition` is not a MetaTable and is not persisted.
- Do not reintroduce `msm_pricing.Position` or `PositionLine`.
- Do not add generic `source_type` or `source_uid` fields without a concrete
  ADR-backed consumer.
- Keep `market_data_set` at the `ValuationPosition` level. Do not add line-level
  market-data-set overrides unless a later ADR introduces that policy.
- `asset_uid` is optional; ad hoc instruments may not have a persisted asset.
- Account holdings and portfolio weights must be normalized by their owning
  package before they are passed into pricing as valuation lines.
- For account holdings, the owning workflow selects the holdings snapshot,
  resolves `asset_identifier` to `Asset`, and computes signed units from
  `quantity * direction`.
- For portfolio sources, the owning workflow chooses the composition/valuation
  source and converts weights, notionals, or quantities into asset-level units.

## Market-Data Sets

Use `PricingMarketDataSet` and `PricingMarketDataSetBinding` for source
selection. Bindings store backend DataNode storage table UIDs for pricing
concepts such as `discount_curves` and `interest_rate_index_fixings`.

Callers select sources at valuation time:

```python
bond.price(market_data_set="eod")
position = ValuationPosition(..., market_data_set="risk_manager")
```

Do not use legacy context constants or storage identifiers as authoritative
runtime pointers.
