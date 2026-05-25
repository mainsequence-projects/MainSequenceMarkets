# `msm.pricing`

`msm.pricing` contains the QuantLib-backed pricing runtime for Main Sequence
Markets. It is the package for priceable instrument definitions, pricing model
helpers, market-data access used by pricing, and interest-rate curve/fixing
registration helpers.

The package intentionally stays inside `msm` so installed users import it as:

```python
import msm.pricing as pricing
from msm.pricing import FixedRateBond, FloatingRateBond, InterestRateSwap
from msm.pricing.models import get_index, register_index_spec
```

## Package Layout

```text
src/msm/pricing/
├── data_interface/      # Main Sequence market-data reads for curves/fixings
├── instruments/         # Pydantic wrappers for priceable instruments
├── interest_rates/      # ETL helpers for curves and fixing storage
├── models/              # QuantLib curve, index, bond, and swap helpers
├── streamlit/           # UI helpers for pricing forms
├── settings.py
└── utils.py
```

## Current Instrument Surface

The current package exports:

- `Instrument`
- `FixedRateBond`
- `CallableFixedRateBond`
- `AmortizingFixedRateBond`
- `ZeroCouponBond`
- `FloatingRateBond`
- `AmortizingFloatingRateBond`
- `InterestRateSwap`
- `Position`
- `PositionLine`

## Runtime Responsibilities

The pricing runtime expects two explicit handshakes:

1. Market data must be registered and stored in the expected shapes for curves
   and fixings.
2. Assets that need valuation must carry pricing details that can rebuild the
   instrument terms later.

At runtime, pricing code should resolve the pricing index UID, load the
corresponding curve/fixing data, materialize QuantLib objects, and value the
instrument or position for an explicit valuation date.

## Extending

Add new priceable instruments under `instruments/` and shared QuantLib helpers
under `models/`. Keep storage access in `data_interface/` or domain-specific ETL
packages so instrument classes remain focused on rebuilding terms and pricing.
