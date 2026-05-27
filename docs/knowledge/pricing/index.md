# Pricing

The pricing concept owns instrument valuation. It contains priceable instrument
terms, QuantLib helpers, curve and fixing access, and registration utilities
needed to turn stored market data into runtime valuation objects.

Pricing is not part of the core `msm` import package. Install it explicitly with
`ms-markets[pricing]` and import it through `msm_pricing`. The core
`ms-markets` install does not require QuantLib.

See `examples/pricing/import_pricing_runtime.py` for the minimal optional
pricing import example.

## Scope

Pricing answers these questions:

- Which instrument terms are needed to rebuild a bond, swap, or position?
- Which curve and fixing data should be loaded for a valuation date?
- Which index UID is authoritative at runtime?
- Which QuantLib objects should be materialized for valuation?
- Which pricing details must be attached to assets for later reconstruction?

## Primary Modules

- `msm_pricing.instruments`: Pydantic wrappers for priceable instruments and
  positions.
- `msm_pricing.models`: QuantLib curve, index, bond, and swap helper functions.
- `msm_pricing.data_interface`: Main Sequence data reads for curves and fixings.
- `msm_pricing.interest_rates`: interest-rate ETL helpers for curves and fixing
  storage.
- `msm_pricing.streamlit`: form helpers for pricing UIs.
- `msm_pricing.settings` and `msm_pricing.utils`: runtime settings and shared
  date conversion utilities.

## Key Contracts

Pricing needs two explicit handshakes:

1. Market data must be registered and stored in the shapes expected by pricing.
2. Assets that need valuation must carry pricing details that rebuild instrument
   terms.

The runtime path should resolve the index UID, load curves and fixings,
materialize QuantLib objects, set an explicit valuation date, and price the
instrument or position.

## Extension Notes

Add new instruments under `msm_pricing.instruments`. Add reusable QuantLib
helpers under `msm_pricing.models`. Add storage-facing pricing data reads under
`msm_pricing.data_interface`. Add market-data publishing logic under
`msm_pricing.interest_rates`.

## Related Concepts

- [Assets](../assets/index.md)
- [Portfolios](../portfolios/index.md)
- [Client](../client/index.md)
