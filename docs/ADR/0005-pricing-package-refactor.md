# 0005. Pricing Package Refactor

## Status

Accepted

## Context

The migrated SDK package originally exposed pricing-related code under:

```text
msm.instruments
```

That package contained more than instrument definitions. It also contained
pricing models, curve/index registration, market-data interfaces, interest-rate
ETL helpers, QuantLib codecs, and Streamlit pricing forms.

The old nested path also produced awkward imports such as:

```python
from msm.instruments.instruments import FixedRateBond
from msm.instruments.pricing_models import get_index
```

## Decision

Rename the package to:

```text
msm.pricing
```

Use these subpackages:

```text
msm.pricing.instruments
msm.pricing.models
msm.pricing.data_interface
msm.pricing.interest_rates
msm.pricing.streamlit
```

The old `pricing_models` package is renamed to `models`.

The old nested `instruments/instruments` package is lifted to
`pricing/instruments`.

## Consequences

Public imports should use `msm.pricing`.

Examples:

```python
from msm.pricing.instruments import FixedRateBond
from msm.pricing.models import get_index
```

The optional dependency extras are renamed from `instruments` to `pricing`, and
from `instruments-streamlit` to `pricing-streamlit`.
