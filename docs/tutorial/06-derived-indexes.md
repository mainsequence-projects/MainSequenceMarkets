# Index Values And Derived Indexes

This chapter publishes a plain Index observation, then registers a versioned
derived Index, previews it in memory, binds source storage, publishes a
backfill, and consumes the canonical history.

## Before You Start: Index Or Portfolio?

Use this workflow for a theoretical observable or benchmark whose value is the
same for every consumer given the same methodology and market inputs. If the
workflow instead depends on account capital, actual quantities, cash, orders,
fills, or realized P&L, build a Portfolio. A Portfolio may reference and
replicate the Index, but its holdings must not replace the Index definition.
See [Derived Index Workflow](../knowledge/msm/indices/derived_indexes.md#index-versus-portfolio)
for the full decision table and architecture diagram.

## 1. Apply The Package Migration

Schema migration is an administrator or release step. From the ms-markets
checkout, use the SDK-managed provider:

```bash
mainsequence project refresh_token --path .
mainsequence migrations upgrade --provider migrations:migration head
```

Revision `0011` creates the definition, leg, canonical value, and resolved-leg
tables. Revision `0012` generalizes the value table: `definition_uid` becomes
nullable and `calculation_status` is renamed to nullable
`observation_status` without replacing the table or discarding existing rows.
The migration flow finalizes the MetaTable catalog bindings. Runtime startup
attaches those already-migrated tables; it does not create them.

`IndexValuesStorage` is the schema anchor. A real value history must use a
cadence-configured model created before its migration provider. The executable
`examples/msm/indices/index_values_frequency_migration.py` provider includes
both models from this tutorial:

```text
IndexValuesTS.1m -> ms_markets__index_values__t_1m
IndexValuesTS.1d -> ms_markets__index_values__t_1d
```

Use the normal SDK migration revision and upgrade lifecycle for the selected
provider. Do not expect runtime startup to create these tables.

## 2. Publish A Plain Index Value

An Index does not need a calculation definition. `USD_SWAP_10Y` is one
observable identity, but its one-minute and daily histories are two datasets:

```python
import pandas as pd

from msm.data_nodes.indices import (
    IndexValuesDataNode,
    configured_index_values_storage,
)

ONE_MINUTE_VALUES = configured_index_values_storage(cadence="1m")
DAILY_VALUES = configured_index_values_storage(cadence="1d")


class Swap10YOneMinuteDataNode(IndexValuesDataNode):
    @classmethod
    def _required_storage_table(cls):
        return ONE_MINUTE_VALUES


class Swap10YDailyDataNode(IndexValuesDataNode):
    @classmethod
    def _required_storage_table(cls):
        return DAILY_VALUES

one_minute_values = Swap10YOneMinuteDataNode.validate_frame(
    pd.DataFrame(
        [
            {
                "time_index": "2026-07-17T14:00:00Z",
                "index_identifier": "USD_SWAP_10Y",
                "value": 0.04192,
                "unit": "decimal",
                "observation_status": "preliminary",
            },
        ]
    )
)

daily_values = Swap10YDailyDataNode.validate_frame(
    pd.DataFrame(
        [
            {
                "time_index": "2026-07-17T23:59:59Z",
                "index_identifier": "USD_SWAP_10Y",
                "value": 0.04205,
                "unit": "decimal",
                "observation_status": "final",
            }
        ]
    )
)

assert ONE_MINUTE_VALUES.__table__.name == "ms_markets__index_values__t_1m"
assert DAILY_VALUES.__table__.name == "ms_markets__index_values__t_1d"
assert ONE_MINUTE_VALUES is not DAILY_VALUES
assert one_minute_values.reset_index()["definition_uid"].isna().all()
assert daily_values.reset_index()["definition_uid"].isna().all()
```

Frequency is not a property of Index identity, but it is a unique definer of
the storage dataset. It therefore drives a different DataNode, MetaTable
identifier, `__cadence__`, storage hash, and physical table name. If core owns
a prospective calculation-method change, add a new effective definition
version. If two complete method histories must coexist, assign them distinct
Index identities.

An extension may own a richer Index-indexed storage, its own update process,
and fields such as bid, ask, source, or quality. It is not required to inherit
`IndexTimestampedDataNode`. Keep the foreign key to
`IndexTable.unique_identifier`, then optionally map one selected value into
the cadence-matched canonical Index-value table for generic consumers. The
executable
`extension_owned_index_storage.py` example demonstrates that boundary.

## 3. Attach The Minimal Runtime

```python
from msm.api.indices import DerivedIndex

DerivedIndex.start_engine()
```

This attaches `IndexTypeTable`, `IndexTable`,
`IndexCalculationDefinitionTable`, and `IndexCalculationLegTable`. Add source
or output storage models to the explicit `models=[...]` list when the same
runtime will use them.

## 4. Persist Identity, Definition, And Legs

```python
import datetime
import uuid

from msm.api.indices import (
    DerivedIndex,
    IndexCalculationDefinition,
    IndexCalculationLeg,
)

definition = IndexCalculationDefinition(
    effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
    status="active",
    calculation_kind="linear_combination",
    calculation_family="yield_spread",
    output_unit="basis_points",
    alignment_policy="inner",
    missing_data_policy="drop",
    composition_mode="fixed",
)

spread = DerivedIndex.upsert(
    unique_identifier="EXAMPLE_2S5S_YIELD_SPREAD",
    display_name="Example 2s5s Yield Spread",
    definition=definition,
    legs=[
        IndexCalculationLeg(
            leg_key="long",
            leg_order=0,
            component_kind="asset",
            asset_uid=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            observable_code="yield",
            input_unit="decimal",
            coefficient_method="fixed",
            coefficient=1.0,
        ),
        IndexCalculationLeg(
            leg_key="short",
            leg_order=1,
            component_kind="asset",
            asset_uid=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            observable_code="yield",
            input_unit="decimal",
            coefficient_method="fixed",
            coefficient=-1.0,
        ),
    ],
)
```

The example UUIDs must be replaced by real registered Assets. The write is
idempotent by semantic hash. Change a coefficient, selector, unit, alignment,
or other output-affecting field by inserting the next version with a new
effective start; do not edit the activated row.

## 5. Preview Without Platform Reads

```python
import pandas as pd

times = pd.date_range("2025-01-01", periods=2, tz="UTC")
preview = spread.calculate(
    {
        "long": pd.Series([0.0841, 0.0850], index=times),
        "short": pd.Series([0.0724, 0.0730], index=times),
    }
)

assert preview.values["value"].tolist() == [117.0, 120.0]
```

The preview uses the same unit, alignment, missing-data, transform, and
coefficient contracts as production publication.

## 6. Bind Source Storage Explicitly

Assume `BondAnalyticsStorage` is an already migrated and registered
`PlatformTimeIndexMetaTable` that contains Asset identity, UTC time, yield, and
any risk observables required by the legs.

```python
from msm.data_nodes.indices import (
    DerivedIndexDataNode,
    DerivedIndexDataNodeConfiguration,
    configured_index_values_storage,
)

DAILY_INDEX_VALUES = configured_index_values_storage(cadence="1d")

config = DerivedIndexDataNodeConfiguration(
    index_identifiers=("EXAMPLE_2S5S_YIELD_SPREAD",),
    source_bindings={"yield": BondAnalyticsStorage},
    offset_start="2025-01-01T00:00:00Z",
)

node = DerivedIndexDataNode(
    config=config,
    storage_table=DAILY_INDEX_VALUES,
    hash_namespace="tutorial.derived-indexes.v1",
)
```

Use either a leg key or observable code as a binding key. Changing the bound
storage changes hashed configuration and dependency identity. The node does
not discover new dependencies inside `update()`.

For a selector, rolling constituent, beta, DV01, or delta coefficient, require
the provenance dependency:

```python
from msm.data_nodes.indices import IndexResolvedLegsStorage

dynamic_config = DerivedIndexDataNodeConfiguration(
    index_identifiers=("EXAMPLE_ROLLING_INDEX",),
    source_bindings={"settlement": FuturesSettlementStorage},
    requires_resolved_legs=True,
    resolved_legs_storage=IndexResolvedLegsStorage,
    offset_start="2025-01-01T00:00:00Z",
)
```

The value node then declares a resolved-leg producer dependency and fails if
dynamic provenance is absent.

## 7. Backfill And Repair

Run the graph with the explicit namespace:

```python
error_on_last_update, values = node.run(
    debug_mode=True,
    force_update=True,
)
```

Normal later runs continue incrementally from update statistics. For a
controlled correction under the same methodology, delete only the affected
Index tails and rerun:

```python
node.repair_after(
    "2025-06-01T00:00:00Z",
    index_identifiers=["EXAMPLE_2S5S_YIELD_SPREAD"],
)
```

Do not use this to make a retroactive methodology with coexisting historical
meaning. That requires a new Index identity.

## 8. Consume Canonical History

Downstream DataNodes and APIs consume the generic storage contract instead of
recalculating the formula:

```python
from mainsequence.meta_tables import APIDataNode
from msm.data_nodes.indices import configured_index_values_storage

DAILY_INDEX_VALUES = configured_index_values_storage(cadence="1d")

source = APIDataNode.build_from_meta_table(
    DAILY_INDEX_VALUES.get_time_index_meta_table()
)
history = source.get_df_between_dates(
    start_date="2025-01-01T00:00:00Z",
    end_date="2025-12-31T23:59:59Z",
    dimension_filters={
        "index_identifier": ["EXAMPLE_2S5S_YIELD_SPREAD"],
    },
)
```

Keep z-score interpretation, long/short decisions, portfolio quantities, and
execution state downstream from this canonical observable.

## Complete Examples

Run the seven offline examples from the source checkout:

```bash
python examples/msm/indices/plain_index_values.py
python examples/msm/indices/extension_owned_index_storage.py
python examples/msm/indices/m_bond_2s5s_yield_spread.py
python examples/msm/indices/commodity_calendar_spread.py
python examples/msm/indices/weighted_multi_leg_spreads.py
python examples/msm/indices/equity_beta_spread.py
python examples/msm/indices/delta_hedged_option_index.py
```

The concept reference is [Derived Index Workflow](../knowledge/msm/indices/derived_indexes.md).
