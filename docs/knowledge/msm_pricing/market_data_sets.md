# Market Data Sets

Pricing market-data sets are the first-class rows that tell the pricing runtime
where to read curve and fixing observations. They replace loose `context_key`
plus DataNode identifier strings with `PricingMarketDataSet` rows and
`PricingMarketDataSetBinding` concept bindings keyed by backend DataNode storage
table UID (see [ADR 0026](../../ADR/0026-explicit-pricing-market-data-sets.md)).

## The market-data set model

The DataNode locations used by the pricing engine are pricing market-data
bindings, not instrument metadata and not core `msm` MetaTables. Bindings are
vertical rows under first-class market-data sets so new pricing concepts can be
added without adding one column per future market-data source:

```text
PricingMarketDataSet
  set_key      = default | eod | live | risk_manager
  display_name
  status

PricingMarketDataSetBinding
  market_data_set_uid -> PricingMarketDataSet.uid
  concept_key         = discount_curves | interest_rate_index_fixings | equity_vol_curves
  data_node_uid       = backend DataNode storage table UID
  storage_table_identifier = optional diagnostic copy

PricingMarketDataSetCurveBinding
  market_data_set_uid -> PricingMarketDataSet.uid
  binding_key         = role:selector_type:selector_key:quote_side
  role_key            = discount | projection | forwarding | z_spread_base
  selector_type       = currency | index | global
  selector_key        = USD | <IndexTable.uid> | global
  curve_uid           -> CurveTable.uid
```

## The `data_node_uid` boundary

The important boundary is:

```text
data_node_uid
  authoritative pointer used by pricing runtime

storage_table_identifier
  optional diagnostic value for humans and logs
  not used to resolve pricing market data
```

## Built-in constants

The built-in pricing constants live in `msm_pricing.settings`:

```python
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_EQUITY_VOL_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_MARKET_DATA_SET_DEFAULT,
    PRICING_MARKET_DATA_SET_EOD,
    PRICING_MARKET_DATA_SET_LIVE,
    PRICING_MARKET_DATA_SET_RISK_MANAGER,
)
```

`interest_rate_index_fixings` is intentionally rate-specific. The current
`FixingRatesNode` stores a decimal `rate` column for SOFR, TIIE, IBOR,
overnight, and similar interest-rate indexes. Future equity index levels,
inflation observations, or volatility inputs should use their own concept keys.

## Default-binding seeding

Fresh pricing bootstrap seeds the default bindings:

```text
PricingMarketDataSet(set_key="default")
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
       data_node_uid = DiscountCurvesStorage.get_meta_table_uid()

  -> PricingMarketDataSetBinding(concept_key="interest_rate_index_fixings")
       data_node_uid = IndexFixingsStorage.get_meta_table_uid()
```

Those UIDs are read from the attached backend `TimeIndexMetaTable` objects. They
are not rebuilt from authored names such as `DiscountCurvesTS` or from namespace
helpers. The optional `storage_table_identifier` is diagnostic metadata only.

Deployments can add or replace market-data sets for `eod`, `live`,
`risk_manager`, or other application workflows:

```python
from msm_pricing.bootstrap import attach_pricing_schemas
from msm_pricing.api import PricingMarketDataSet, PricingMarketDataSetBinding
from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_MARKET_DATA_SET_EOD,
)

attach_pricing_schemas(seed_default_market_data_bindings=True)

market_data_set = PricingMarketDataSet.upsert(
    set_key=PRICING_MARKET_DATA_SET_EOD,
    display_name="EOD pricing market data",
)
PricingMarketDataSetBinding.upsert(
    market_data_set_uid=market_data_set.uid,
    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
    data_node_uid=DiscountCurvesStorage.get_meta_table_uid(),
    storage_table_identifier=DiscountCurvesStorage.get_identifier(),
)
```

## Selecting Curve Identity

`PricingMarketDataSetBinding` answers where to read a concept from. It does not
answer which curve inside that storage should be used. A discount-curve storage
table can contain many `curve_identifier` values.

Use `PricingMarketDataSetCurveBinding.upsert_index_curve_selection(...)` to
select curve identity for an index-scoped valuation role:

```python
from msm_pricing.api import PricingMarketDataSetCurveBinding

PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="projection",
    index_uid=index.uid,
    quote_side="mid",
    curve_uid=curve.uid,
)
```

The helper writes the generic `PricingMarketDataSetCurveBinding` row with
`selector_type="index"` and `selector_key=str(index.uid)` internally. Normal
index-based workflows should not pass those selector fields directly. Use the
raw `upsert(...)` method only for generic selectors such as currency, future
asset-scoped selectors, volatility surfaces, or other policy dimensions.

Benchmark analytics use the same binding table. A bond's
`benchmark_rate_index_uid` selects the index identity only; z-spread resolves
the curve from a `z_spread_base` binding:

```python
PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="z_spread_base",
    index_uid=benchmark_index.uid,
    quote_side="mid",
    curve_uid=benchmark_curve.uid,
)

spread = bond.z_spread(
    target_dirty_ccy=101.25,
    market_data_set=market_data_set.set_key,
    benchmark_curve_quote_side="mid",
)
```

There is no implicit `mid` fallback. A binding written with `quote_side="mid"`
is looked up only when the runtime request also carries `quote_side="mid"`.
Use `quote_side=None` when the binding should be the default side for that
market-data set and role.

## Selecting a market-data set

Runtime resolution checks direct in-memory UID overrides first, then the
persisted binding row for `(market_data_set_uid, concept_key)`. The final read
always uses `APIDataNode.build_from_table_uid(...)`.

Curve consumers that need the latest available curve snapshot for one curve
identity should use `MSDataInterface.get_latest_discount_curve(...)` instead of
setting a process-wide fallback environment variable:

```python
from msm_pricing.data_interface import MSDataInterface

interface = MSDataInterface()
nodes, effective_date = interface.get_latest_discount_curve(
    curve.unique_identifier,
    market_data_set="eod",
)
```

Instrument pricing chooses the set explicitly when the caller needs more than
one source set in the same process:

```python
bond.price(market_data_set="eod")
bond.price(market_data_set="live")
```

When `market_data_set` is omitted, pricing uses the process-wide default
configuration, whose default selector is `default`.

Transient basket valuation uses `ValuationPosition`. It applies one valuation
date and market-data set to every instrument, scales prices and cashflows by
line units, and does not persist a pricing `PositionTable`:

```python
from msm_pricing.valuation import ValuationLine, ValuationPosition

position = ValuationPosition(
    valuation_date=valuation_date,
    market_data_set="eod",
    lines=[ValuationLine(instrument=bond, units=25.0, asset_uid=asset.uid)],
)
value = position.price()
breakdown = position.price_breakdown()
```

`ValuationLine` and `ValuationPosition` are documented in full under
[Instruments](instruments.md).

## Related Concepts

- [msm_pricing overview](index.md)
- [Instruments](instruments.md)
- [Curves](curves.md)
- [Fixings](fixings.md)
- [Runtime Resolution](runtime_resolution.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
