---
name: mainsequence-markets-fixed-income-curve-building
description: Use this skill when creating, extending, reviewing, or using ms-markets/msm_pricing fixed-income pricing infrastructure, including Index convention details, index fixing DataNodes, Curve rows, discount curve DataNodes, QuantLib index/curve resolvers, and bond or swap examples that depend on those three coupled concepts.
---

# Main Sequence Markets Fixed-Income Curve Building

Use this skill when an agent needs to build or modify the fixed-income pricing
stack in `msm_pricing`.

This skill treats index conventions, fixings, and curves as one coupled runtime:

```text
IndexTable.uid
  -> IndexConventionDetails.index_uid
  -> Curve.index_uid
  -> DiscountCurvesNode(curve_unique_identifier)

IndexTable.unique_identifier
  -> FixingRatesNode(unique_identifier, rate)
  -> QuantLib index hydration
```

## Route First

Use these skills first when the task crosses their boundaries:

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
- Creating or reviewing `Curve` rows linked to index convention details.
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
4. `src/msm_pricing/data_nodes/index_fixings.py`
5. `src/msm_pricing/data_nodes/curves.py`
6. `src/msm_pricing/pricing_engine/resolvers.py`
7. `src/msm_pricing/meta_tables.py`
8. `examples/pricing/bond_pricing_example/main.py`
9. `examples/pricing/utils/mock_market_data.py`
10. `docs/ADR/0013-current-asset-pricing-details.md`

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
`unique_identifier`, but its `index_uid` points to
`IndexConventionDetailsTable.index_uid`, not directly to loose strings. Curve
rows describe which convention/index the curve belongs to and how to interpret
published curve observations.

Pricing startup order matters:

```python
from msm_pricing.bootstrap import create_pricing_schemas

create_pricing_schemas()
```

`create_pricing_schemas(...)` uses the same maintenance catalog bootstrap as
`msm.start_engine(...)`: already-cataloged tables are attached, missing tables
are registered, and dependencies are processed in FK order. The dependency order
includes `AssetTable`, `IndexTypeTable`, `IndexTable`,
`IndexConventionDetailsTable`, `CurveTable`, then pricing details and pricing
DataNode storage tables.

## Creation Workflow

Use this order for user-facing examples, scripts, tests, and application setup:

```python
from msm.api.indices import Index, IndexType
from msm.constants import (
    INDEX_TYPE_INTEREST_RATE,
    INDEX_TYPE_INTEREST_RATE_DEFINITION,
)
from msm_pricing.api import Curve, IndexConventionDetails, PricingMarketDataBinding
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_CONTEXT_DEFAULT,
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
    index_uid=index.uid,
    interpolation_method="log_linear_discount",
    compounding="compounded_annual",
    source="example",
)

PricingMarketDataBinding.upsert(
    context_key=PRICING_CONTEXT_DEFAULT,
    concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
    data_node_identifier="discount_curves",
)
PricingMarketDataBinding.upsert(
    context_key=PRICING_CONTEXT_DEFAULT,
    concept_key=PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    data_node_identifier="interest_rate_index_fixings",
)
```

Rules:

- Use `IndexTable.uid` for pricing relationships stored in instruments and
  convention/curve MetaTables.
- Use `IndexTable.unique_identifier` only for index-stamped DataNode rows.
- Use `Curve.unique_identifier` for curve DataNode rows.
- Do not use Main Sequence Constant names as curve or index identity.

## Fixings Pattern

Use `FixingRatesNode` for observed index fixings. It extends
`IndexTimestampedDataNode`, so rows are keyed by
`["time_index", "unique_identifier"]`, where `unique_identifier` is
`IndexTable.unique_identifier`.

Subclass `FixingRatesNode` when the source is specific:

```python
import pandas as pd

from msm_pricing.data_nodes import FixingRatesNode, IndexFixingConfiguration


class ExampleFixingsNode(FixingRatesNode):
    def build_fixing_frame(self, *, update_statistics, unique_identifier: str) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "time_index": "2026-05-27T00:00:00Z",
                    "unique_identifier": unique_identifier,
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
`["time_index", "curve_unique_identifier"]`, where
`curve_unique_identifier` is `Curve.unique_identifier`.

Subclass `DiscountCurvesNode` when the curve source is specific:

```python
import pandas as pd

from msm_pricing.data_nodes import CurveConfig, DiscountCurvesNode


class ExampleDiscountCurveNode(DiscountCurvesNode):
    def build_curve_frame(
        self,
        *,
        update_statistics,
        curve_unique_identifier: str,
        base_node_curve_points,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "time_index": "2026-05-27T00:00:00Z",
                    "curve_unique_identifier": curve_unique_identifier,
                    "curve": {30: 0.05, 90: 0.051, 365: 0.052},
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
- `curve_unique_identifier` must exist as a `Curve` row before publishing.
- Keep interpolation and compounding metadata on `Curve`, not in ad hoc builder
  globals.

## Runtime Resolution

Use the pricing resolvers instead of calling local builders directly from
instruments:

```python
from msm_pricing.pricing_engine.resolvers import (
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
```

Resolver expectations:

- `IndexConventionDetails` exists for the index UID.
- Exactly one matching `Curve` exists, or the caller passes `source` or
  `curve_unique_identifier`.
- `PricingMarketDataBinding` resolves the active `(context_key, concept_key)`
  to the DataNode identifier for the published curve and fixing DataNodes.
- Use `PRICING_CONCEPT_DISCOUNT_CURVES` and
  `PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS` instead of hard-coded DataNode
  field names.

For instrument payloads:

- Floating-rate bonds store `floating_rate_index_uid`.
- Swaps store `float_leg_index_uid`.
- Persisted payloads must reject stale `*_index_name` fields.

## Example Pattern

For a full workflow, prefer adapting:

- `examples/pricing/bond_pricing_example/main.py`
- `examples/pricing/utils/mock_market_data.py`

An example should print or otherwise expose each step:

1. Register asset/index/reference rows.
2. Upsert `IndexConventionDetails`.
3. Upsert `Curve`.
4. Publish fixings.
5. Publish discount curves.
6. Use the seeded default pricing context or upsert named
   `PricingMarketDataBinding` rows.
7. Attach/load the instrument by asset.
8. Price and show analytics/cashflows.

## Validation Checklist

Before finishing a change:

- `IndexTable` remains free of Constant-name and curve fields.
- `IndexConventionDetailsTable.index_uid` is one-to-one with `IndexTable.uid`.
- `CurveTable.index_uid` depends on `IndexConventionDetailsTable.index_uid`.
- Fixing DataNode rows use `time_index`, `unique_identifier`, and `rate`.
- Curve DataNode rows use `time_index`, `curve_unique_identifier`, and `curve`.
- Instrument payloads store backend index UUIDs and reject raw index-name
  relationship fields.
- Tests cover payload validation, resolver selection, and DataNode frame shape
  for the changed behavior.
- Docs, examples, tutorial, and changelog are updated for user-facing changes.
