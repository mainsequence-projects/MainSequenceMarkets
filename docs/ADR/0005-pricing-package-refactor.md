# 0005. Pricing Package Refactor

## Status

Accepted, amended to remove pricing from the core `msm` import package.

## Context

The migrated SDK package originally exposed pricing-related code under:

```text
msm.instruments
```

That package contained more than instrument definitions. It also contained
pricing models, curve/index registration, market-data interfaces, interest-rate
ETL helpers, and QuantLib codecs.

The old nested path also produced awkward imports such as:

```python
from msm.instruments.instruments import FixedRateBond
from msm.instruments.pricing_models import get_index
```

## Decision

Rename the package to a separate import root:

```text
msm_pricing
```

Use these subpackages:

```text
msm_pricing.instruments
msm_pricing.models
msm_pricing.pricing_engine
msm_pricing.data_interface
msm_pricing.data_nodes
```

The old `pricing_models` package is renamed to `pricing_engine`. The
`msm_pricing.models` package follows the same convention as core `msm.models`
and is reserved for SQLAlchemy MetaTable declarations.

The old nested `instruments/instruments` package is lifted to
`pricing/instruments`.

## Consequences

Public imports should use `msm_pricing`. No compatibility module for the old
import root is kept; pricing is intentionally outside core `msm`.

Examples:

```python
from msm_pricing.instruments import FixedRateBond
from msm_pricing.pricing_engine import get_index
```

The optional dependency extra is renamed from `instruments` to `pricing`.
Core `ms-markets` does not depend on QuantLib; users install
`ms-markets[pricing]` when they need pricing capabilities. Streamlit pricing
form helpers were later removed from `msm_pricing`; UI surfaces should live in
application packages instead of the pricing runtime package.
