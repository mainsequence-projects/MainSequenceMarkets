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
  -> DiscountCurvesNode(curve_identifier)

IndexTable.unique_identifier
  -> FixingRatesNode(index_identifier, rate)
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
`unique_identifier`, but its `index_uid` points to
`IndexConventionDetailsTable.index_uid`, not directly to loose strings. Curve
rows describe which convention/index the curve belongs to and how to interpret
published curve observations.

Pricing runtime attachment order matters. `create_pricing_schemas(...)` is a
legacy-named startup entrypoint; in current code it attaches already-registered
pricing MetaTables and configures pricing market-data bindings. It does not
create schemas or register missing MetaTables at runtime:

```python
from msm_pricing.bootstrap import create_pricing_schemas

create_pricing_schemas()
```

`create_pricing_schemas(...)` uses the same direct runtime attachment path as
`msm.start_engine(...)`: already-registered tables are attached, and dependency
order is resolved before runtime binding. The dependency order includes
`AssetTable`, `IndexTypeTable`, `IndexTable`, `IndexConventionDetailsTable`,
`CurveTable`, then pricing details and pricing DataNode storage tables. Missing
MetaTables indicate SDK migration/provider work still needs to run before
pricing startup.

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
    IndexConventionDetails,
    PricingMarketDataSet,
    PricingMarketDataSetBinding,
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
    index_uid=index.uid,
    interpolation_method="log_linear_discount",
    compounding="compounded_annual",
    source="example",
)

market_data_set = PricingMarketDataSet.upsert(
    set_key=PRICING_MARKET_DATA_SET_DEFAULT,
    display_name="Default pricing market data",
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

- Use `IndexTable.uid` for pricing relationships stored in instruments and
  convention/curve MetaTables.
- Use `index_identifier` for index-stamped DataNode rows. It stores
  `IndexTable.unique_identifier`.
- Use `curve_identifier` for curve DataNode rows. It stores
  `Curve.unique_identifier`.
- Do not use Main Sequence Constant names as curve or index identity.
- Use `MSDataInterface.get_latest_discount_curve(curve.unique_identifier, ...)`
  when a caller wants the latest available curve snapshot for one curve
  identity. Do not use `USE_LAST_OBSERVATION_MS_INSTRUMENT` as normal
  application control flow.

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

from msm_pricing.data_nodes import CurveConfig, DiscountCurvesNode


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
- The builder configuration's `curve_unique_identifier` must exist as a `Curve`
  row before publishing; emitted storage rows use `curve_identifier`.
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
- `PricingMarketDataSetBinding` resolves the active
  `(market_data_set_uid, concept_key)` to the backend DataNode storage table UID
  for the published curve and fixing DataNodes.
- Use `PRICING_CONCEPT_DISCOUNT_CURVES` and
  `PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS` instead of hard-coded DataNode
  field names.
- When multiple market-data source sets exist in one process, select them at
  pricing time with `bond.price(market_data_set="eod")` or
  `swap.price(market_data_set="live")`.

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
4. Publish fixings.
5. Publish discount curves.
6. Attach pricing storage tables and upsert the pricing market-data set plus
   `PricingMarketDataSetBinding` rows explicitly.
7. Attach/load the instrument by asset.
8. Price and show analytics/cashflows.

## Validation Checklist

Before finishing a change:

- `IndexTable` remains free of Constant-name and curve fields.
- `IndexConventionDetailsTable.index_uid` is one-to-one with `IndexTable.uid`.
- `CurveTable.index_uid` depends on `IndexConventionDetailsTable.index_uid`.
- Fixing DataNode rows use `time_index`, `index_identifier`, and `rate`.
- Curve DataNode rows use `time_index`, `curve_identifier`, and `curve`.
- Instrument payloads store backend index UUIDs and reject raw index-name
  relationship fields.
- Tests cover payload validation, resolver selection, and DataNode frame shape
  for the changed behavior.
- Docs, examples, tutorial, and changelog are updated for user-facing changes.
