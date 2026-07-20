# Curves

This page covers the pricing concepts that reconstruct discounting and
projection curves: index conventions (`IndexConventionDetailsTable`) for
QuantLib index/fixing mechanics, curve rows (`CurveTable`), curve build details
(`CurveBuildingDetailsTable`), market-data-set curve bindings, and timestamped
curve observations (`DiscountCurvesNode`).

## Index Conventions

Instruments reference canonical indexes by backend UUID fields such as
`floating_rate_index_uid`, `benchmark_rate_index_uid`, or `float_leg_index_uid`.
They do not store string names.

`IndexTable` is core market reference data. For fixed income, first register
the `interest_rate` type through `IndexType`, then create the index row:

```python
from msm.api.indices import Index, IndexType
from msm.constants import (
    INDEX_TYPE_INTEREST_RATE,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)

IndexType.upsert(**INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload())
index = Index.upsert(
    unique_identifier="USD-SOFR-3M",
    index_type=INDEX_TYPE_INTEREST_RATE,
    display_name="USD SOFR 3M",
)
```

Pricing-specific index mechanics live in `IndexConventionDetailsTable`:

```text
+-----------------------------+        one-to-one extension     +-------------------------------+
| IndexTable                  |-------------------------------->| IndexConventionDetails        |
|-----------------------------|        index_uid PK/FK          |-------------------------------|
| uid                  PK     |                                 | index_uid              PK/FK  |
| unique_identifier    unique |                                 | index_family                  |
| index_type                  |                                 | convention_dump               |
| display_name                |                                 | serialization_format          |
| provider                    |                                 | source                        |
| metadata                    |                                 | metadata                      |
+-----------------------------+                                 +-------------------------------+
```

`IndexConventionDetailsTable` stores index reconstruction mechanics:

- index family, such as `ibor` or `overnight`;
- currency code;
- tenor or period;
- fixing calendar;
- day counter;
- settlement days;
- business-day convention;
- end-of-month behavior;
- optional fixing identity override.

It does not store curve selection and it does not belong in core `msm.models`.

```python
from msm_pricing.api import IndexConventionDetails

IndexConventionDetails.upsert(
    index_uid=index.uid,
    index_family="ibor",
    convention_dump={
        "currency_code": "USD",
        "day_counter_code": "Actual360",
        "fixing_calendar_code": "US",
        "period": "3M",
        "settlement_days": 2,
        "business_day_convention": "ModifiedFollowing",
        "end_of_month": False,
        "fixings_unique_identifier": index.unique_identifier,
    },
    source="example",
)
```

## Curves

Curves are pricing concepts. They are not assets and do not reference
`AssetTable`.

`CurveTable` is a pricing-owned MetaTable with its own `uid` and
`unique_identifier`. It is the curve registry. It does not need to belong to an
index and it has no index ownership field. Runtime selection uses explicit
market-data-set curve bindings.

```text
+-----------------------------+        build spec keyed by        +-----------------------------+
| CurveTable                  |<--------------------------------| CurveBuildingDetailsTable   |
|-----------------------------|        curve_uid                |-----------------------------|
| uid                  PK     |                                 | curve_uid            PK/FK  |
| unique_identifier    unique |                                 | builder_type                |
| display_name                |                                 | quote_convention            |
| curve_type                  |                                 | day_counter_code            |
| currency_code               |                                 | calendar_code               |
| quote_side                  |                                 | interpolation_method        |
| source                      |                                 | compounding                 |
| status                      |                                 | extrapolation_policy        |
| metadata                    |                                 | metadata                    |
+-----------------------------+                                 +-----------------------------+
```

Curve identity rules:

- `CurveTable.uid` is the canonical row identity for MetaTable operations.
- `CurveTable.unique_identifier` is the stable curve row key. Curve DataNode
  storage publishes that value in the `curve_identifier` column.
- Bulk latest-as-of reads for multiple curve identifiers are executed by the
  backend against `DiscountCurvesStorage` with one ranked row per
  `curve_identifier`; callers should not materialize full historical ranges
  just to find the latest row.
- `CurveBuildingDetailsTable.curve_uid` stores how observations are turned into
  a QuantLib term structure.
- `PricingMarketDataSetCurveBindingTable` stores valuation-policy selection:
  `market_data_set_uid + role_key + selector_type + selector_key + quote_side`
  resolves to `curve_uid`.
- `curve_uid` is not unique in `PricingMarketDataSetCurveBindingTable`. A curve
  can be selected by many market-data-set roles, selector types, index UIDs,
  quote sides, or source sets. The curve row is the target of selection, not the
  owner of the selector.
- `IndexConventionDetailsTable` is only for rebuilding QuantLib indexes and
  fixings. It is not the source of truth for curve construction.
- Do not encode curve selection as an index relationship. Market-data sets may
  choose different bid/mid/offer, source, scenario, discount, projection,
  spread, basis, or future volatility curves.

### Native curve construction methods

Runtime curve construction honors `CurveBuildingDetails.interpolation_method`;
it does not silently coerce every curve into log-linear discount space.
Supported methods are intentionally limited to non-deprecated QuantLib
constructors:

```text
log_linear_discount -> ql.DiscountCurve
log_cubic_discount  -> ql.LogCubicDiscountCurve
linear_zero         -> ql.ZeroCurve with ql.Linear()
cubic_zero          -> ql.NaturalCubicZeroCurve with ql.SplineCubic()
natural_cubic_zero  -> ql.NaturalCubicZeroCurve with ql.SplineCubic()
monotone_cubic_zero -> ql.MonotonicCubicZeroCurve with ql.MonotonicCubic()
linear_forward      -> ql.LinearForwardCurve, only for forward_rate quotes
```

Zero-rate discount-space methods convert stored zero rates into discount
factors with `ql.InterestRate(...).discountFactor(...)`. Zero-space methods
pass zero rates to the QuantLib zero-curve constructor with the declared
compounding and frequency. `rate_unit` parsing is the only local scaling step.

Deprecated QuantLib methods are rejected instead of aliased. Do not persist
`log_linear_zero`, `LogLinearZeroCurve`, `monotonic_log_cubic_discount`, or
`MonotonicLogCubicDiscountCurve` as curve build methods.

### Helper-based curve reconstruction

Some curves are not best represented as direct zero or forward nodes at the
source boundary. When the source inputs are helper-style instruments, use the
generic reconstruction machinery under
`msm_pricing.pricing_engine.curves`.

The primitive API is QuantLib-first and has no MetaTable, DataNode, connector,
vendor, currency, or index-name dependency:

```python
import QuantLib as ql

from msm_pricing.pricing_engine.curves import (
    CurveObservationExportConfig,
    FixedRateBondHelperSpec,
    InterestRateFutureHelperSpec,
    OISRateHelperSpec,
    OvernightDepositHelperSpec,
    StaticRateHelperRuntimeResolver,
    ZeroCouponBondHelperSpec,
    export_curve_observation_nodes,
    reconstruct_curve_handle_from_helper_specs,
    reconstruct_curve_result_from_key_nodes,
    reconstruct_curve_term_structure_from_helper_specs,
)

handle = reconstruct_curve_handle_from_helper_specs(
    (
        OvernightDepositHelperSpec(quote=0.0475, tenor="1D"),
        InterestRateFutureHelperSpec(
            quote=95.25,
            reference_month="JUN",
            reference_year=2026,
            reference_frequency="Monthly",
        ),
        OISRateHelperSpec(
            quote=0.0480,
            tenor="1Y",
            settlement_days=2,
            overnight_index=ql.Sofr(),
            payment_convention="ModifiedFollowing",
            payment_frequency="Annual",
            payment_calendar=ql.TARGET(),
            fixed_payment_frequency="Annual",
            fixed_calendar=ql.TARGET(),
            averaging_method="Compound",
        ),
    ),
    valuation_date=valuation_date,
    day_counter=ql.Actual360(),
)
nodes = export_curve_observation_nodes(
    handle,
    valuation_date=valuation_date,
    node_days=[7, 30, 90, 180, 365],
)

bond_handle = reconstruct_curve_handle_from_helper_specs(
    (
        ZeroCouponBondHelperSpec(
            quote=97.5,
            quote_type="clean_price",
            quote_unit="price_per_100",
            settlement_days=0,
            face_value=100.0,
            maturity_date="2026-07-02",
            issue_date="2026-01-02",
        ),
        FixedRateBondHelperSpec(
            quote=99.0,
            quote_type="clean_price",
            quote_unit="price_per_100",
            coupon_rate=0.05,
            issue_date="2026-01-02",
            maturity_date="2027-01-02",
            tenor="6M",
            settlement_days=0,
            face_value=100.0,
            day_counter=ql.Actual360(),
        ),
    ),
    valuation_date=valuation_date,
    day_counter=ql.Actual360(),
)
bond_nodes = export_curve_observation_nodes(
    bond_handle,
    valuation_date=valuation_date,
    node_days=[181, 365],
)

collateral_handle = ql.YieldTermStructureHandle(
    ql.FlatForward(ql.Date(2, 1, 2026), 0.03, ql.Actual360())
)
resolver = StaticRateHelperRuntimeResolver(
    yield_curves={"GENERIC-COLLATERAL": collateral_handle},
    indexes={
        "BASE-OVERNIGHT": ql.OvernightIndex(
            "BASE-ON", 0, ql.USDCurrency(), ql.TARGET(), ql.Actual360(), collateral_handle
        ),
        "QUOTE-OVERNIGHT": ql.OvernightIndex(
            "QUOTE-ON", 0, ql.EURCurrency(), ql.TARGET(), ql.Actual360(), collateral_handle
        ),
    },
)
xccy_result = reconstruct_curve_result_from_key_nodes(
    cross_currency_key_nodes,
    valuation_date=valuation_date,
    day_counter=ql.Actual360(),
    helper_runtime_resolver=resolver,
)
```

In this example, `cross_currency_key_nodes` is a `rate_helpers@v1` payload with
generic context/provenance nodes plus helper nodes, as shown later in this
section.

For helper-built curves that must be exported back into resolver-compatible
curve observations, derive the export convention from `CurveBuildingDetails`
instead of hardcoding it beside the connector. Use the term-structure
reconstruction primitive when exporting QuantLib pillar dates; handles are the
right output for pricing but may not expose `dates()` through every QuantLib
Python binding. The exporter supports pillar dates plus explicit front nodes:

```python
term_structure = reconstruct_curve_term_structure_from_helper_specs(
    helper_specs,
    valuation_date=valuation_date,
    day_counter=ql.Actual360(),
)
export_config = CurveObservationExportConfig.from_curve_building_details(
    curve_building_details
)
nodes = export_curve_observation_nodes(
    term_structure,
    valuation_date=valuation_date,
    node_days=[1],
    include_pillar_dates=True,
    config=export_config,
)
```

If the persisted build details use source-helper placeholders such as
`quote_convention="helper_quote"` or `rate_unit="helper_unit"`, the
`builder_payload` must include explicit output keys such as
`output_quote_convention="zero_rate"` and `output_rate_unit="decimal"`. Export
compounding comes from the normal build-detail fields, so compounded annual
zero output is represented by
`compounding="compounded_annual"`.

The persistence adapter is narrower. Persisted helper curves use
`CurveBuildingDetails.builder_type="rate_helper_curve"` and publish generic
helper-shaped dictionaries in `DiscountCurvesNode.key_nodes`. The adapter reads
the build details, requires `builder_payload.helper_schema="rate_helpers@v1"`,
converts key nodes into runtime helper specs, builds QuantLib rate helpers, and
delegates to `reconstruct_curve_handle(...)`.

`rate_helpers@v1` is the canonical helper schema. It supports helper nodes and
generic context/provenance nodes that are needed to build those helpers.
Supported helper key-node types include:

```json
[
  {
    "source_reference": {
      "type": "index",
      "identifier": "USD-OVERNIGHT-DEPOSIT-1D"
    },
    "helper_type": "overnight_deposit_helper",
    "quote": 4.75,
    "quote_type": "deposit_rate",
    "quote_unit": "percent",
    "tenor": "1D",
    "fixing_days": 0,
    "calendar_code": "TARGET",
    "business_day_convention": "Following",
    "day_counter_code": "Actual360"
  },
  {
    "source_reference": {
      "type": "index",
      "identifier": "USD-OVERNIGHT-OIS-1Y"
    },
    "helper_type": "ois_rate_helper",
    "quote": 4.80,
    "quote_type": "par_swap_rate",
    "quote_unit": "percent",
    "tenor": "1Y",
    "settlement_days": 2,
    "floating_index": "USD-OVERNIGHT",
    "payment_convention": "ModifiedFollowing",
    "payment_frequency": "Annual",
    "payment_calendar_code": "TARGET",
    "fixed_payment_frequency": "Annual",
    "fixed_calendar_code": "TARGET",
    "averaging_method": "Compound"
  },
  {
    "source_reference": {
      "type": "index",
      "identifier": "CME-SOFR-JUN-2026"
    },
    "helper_type": "sofr_future_rate_helper",
    "quote": 95.25,
    "quote_type": "futures_price",
    "quote_unit": "price",
    "reference_month": "JUN",
    "reference_year": 2026,
    "reference_frequency": "Monthly",
    "convexity_adjustment": 0.0
  },
  {
    "source_reference": {
      "type": "asset",
      "identifier": "EXAMPLE-ZERO-COUPON-BOND-2026"
    },
    "helper_type": "zero_coupon_bond_helper",
    "quote": 97.5,
    "quote_type": "clean_price",
    "quote_unit": "price_per_100",
    "maturity_date": "2026-07-02",
    "issue_date": "2026-01-02",
    "settlement_days": 0,
    "calendar_code": "TARGET",
    "face_value": 100.0
  },
  {
    "source_reference": {
      "type": "asset",
      "identifier": "EXAMPLE-FIXED-RATE-BOND-2027"
    },
    "helper_type": "fixed_rate_bond_helper",
    "quote": 99.0,
    "quote_type": "clean_price",
    "quote_unit": "price_per_100",
    "coupon_rate": 0.05,
    "issue_date": "2026-01-02",
    "maturity_date": "2027-01-02",
    "tenor": "6M",
    "settlement_days": 0,
    "calendar_code": "TARGET",
    "face_value": 100.0,
    "day_counter_code": "Actual360"
  }
]
```

Every typed fixed-income helper key node inherits `FixedIncomeCurveKeyNode`.
Its `source_reference` is independent of helper construction: bonds can point
to `AssetTable.unique_identifier`, while deposit, swap, futures, FX, and basis
quotes can point to `IndexTable.unique_identifier`. Helper-specific fields stay
on their discriminated model, so a futures helper does not carry OIS fields.
The old top-level `asset_identifier` and `index_identifier` forms are rejected.

The same `rate_helpers@v1` reconstruction path accepts context nodes. It does
not introduce a new schema, builder type, or bootstrap path. The first context
node is `helper_type="fx_spot"`, which supplies construction provenance for FX
swap helpers but is not itself a QuantLib `RateHelper`.

```json
[
  {
    "helper_type": "fx_spot",
    "quote": 1.1,
    "quote_type": "fx_spot",
    "quote_unit": "quote_per_base",
    "fx_pair": "BASE/QUOTE",
    "fx_base_currency": "BASE",
    "fx_quote_currency": "QUOTE"
  },
  {
    "helper_type": "fx_swap_rate_helper",
    "quote": 0.001,
    "quote_type": "fx_forward_points",
    "quote_unit": "quote_per_base",
    "tenor": "1M",
    "fixing_days": 2,
    "calendar_code": "TARGET",
    "business_day_convention": "ModifiedFollowing",
    "end_of_month": false,
    "fx_pair": "BASE/QUOTE",
    "fx_base_currency": "BASE",
    "fx_quote_currency": "QUOTE",
    "is_fx_base_currency_collateral_currency": true,
    "collateral_curve": "GENERIC-COLLATERAL"
  },
  {
    "helper_type": "const_notional_cross_currency_basis_swap_rate_helper",
    "quote": 1.0,
    "quote_type": "basis_spread",
    "quote_unit": "basis_points",
    "tenor": "1Y",
    "fixing_days": 2,
    "calendar_code": "TARGET",
    "business_day_convention": "ModifiedFollowing",
    "end_of_month": false,
    "base_currency_index": "BASE-OVERNIGHT",
    "quote_currency_index": "QUOTE-OVERNIGHT",
    "collateral_curve": "GENERIC-COLLATERAL",
    "is_fx_base_currency_collateral_currency": true,
    "is_basis_on_fx_base_currency_leg": true,
    "payment_frequency": "Annual"
  }
]
```

OIS key nodes require the caller to supply a QuantLib overnight index or a
resolver callable at runtime. `msm_pricing` does not infer an index from curve
names, currencies, vendors, or local product names. Source-specific file
parsing, fallback quote units, and source identifier repairs belong in the
connector or publisher before data becomes generic helper key nodes.

The OIS spec exposes the generic QuantLib OIS schedule/convention surface,
including payment lag, payment convention, payment frequency/calendar,
forward-start period, overnight spread, pillar choice, averaging method,
end-of-month flag, fixed-leg frequency/calendar, and observation-shift fields.
Those fields exist for parity with market conventions; callers should pass
them explicitly when the source curve depends on them instead of rebuilding
curves through connector-local helper constructors.

Interest-rate future helpers consume futures prices, not rates. Future key
nodes therefore require `quote_type="futures_price"` and `quote_unit="price"`.
The v1 schema supports `helper_type="sofr_future_rate_helper"` through the
generic `InterestRateFutureHelperSpec` with explicit reference month, year,
frequency, convexity adjustment, pillar choice, and custom pillar date fields.
Source-specific contract-code parsing stays in the connector or publisher that
creates the generic key node.

Bond helpers consume clean or dirty prices, not rates. The v1 schema supports
`helper_type="zero_coupon_bond_helper"` and
`helper_type="fixed_rate_bond_helper"` with explicit `quote_type`,
`quote_unit`, face value, dates, calendars, day counters, and schedule fields.
Generic price units are `price`, `price_per_face`, and `price_per_100`.
Source-specific scales must be normalized by the connector before publication.
Fixed-rate helpers can use `tenor`, `coupon_period_days`, `coupon_frequency`,
explicit `schedule_dates`, or a serialized `schedule`. These helpers are still
QuantLib `RateHelper` objects, so they use the same
`builder_type="rate_helper_curve"` and `helper_schema="rate_helpers@v1"`
adapter as OIS, deposit, and futures helpers.

Cross-currency helpers still use `helper_schema="rate_helpers@v1"` even though
they mix helper nodes and context nodes. FX forward points use explicit
`quote_type="fx_forward_points"` and are not normalized as rates. Raw
point/pip source quotes require a `point_scale`; already normalized FX-pair
units are consumed directly. Constant-notional cross-currency basis helpers use
`quote_type="basis_spread"` and accept explicit decimal, percent, or basis
point units. Collateral curves and base/quote currency indexes are resolved by
a `RateHelperRuntimeResolver`; the static mapping resolver is useful for
offline examples and connector-owned tests, while application/runtime adapters
can resolve those identifiers from their prepared curve/index context.
`reconstruct_curve_result_from_key_nodes(...)` returns the term structure,
built helpers, parsed specs, context nodes, and captured helper quote errors
for diagnostics.

Observation export is also generic. `export_curve_observation_nodes(...)`
exports resolver-compatible nodes from a QuantLib handle or term structure on
an explicit `node_days` grid, or from pillar dates when the submitted QuantLib
object exposes them. `zero_rate` is the initial exported quote convention;
future curve families should add quote conventions to the exporter rather than
forking product-specific export functions.

```python
from msm_pricing.api import Curve, CurveBuildingDetails, PricingMarketDataSetCurveBinding

curve = Curve.upsert(
    unique_identifier="USD-SOFR-3M-PROJECTION",
    display_name="USD SOFR 3M Projection Curve",
    curve_type="projection",
    currency_code="USD",
    quote_side="mid",
    source="example",
)
CurveBuildingDetails.upsert(
    curve_uid=curve.uid,
    builder_type="zero_rate_curve",
    quote_convention="zero_rate",
    rate_unit="decimal",
    day_counter_code="Actual360",
    calendar_code="TARGET",
    interpolation_method="log_linear_discount",
    compounding="simple",
    extrapolation_policy="enabled",
)
PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="projection",
    index_uid=index.uid,
    quote_side="mid",
    curve_uid=curve.uid,
)
```

For benchmark z-spread analytics, bind the benchmark index UID with the
`z_spread_base` role. The curve row may still have `curve_type="discount"` or
another physical curve type; the role describes why the curve is selected.

```python
benchmark_curve = Curve.upsert(
    unique_identifier="USD-SOFR-ZSPREAD-BASE",
    display_name="USD SOFR Z-Spread Base Curve",
    curve_type="discount",
    currency_code="USD",
    source="example",
)
CurveBuildingDetails.upsert(
    curve_uid=benchmark_curve.uid,
    builder_type="zero_rate_curve",
    quote_convention="zero_rate",
    rate_unit="decimal",
    day_counter_code="Actual360",
    calendar_code="TARGET",
    interpolation_method="log_linear_discount",
    compounding="simple",
    extrapolation_policy="enabled",
)
PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="z_spread_base",
    index_uid=benchmark_index.uid,
    quote_side=None,
    curve_uid=benchmark_curve.uid,
)
```

The instrument then stores only `benchmark_rate_index_uid=benchmark_index.uid`.
At runtime, `z_spread(...)` resolves the curve through the index curve
selection above. The helper writes `selector_type="index"` and
`selector_key=str(benchmark_index.uid)` into the generic binding table
internally; callers should not pass those selector fields in normal
index-based workflows.

When an observed z-spread should be applied back to a curve handle for scenario
or line valuation, keep that as derived runtime state:

```python
from msm_pricing.pricing_engine import apply_z_spread_to_curve

spreaded_curve = apply_z_spread_to_curve(base_curve_handle, z_spread_decimal)
```

The helper expects the decimal spread returned by `Bond.z_spread(...)`, quoted
as a continuous zero-rate spread. It does not change the persisted curve nodes,
`key_nodes`, `CurveTable`, or `CurveBuildingDetails`.

## Curve Scenarios

Curve scenarios live under `msm_pricing.scenarios.curves`. They shock curves by
`Curve.unique_identifier`, not by backend curve UID, index UID, role key, quote
side, or provider-local curve name. A curve that is selected by several roles
or lines is rebuilt once for the scenario and reused wherever that same curve
identity is resolved.

```python
from msm_pricing.scenarios.curves import CurveBumpSpec, CurveScenario

scenario = CurveScenario(
    name="parallel-up-25bp",
    shocks_by_curve_identifier={
        "USD-SOFR-3M-PROJECTION": CurveBumpSpec(parallel_bp=25.0),
    },
)
```

`CurveBumpSpec` supports:

- `parallel_bp`: a basis-point shift applied to every usable source key-node
  rate or yield;
- `keyrate_bp`: tenor labels such as `"3M"` or positive day counts mapped to
  basis-point shifts; key-rate values are linearly interpolated and flat
  extrapolated;
- `metadata_json`: caller-owned scenario metadata.

The bump helpers operate on copied `key_nodes` dictionaries. They never mutate
the submitted observation, the persisted `DiscountCurvesNode` row, or the
prepared valuation context. Supported key-node rate sources are:

- `yield` or `yield_value` with an explicit decimal or percent unit;
- rate-like `quote` values when `quote_type` is a rate convention such as
  `zero_rate`, `forward_rate`, `par_rate`, or `swap_rate`;
- `implied_rate` with an explicit decimal or percent unit.

Unsupported source quote conversions, such as `clean_price` or
`price_per_100` to a rate, stay outside core `msm_pricing`. Those conversions
depend on vendor/source interpretation and belong in the producer or connector
adapter that understands the source instrument.

Scenario runtime nodes are built from the bumped key nodes and the runtime
`CurveBuildingDetails` output convention:

```text
quote_convention = zero_rate    -> {"days_to_maturity": ..., "zero": ...}
quote_convention = forward_rate -> {"days_to_maturity": ..., "forward": ...}
```

If persisted build details use source placeholders such as
`quote_convention="key_node_quote"` or `rate_unit="key_node_unit"`, the
`builder_payload` must explicitly declare the runtime output convention and
unit. The scenario helper fails instead of guessing.

Connector-specific curve rebuilds remain connector-owned when they interpret
source files, source identifiers, or vendor quote policy. Once a connector has
generic helper key nodes, `builder_type="rate_helper_curve"` can be shocked and
rebuilt by core `msm_pricing` without importing connector code. OIS helper
curves still need a QuantLib overnight index at runtime; callers can pass
`overnight_index` or `overnight_index_resolver` to
`price_curve_scenario(...)`, and the high-level scenario loop forwards that
resolver to `build_scenario_curve_handle(...)`. Cross-currency helper curves
also need `helper_runtime_resolver` so copied scenario key nodes can resolve
collateral curves and base/quote currency indexes while staying on the generic
helper-reconstruction path. If a connector needs source-only interpretation
before generic helper key nodes exist, it can build connector-owned scenario
handles and then call lower-level pricing helpers.
For bond helper curves, no-op scenario reconstruction is supported, but
non-empty yield shocks on price-quoted bond helpers raise a diagnostic until
generic yield-to-price conversion is implemented with explicit bond
conventions. The scenario engine does not bump a stored clean or dirty price as
though it were a rate.

When the caller already has exact base and scenario curve handles, use
`price_resolved_curve_scenario(...)` instead of rebuilding handles from
`key_nodes`. That workflow accepts typed `LineCurveResolution` records, applies
the same deterministic line-role selection and observed z-spread overlays, and
returns the same `CurveScenarioResult` shape as `price_curve_scenario(...)`.
`CurveScenarioResult` also exposes the selected
`base_curve_handles_by_line` and `scenario_curve_handles_by_line` maps so
callers can reuse the exact scenario handles for local analytics or reporting
without duplicating curve-selection logic.
For broader dashboard or API workflows that need base valuation, multiple
scenario runs, partial-success line diagnostics, analytics, cashflows, carry
impacts, and observed dirty-price z-spread overlay records, use
`msm_pricing.scenarios.valuation.run_valuation_scenario_workflow(...)`. That
valuation workflow delegates its curve runtime override preparation back to
`msm_pricing.scenarios.curves`; it does not duplicate curve construction.
See [Curve Scenarios](scenarios/curves.md),
[Valuation Scenario Workflow](scenarios/valuation.md), and
`examples/msm_pricing/resolved_curve_scenario.py`.

## Curve Observations

`DiscountCurvesNode` publishes timestamped curve observations. Its storage key
is `CurveTable.unique_identifier`, exposed on the DataNode row as
`curve_identifier`.

```text
+-----------------------------+        observations keyed by      +-----------------------------+
| CurveTable                  |<--------------------------------| DiscountCurvesNode          |
|-----------------------------|        curve_identifier          |-----------------------------|
| uid                  PK     |                                  | time_index                  |
| unique_identifier    unique |                                  | curve_identifier            |
| curve_type                  |                                  | curve                       |
| currency_code               |                                  | key_nodes                   |
|                             |                                  | metadata_json               |
|                             |                                  +-----------------------------+
+-----------------------------+
```

The curve DataNode contract is:

```text
DiscountCurvesNode
  index:   (time_index, curve_identifier)
  cadence: 1d
  columns: curve, key_nodes, metadata_json
  FK:      curve_identifier -> CurveTable.unique_identifier
```

`curve` is required. It remains the serialized compressed pricing payload
consumed by runtime valuation. It stores the constructed curve nodes keyed by
days to maturity; the quote meaning comes from
`CurveBuildingDetails.quote_convention`, `rate_unit`, `compounding`, and the
related build fields. Do not normalize curve points into a different row grain
without a separate decision.

`key_nodes` records the input quotes used to build that specific curve
observation. It is row-level construction provenance, not another convention
source. Publishers pass producer-owned JSON that satisfies the base contract
below; the DataNode compresses that JSON into the storage column, and read/API
helpers return it decompressed. `msm_pricing.data_nodes.CurveKeyNode` is the
recommended helper when the standard fields fit the source:

```json
[
  {
    "maturity_date": "2031-05-27",
    "source_reference": {
      "type": "asset",
      "identifier": "EXAMPLE_BOND_2031"
    },
    "instrument_type": "fixed_rate_bond",
    "quote": 99.25,
    "quote_type": "clean_price",
    "quote_unit": "price_per_100",
    "quote_side": "mid"
  },
  {
    "maturity_date": "2027-05-27",
    "instrument_type": "direct_zero_rate",
    "quote": 0.105,
    "quote_type": "zero_rate",
    "quote_unit": "decimal",
    "quote_side": "mid",
    "yield": 0.105
  }
]
```

Rules:

- Publisher `key_nodes` values must be JSON object/list provenance with
  JSON-serializable nested values. They are stored as compressed text and
  returned by helpers as decompressed JSON.
- The shared storage layer does not enforce one fixed per-node financial schema
  because mixed curves may combine bonds, zero-coupon instruments, swaps,
  deposits, direct zero rates, and source-specific payloads.
- Prefer the standard fields `source_reference`, `maturity_date`,
  `instrument_type`, `quote`, `quote_type`, `quote_unit`, and `quote_side` when
  they fit the source. Discount-curve producers that think in yields may also
  include the optional `yield` field.
- `source_reference.type="asset"` selects an `AssetTable.unique_identifier`;
  `source_reference.type="index"` selects an `IndexTable.unique_identifier`.
  This is quote provenance and does not create curve ownership or select a
  projection/discount valuation role.
- Source publishers that need more structure should encode that structure in
  their own `CurveKeyNode`-compatible extensions or enforce it through
  `normalize_key_nodes(...)` / `set_key_nodes_validator(...)`.
- `quote_type` and `quote_unit` describe the raw source input for that key node.
  `CurveBuildingDetails` still describes how the final stored `curve` is built
  and interpreted by pricing.

When a producer needs stricter source-specific validation, extend the DataNode
validator instead of tightening the shared storage contract. The base
`DiscountCurvesNode` calls `normalize_key_nodes(...)` for each row after
storage-level JSON normalization. Subclass it for source-owned rules:

```python
from msm_pricing.data_nodes import CurveKeyNode, DiscountCurvesNode


class SourceDiscountCurvesNode(DiscountCurvesNode):
    def normalize_key_nodes(self, value, *, row, curve_identifier):
        nodes = super().normalize_key_nodes(
            value,
            row=row,
            curve_identifier=curve_identifier,
        )
        return [
            CurveKeyNode.model_validate(node).model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
            )
            for node in nodes
        ]
```

For runtime composition, attach a callable with
`node.set_key_nodes_validator(...)`. The callable receives the normalized
`value`, the full row, and the `curve_identifier`, and must return JSON
object/list provenance. Do not put validator callables in `CurveConfig`; they
are execution behavior, not hashed dataset identity.

A `DiscountCurvesNode` publisher passes the values as ordinary DataFrame
columns. Keep `key_nodes` beside `curve`; do not nest it inside the compressed
pricing payload and do not precompress it in the publisher:

```python
return pd.DataFrame(
    [
        {
            "time_index": valuation_timestamp,
            "curve_identifier": curve.unique_identifier,
            "curve": {
                30: 0.0500,
                90: 0.0508,
                180: 0.0512,
            },
            "key_nodes": [
                {
                    "maturity_date": "2026-06-26",
                    "quote": 0.0500,
                    "quote_type": "zero_rate",
                    "quote_unit": "decimal",
                    "yield": 0.0500,
                },
                {
                    "maturity_date": "2026-08-25",
                    "source_reference": {
                        "type": "index",
                        "identifier": "USD_SOFR_SWAP_3M",
                    },
                    "instrument_type": "ois_swap",
                    "quote": 0.0508,
                    "quote_type": "par_rate",
                    "quote_unit": "decimal",
                },
            ],
            "metadata_json": {"source_snapshot": "example-2026-05-27"},
        }
    ]
)
```

`metadata_json` stores optional row diagnostics such as provider snapshot IDs,
quality flags, workflow labels, or raw-source checksums. It should not be used
to override the pricing interpretation of `curve` or `key_nodes`.

Source publishers should subclass `DiscountCurvesNode` or inject runtime curve
builder callables. The builder is execution wiring; it is not persisted dataset
identity.

## Related Concepts

- [msm_pricing overview](index.md)
- [Market Data Sets](market_data_sets.md)
- [Fixings](fixings.md)
- [Pricing Scenarios](scenarios/index.md)
- [Runtime Resolution](runtime_resolution.md)
- [Indexes](../msm/indices/index.md)
- [Models](../msm/models/index.md)
- [Core Concepts](../../concepts.md)
