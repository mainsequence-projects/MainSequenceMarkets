---
name: mainsequence-markets-fixed-income-curve-building
description: Use this skill when creating, extending, reviewing, or using ms-markets/msm_pricing fixed-income pricing infrastructure, including Index convention details, index fixing DataNodes, Curve rows, CurveBuildingDetails rows, market-data-set curve bindings, discount curve DataNodes, QuantLib index/curve resolvers, and bond or swap examples that depend on those coupled concepts.
---

# Main Sequence Markets Fixed-Income Curve Building

Use this skill when an agent needs to build or modify the fixed-income pricing
stack in `msm_pricing`.

This skill treats index conventions, fixings, and curve selection as one
explicit runtime:

```text
IndexTable.uid
  -> IndexConventionDetails.index_uid
  -> QuantLib index and fixing hydration

PricingMarketDataSetCurveBinding(role + selector + quote side)
  -> CurveTable.uid
  -> CurveBuildingDetails.curve_uid
  -> DiscountCurvesNode(curve_identifier)

IndexTable.unique_identifier
  -> FixingRatesNode(index_identifier, rate)
```

## Route First

Use these skills first when the task crosses their boundaries:

- Generic pricing runtime, pricing details, market-data-set, or valuation-basket
  behavior:
  `.agents/skills/ms_markets/pricing/general_pricing/SKILL.md`
- Generic Main Sequence DataNode behavior:
  `.agents/skills/mainsequence/data_publishing/data_nodes/SKILL.md`
- Generic Main Sequence MetaTable behavior:
  `.agents/skills/mainsequence/data_publishing/meta_tables/SKILL.md`
- Asset identity or bond asset detail tables:
  `.agents/skills/ms_markets/assets/asset_model_extension/SKILL.md`
- Asset-indexed market data:
  `.agents/skills/ms_markets/assets/asset_indexed_data_nodes/SKILL.md`

Then use this skill for pricing-specific index, fixing, and curve choices.

## This Skill Owns

- Creating or reviewing `IndexConventionDetails` rows for canonical
  `msm.models.IndexTable` rows.
- Creating or reviewing `Curve` rows, their `CurveBuildingDetails`, and their
  market-data-set curve selection bindings.
- Creating or extending `FixingRatesNode` subclasses that publish index fixings.
- Creating or extending `DiscountCurvesNode` subclasses that publish compressed
  curve payloads.
- Wiring `msm_pricing.pricing_engine.resolvers` into bonds, swaps, examples, and
  tests.
- Ensuring persisted instruments use backend UUID fields such as
  `floating_rate_index_uid` or `float_leg_index_uid`.

## This Skill Does Not Own

- Turning indexes into assets. Indexes are reference rows, not tradable assets.
- Reintroducing platform Constant names, raw index-name relationships, or
  `*_index_name` fields into pricing payloads.
- Adding curve identity to `AssetTable`.
- Generic job scheduling, releases, RBAC, FastAPI, dashboards, or Command
  Center workspaces.

## Read First

Before changing code, inspect the local implementation relevant to the task:

1. `src/msm/api/indices.py`
2. `src/msm_pricing/api/index_convention_details.py`
3. `src/msm_pricing/api/curves.py`
4. `src/msm_pricing/data_nodes/index_fixings/__init__.py`
5. `src/msm_pricing/data_nodes/index_fixings/storage.py`
6. `src/msm_pricing/data_nodes/curves/__init__.py`
7. `src/msm_pricing/data_nodes/curves/storage.py`
8. `src/msm_pricing/pricing_engine/resolvers.py`
9. `src/msm_pricing/meta_tables.py`
10. `examples/msm_pricing/bond_pricing_example/main.py`
11. `examples/msm_pricing/utils/mock_market_data.py`
12. `docs/knowledge/msm_pricing/index.md`
13. `docs/ADR/0026-explicit-pricing-market-data-sets.md`

For generic SDK semantics, verify against the latest Main Sequence docs instead
of relying on memory.

## Core Model

`IndexTable` is core market reference data. It stores canonical index identity:

- `uid`
- `unique_identifier`
- `index_type`
- `display_name`
- `description`
- `provider`
- `metadata_json`

`IndexTypeTable` is the core index type registry. For fixed-income indexes,
register `interest_rate` through `IndexType` before creating the index row.

Do not add legacy Constant-name fields to `IndexTable`.

`IndexConventionDetailsTable` is pricing-owned convention metadata keyed
one-to-one by `index_uid`. It stores the convention dump needed to reconstruct
QuantLib indexes: index family, currency, tenor, day counter, calendar, business
day convention, settlement days, end-of-month handling, and optional fixing
identity override.

`CurveTable` is pricing-owned curve identity. It has its own `uid` and
`unique_identifier`. It has no index ownership field. Curve selection must use
`PricingMarketDataSetCurveBindingTable`.

`CurveBuildingDetailsTable` is keyed one-to-one by `curve_uid` and stores how to
turn published observations into a QuantLib curve: builder type, quote
convention, rate unit, day counter, calendar, interpolation, compounding,
extrapolation policy, source, and metadata.

`PricingMarketDataSetCurveBindingTable` selects curve identity within a
market-data set. Use it for `discount`, `projection`, `forwarding`,
`z_spread_base`, bid/mid/offer, source/scenario, basis/spread, and future
volatility curve or surface selection decisions. Do not encode those policy
choices as foreign keys from `CurveTable` to `IndexConventionDetailsTable`.
The binding uniqueness boundary is `(market_data_set_uid, binding_key)`, where
`binding_key` is derived from role, selector type, selector key, and quote side.
`curve_uid` is not unique: multiple roles, indices, quote sides, source sets,
or selector types may deliberately select the same curve. Do not infer a single
owning index or selector from a `Curve` row.

## Runtime Usability Invariant

An active `Curve` row intended for runtime pricing is incomplete unless the
agent also creates or verifies all of the following:

- `CurveBuildingDetails` exists for `curve_uid`.
- At least one `PricingMarketDataSetCurveBinding` selects the curve for the
  intended market-data set, valuation role, selector, and quote side.
- The market-data set has a `PricingMarketDataSetBinding` for
  `PRICING_CONCEPT_DISCOUNT_CURVES` pointing at the curve storage DataNode.
- Published or publishable `DiscountCurvesNode` observations use
  `curve_identifier=Curve.unique_identifier`.

For index-scoped curve selection, use
`PricingMarketDataSetCurveBinding.upsert_index_curve_selection(...)`; do not ask
users or examples to pass `selector_type="index"` and `selector_key=str(index.uid)`.

If a curve is deliberately created only as a registry/staging row, state that
explicitly in the code, example, or documentation. Do not claim the curve is
priceable, observable through runtime resolution, or ready for bond/swap pricing
until the build details, market-data source binding, and curve selection binding
exist.

Pricing runtime attachment order matters. `attach_pricing_schemas(...)` is the
startup entrypoint; it attaches already-registered pricing MetaTables and
configures pricing market-data bindings. It does not create schemas or register
missing MetaTables at runtime:

```python
from msm_pricing.bootstrap import attach_pricing_schemas

attach_pricing_schemas(seed_default_market_data_bindings=True)
```

`attach_pricing_schemas(...)` uses the same direct runtime attachment path as
`msm.start_engine(...)`: already-registered tables are attached, and dependency
order is resolved before runtime binding. The dependency order includes
`AssetTable`, `IndexTypeTable`, `IndexTable`, `IndexConventionDetailsTable`,
`CurveTable`, `CurveBuildingDetailsTable`, then pricing details,
`PricingMarketDataSetTable`, `PricingMarketDataSetBindingTable`,
`PricingMarketDataSetCurveBindingTable`, and pricing DataNode storage tables.
Missing MetaTables indicate SDK migration/provider work still needs to run
before pricing startup.

## Creation Workflow

Use this order for user-facing examples, scripts, tests, and application setup:

```python
from msm.api.indices import Index, IndexType
from msm.constants import (
    INDEX_TYPE_INTEREST_RATE,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)
from msm_pricing.api import (
    Curve,
    CurveBuildingDetails,
    IndexConventionDetails,
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
    PricingMarketDataSetCurveBinding,
)
from msm_pricing.data_nodes.curves.storage import DiscountCurvesStorage
from msm_pricing.data_nodes.index_fixings.storage import IndexFixingsStorage
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_MARKET_DATA_SET_DEFAULT,
)

IndexType.upsert(**INDEX_TYPE_INTEREST_RATE_DEFINITION.as_payload())
index = Index.upsert(
    unique_identifier="USD-SOFR-3M",
    index_type=INDEX_TYPE_INTEREST_RATE,
    display_name="USD SOFR 3M",
    provider="example",
)

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

curve = Curve.upsert(
    unique_identifier="USD-SOFR-3M-DISCOUNT",
    display_name="USD SOFR 3M Discount Curve",
    curve_type="discount",
    currency_code="USD",
    quote_side="mid",
    interpolation_method="log_linear_discount",
    compounding="compounded_annual",
    source="example",
)

market_data_set = PricingMarketDataSet.upsert(
    set_key=PRICING_MARKET_DATA_SET_DEFAULT,
    display_name="Default pricing market data",
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
    source="example",
)
PricingMarketDataSetCurveBinding.upsert_index_curve_selection(
    market_data_set_uid=market_data_set.uid,
    role_key="projection",
    index_uid=index.uid,
    quote_side="mid",
    curve_uid=curve.uid,
    source="example",
)
PricingMarketDataSetBinding.upsert(
    market_data_set_uid=market_data_set.uid,
    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
    data_node_uid=DiscountCurvesStorage.get_meta_table_uid(),
    storage_table_identifier=DiscountCurvesStorage.get_identifier(),
)
PricingMarketDataSetBinding.upsert(
    market_data_set_uid=market_data_set.uid,
    concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    data_node_uid=IndexFixingsStorage.get_meta_table_uid(),
    storage_table_identifier=IndexFixingsStorage.get_identifier(),
)
```

Rules:

- Use `IndexTable.uid` for pricing relationships stored in instruments,
  convention details, and market-data curve binding selectors.
- Persist fixed-income instruments through `instrument.serialize_for_backend()`,
  `instrument.attach_to_asset(...)`, `msm_pricing.api.add_pricing_details(...)`,
  or `msm_pricing.api.add_many_pricing_details(...)`. Do not hand-build
  `instrument_dump` calendar JSON. Instrument calendar fields use
  `ql_fields.QuantLibCalendar` and must store QuantLib display-name JSON from
  `calendar.name()`: for Mexico BMV, store
  `{"name": "Mexican stock exchange"}`, not `{"name": "Mexico"}` and not
  `{"name": "Mexico-BMV"}`.
- Use `index_identifier` for index-stamped DataNode rows. It stores
  `IndexTable.unique_identifier`.
- Use `curve_identifier` for curve DataNode rows. It stores
  `Curve.unique_identifier`.
- Do not use Main Sequence Constant names as curve or index identity.
- Use `MSDataInterface.get_latest_discount_curve(curve.unique_identifier, ...)`
  when a caller wants the latest available curve snapshot for one curve
  identity. Do not use `USE_LAST_OBSERVATION_MS_INSTRUMENT` as normal
  application control flow.
- Persist pricing details for one asset with `instrument.attach_to_asset(asset)`
  or `msm_pricing.api.add_pricing_details(...)`. For thousands of assets, use
  `msm_pricing.api.add_many_pricing_details(...)` so instruments are serialized
  once and pricing-detail/current rows are written through chunked bulk upserts.
  Do not loop single-asset writes for large universes. Explicit
  `pricing_details_date` writes must still reconcile the current projection:
  update current when no current row exists or when the new date is newer than
  current.

## Fixings Pattern

Use `FixingRatesNode` for observed index fixings. It extends
`IndexTimestampedDataNode`, so rows are keyed by
`["time_index", "index_identifier"]`, where `index_identifier` is
`IndexTable.unique_identifier`.

Subclass `FixingRatesNode` when the source is specific:

```python
import pandas as pd

from msm_pricing.data_nodes import FixingRatesNode, IndexFixingConfiguration


class ExampleFixingsNode(FixingRatesNode):
    def build_fixing_frame(self, *, update_statistics, index_identifier: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "time_index": "2026-05-27T00:00:00Z",
                    "index_identifier": index_identifier,
                    "rate": 0.0525,
                }
            ]
        )


node = ExampleFixingsNode(
    IndexFixingConfiguration(index_unique_identifiers=["USD-SOFR-3M"])
)
node.run(debug_mode=True, force_update=True)
```

Rules:

- `rate` is a decimal rate, not percent.
- `frequency` is hashable dataset identity; changing it creates a distinct
  fixing dataset.
- Keep builders keyed by `IndexTable.unique_identifier`.
- Do not publish fixings keyed by backend UUID unless the DataNode contract is
  deliberately changed.

## Curve Pattern

Use `DiscountCurvesNode` for compressed discount curves. Rows are keyed by
`["time_index", "curve_identifier"]`, where `curve_identifier` is
`Curve.unique_identifier`.

Subclass `DiscountCurvesNode` when the curve source is specific:

```python
import pandas as pd

from msm_pricing.data_nodes import CurveConfig, CurveKeyNode, DiscountCurvesNode


class ExampleDiscountCurveNode(DiscountCurvesNode):
    def build_curve_frame(
        self,
        *,
        update_statistics,
        curve_identifier: str,
        base_node_curve_points,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "time_index": "2026-05-27T00:00:00Z",
                    "curve_identifier": curve_identifier,
                    "curve": {30: 0.05, 90: 0.051, 365: 0.052},
                    "key_nodes": [
                        CurveKeyNode(
                            maturity_date="2026-06-26",
                            instrument_type="direct_zero_rate",
                            quote=0.05,
                            quote_type="zero_rate",
                            quote_unit="decimal",
                            yield_value=0.05,
                        ).model_dump(mode="json", by_alias=True, exclude_none=True),
                        CurveKeyNode(
                            maturity_date="2026-08-25",
                            instrument_type="direct_zero_rate",
                            quote=0.051,
                            quote_type="zero_rate",
                            quote_unit="decimal",
                            yield_value=0.051,
                        ).model_dump(mode="json", by_alias=True, exclude_none=True),
                        CurveKeyNode(
                            maturity_date="2027-05-27",
                            instrument_type="direct_zero_rate",
                            quote=0.052,
                            quote_type="zero_rate",
                            quote_unit="decimal",
                            yield_value=0.052,
                        ).model_dump(mode="json", by_alias=True, exclude_none=True),
                    ],
                }
            ]
        )


node = ExampleDiscountCurveNode(
    CurveConfig(curve_unique_identifier="USD-SOFR-3M-DISCOUNT")
)
node.run(debug_mode=True, force_update=True)
```

Rules:

- The builder returns a mapping from days-to-maturity to zero rates; the node
  compresses it before persistence.
- The builder also returns `key_nodes` construction provenance. `key_nodes` is
  source-owned JSON object/list provenance. The node compresses it before
  persistence and read/API helpers return decompressed JSON. Prefer the
  optional `CurveKeyNode` helper when the standard fields fit: `maturity_date`,
  `asset_identifier`, `instrument_type`, `quote`, `quote_type`, `quote_unit`,
  `quote_side`, and optional yield-native `yield` via the Python field
  `yield_value`. Producers may add source-specific extensions and enforce them
  through `normalize_key_nodes(...)` or `set_key_nodes_validator(...)`.
  Per-node `quote_type` and `quote_unit` describe raw source inputs;
  `CurveBuildingDetails` describes the final stored curve.
- When a producer needs stricter source-specific semantics, override
  `DiscountCurvesNode.normalize_key_nodes(...)` or attach a runtime callable
  with `set_key_nodes_validator(...)`. The hook receives the normalized
  key-node value, the full row, and the curve identifier. It must return JSON
  object/list provenance. Do not put validator callables in `CurveConfig`; they
  are execution behavior, not hashed DataNode configuration.
- Optional row diagnostics belong in the storage column named `metadata_json`.
- The builder configuration's `curve_unique_identifier` must exist as a `Curve`
  row before publishing; emitted storage rows use `curve_identifier`.
- Keep interpolation and compounding metadata on `CurveBuildingDetails`, not in
  ad hoc builder globals. Runtime curve construction must dispatch to native
  QuantLib constructors by `interpolation_method`; do not hardcode every curve
  as log-linear discount.
- Supported `interpolation_method` values are `log_linear_discount`,
  `log_cubic_discount`, `linear_zero`, `cubic_zero`, `natural_cubic_zero`,
  `monotone_cubic_zero`, and `linear_forward` only when
  `quote_convention="forward_rate"`.
- Reject deprecated QuantLib method names such as `log_linear_zero`,
  `LogLinearZeroCurve`, `monotonic_log_cubic_discount`, and
  `MonotonicLogCubicDiscountCurve`. Do not add aliases for them.

## Runtime Resolution

Use the pricing resolvers instead of calling local builders directly from
instruments:

```python
from msm_pricing.pricing_engine.resolvers import (
    resolve_curve_for_index_binding,
    resolve_pricing_curve,
    resolve_quantlib_index,
)

index = resolve_quantlib_index(
    index_uid=index.uid,
    valuation_date=valuation_date,
)
curve = resolve_pricing_curve(
    index_uid=index.uid,
    valuation_date=valuation_date,
    curve_type="discount",
)
benchmark_curve = resolve_curve_for_index_binding(
    index_uid=benchmark_index.uid,
    valuation_date=valuation_date,
    role_key="z_spread_base",
    market_data_set="eod",
    quote_side="mid",
)
```

Resolver expectations:

- `IndexConventionDetails` exists for the index UID.
- `PricingMarketDataSetCurveBinding` resolves the valuation role and selector
  to exactly one `Curve`. For index-scoped workflows, use
  `upsert_index_curve_selection(...)` and `resolve_index_curve_uid(...)` instead
  of passing raw selector fields.
- `benchmark_rate_index_uid` is only an index selector. Benchmark z-spread
  resolution must use `role_key="z_spread_base"`, the benchmark index UID, and
  the requested quote side through
  `PricingMarketDataSetCurveBinding.resolve_index_curve_uid(...)`.
- `CurveBuildingDetails` exists for the selected curve.
- `PricingMarketDataSetBinding` resolves the active
  `(market_data_set_uid, concept_key)` to the backend DataNode storage table UID
  for the published curve and fixing DataNodes.
- Use `PRICING_CONCEPT_DISCOUNT_CURVES` and
  `PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS` instead of hard-coded DataNode
  field names.
- When multiple market-data source sets exist in one process, select them at
  pricing time with `bond.price(market_data_set="eod")` or
  `swap.price(market_data_set="live")`.
- There is no implicit `mid` fallback. If a binding is written with
  `quote_side="mid"`, runtime calls must request that quote side; omitted quote
  side means the default binding key.

For instrument payloads:

- Floating-rate bonds store `floating_rate_index_uid`.
- Swaps store `float_leg_index_uid`.
- Persisted payloads must reject stale `*_index_name` fields.

## Example Pattern

For a full workflow, prefer adapting:

- `examples/msm_pricing/bond_pricing_example/main.py`
- `examples/msm_pricing/utils/mock_market_data.py`

An example should print or otherwise expose each step:

1. Register asset/index/reference rows.
2. Upsert `IndexConventionDetails`.
3. Upsert `Curve`.
4. Upsert `CurveBuildingDetails`.
5. Upsert `PricingMarketDataSetCurveBinding` through
   `upsert_index_curve_selection(...)` for index-scoped selections.
6. Publish fixings.
7. Publish discount curves.
8. Attach pricing storage tables and upsert the pricing market-data set plus
   `PricingMarketDataSetBinding` rows explicitly.
9. Attach/load the instrument by asset.
10. Price and show analytics/cashflows.

## Validation Checklist

Before finishing a change:

- `IndexTable` remains free of Constant-name and curve fields.
- `IndexConventionDetailsTable.index_uid` is one-to-one with `IndexTable.uid`.
- `CurveTable` has no index ownership field.
- Every active/runtime priced curve has `CurveBuildingDetails`.
- Every active/runtime priced curve has at least one
  `PricingMarketDataSetCurveBinding`, or is explicitly documented as a
  non-runtime registry/staging row.
- Market-data-set curve selection uses `PricingMarketDataSetCurveBinding`, and
  index-scoped selections use `upsert_index_curve_selection(...)`.
- Curve-binding reviews distinguish selector uniqueness from curve sharing:
  duplicate `(market_data_set_uid, binding_key)` rows are invalid, but multiple
  bindings pointing at the same `curve_uid` are valid when the policy calls for
  shared curve identity.
- Runtime curve reads have a `PricingMarketDataSetBinding` for
  `PRICING_CONCEPT_DISCOUNT_CURVES`.
- Fixing DataNode rows use `time_index`, `index_identifier`, and `rate`.
- Curve DataNode rows use `time_index`, `curve_identifier`, and `curve`.
- Instrument payloads store backend index UUIDs and reject raw index-name
  relationship fields.
- Tests cover payload validation, resolver selection, and DataNode frame shape
  for the changed behavior.
- Docs, examples, tutorial, and changelog are updated for user-facing changes.
