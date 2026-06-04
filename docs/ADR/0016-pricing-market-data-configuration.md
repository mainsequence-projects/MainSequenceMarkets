# 0016. Pricing Market Data Configuration

## Status

Accepted

## Context

`msm_pricing` prices instruments by combining instrument payloads, canonical
asset and index rows, pricing-owned convention rows, curve rows, and published
market-data DataNodes:

```text
Instrument payload
  -> backend index UID fields
  -> IndexConventionDetails
  -> Curve selection
  -> curve and fixing DataNodes
  -> QuantLib objects
```

The previous runtime used an old configuration path:

```python
data_interface.set_instruments_configuration(
    SimpleNamespace(
        discount_curves_data_node_uid="<platform-table-uid>",
        reference_rates_fixings_data_node_uid="<platform-table-uid>",
    )
)
```

That API is wrong for the new package boundary.

The values are not instrument configuration. They are pricing market-data source
configuration: they tell the pricing engine where to read discount-curve rows
and interest-rate-index fixing rows. Instruments already carry their own terms
through `AssetCurrentPricingDetailsTable` and the instrument Pydantic payload.

The existing persisted table is also in the wrong package and has the wrong
shape:

```text
msm.models.instruments.InstrumentsConfigurationTable
```

Core `msm` owns canonical assets and canonical indexes. `msm_pricing` owns
priceable instrument payloads, index convention details, curve rows, fixing
rows, and the runtime that turns those objects into QuantLib pricing inputs.
Core `msm` must not own pricing-engine market-data wiring.

The Main Sequence platform treats DataNodes as reusable published datasets. For
pricing, the built-in datasets are package-level concepts:

```text
DiscountCurvesNode
  identifier: markets_data_node_identifier("DiscountCurvesTS")
  rows:       (time_index, curve_identifier)

FixingRatesNode
  identifier: markets_data_node_identifier("IndexFixingsTS")
  rows:       (time_index, index_identifier)
```

Platform table UIDs are runtime-resolved objects, not stable static library
configuration. Pricing configuration must store DataNode identifiers and resolve
them through `APIDataNode.build_from_identifier(...)`.

Removing persisted configuration entirely would still lose a useful workflow.
Applications often need several named pricing contexts:

```text
default
eod
live
risk_manager
```

Those contexts are useful for valuation, monitoring, and risk workflows because
users should not need to remember which DataNode backs each pricing input. The
problem is not persisted pointers. The problem is that the old table is named as
instrument configuration, lives in core `msm`, stores platform table UIDs, and
uses a wide schema that would require a migration every time a new pricing
market-data concept is added.

## Decision

Remove `InstrumentsConfigurationTable` from core `msm` and replace it with
pricing-owned market-data bindings.

The runtime entry point is:

```text
PricingMarketDataConfiguration
```

`PricingMarketDataConfiguration` selects a pricing context and can carry direct
in-memory concept overrides for tests, scripts, or deployments that do not want
to read persisted bindings.

The persisted schema is vertical: one row per `(context_key, concept_key)`
binding.

```text
PricingMarketDataBindingTable
  uid                   PK
  context_key           e.g. default, eod, live, risk_manager
  concept_key           e.g. discount_curves, interest_rate_index_fixings, equity_vol_curves
  data_node_identifier  DataNode identifier, not platform table UID
  source
  metadata_json

unique(context_key, concept_key)
index(context_key)
index(concept_key)
```

Future pricing concepts add a new concept constant and binding row, not a new
column.

## Constants

Built-in pricing context and concept keys must live in `src/msm_pricing/settings.py`.

```python
PRICING_CONTEXT_DEFAULT = "default"
PRICING_CONTEXT_EOD = "eod"
PRICING_CONTEXT_LIVE = "live"
PRICING_CONTEXT_RISK_MANAGER = "risk_manager"

PRICING_CONCEPT_DISCOUNT_CURVES = "discount_curves"
PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS = "interest_rate_index_fixings"
PRICING_CONCEPT_EQUITY_VOL_CURVES = "equity_vol_curves"
```

The interest-rate fixing concept is `interest_rate_index_fixings`, not
`index_fixings`, because the current fixing DataNode stores a decimal `rate`
column for SOFR, TIIE, IBOR, overnight, and similar interest-rate indexes.
Future equity index levels, inflation fixings, or other index observations get
their own concept keys instead of overloading the interest-rate fixing concept.

## Defaults

The built-in default bindings are:

```text
(default, discount_curves)
  -> markets_data_node_identifier("DiscountCurvesTS")

(default, interest_rate_index_fixings)
  -> markets_data_node_identifier("IndexFixingsTS")
```

These defaults exist in two places:

```text
Static package defaults
  -> used when no persisted binding is selected or available

Persisted default bindings
  -> seeded during pricing bootstrap for discoverability and application use
```

Bootstrap seeding is idempotent. It must not overwrite an existing binding
unless the caller explicitly asks to replace defaults.

## Resolution Flow

Pricing market-data lookup resolves in this order:

```text
1. Direct in-memory override on PricingMarketDataConfiguration
2. Persisted PricingMarketDataBinding row for (context_key, concept_key)
3. Static package default for the built-in concept
4. Failure with a clear missing-binding error
```

The runtime always resolves the final value with:

```python
APIDataNode.build_from_identifier(identifier)
```

It must not store or require platform table UIDs in static defaults or public
pricing examples.

The fixed-income resolver flow is:

```text
FloatingRateBond.floating_rate_index_uid
  -> IndexConventionDetails.get_by_index_uid(index_uid)
  -> Curve.select(index_uid, curve_type="discount")
  -> PricingMarketDataConfiguration.context_key
  -> resolve concept_key="discount_curves"
  -> APIDataNode.build_from_identifier(data_node_identifier)
  -> row where curve_unique_identifier == Curve.unique_identifier
  -> QuantLib YieldTermStructureHandle

IndexTable.unique_identifier
  -> PricingMarketDataConfiguration.context_key
  -> resolve concept_key="interest_rate_index_fixings"
  -> APIDataNode.build_from_identifier(data_node_identifier)
  -> rows where unique_identifier == IndexTable.unique_identifier
  -> QuantLib index fixings
```

## Architecture

```text
                         pricing market-data bindings
                         ----------------------------
                         (default, discount_curves)
                         (default, interest_rate_index_fixings)
                         (risk_manager, equity_vol_curves)
                                      |
                                      v
+---------------------+       +----------------------+       +----------------------+
| CurveTable          |------>| DiscountCurvesNode   |------>| QuantLib curve       |
|---------------------|       |----------------------|       |----------------------|
| unique_identifier   |       | curve_unique_id      |       | YieldTermStructure   |
| index_uid           |       | compressed curve     |       +----------------------+
+---------------------+       +----------------------+
          |
          v
+----------------------------+       +----------------------+       +----------------------+
| IndexConventionDetails     |------>| FixingRatesNode      |------>| QuantLib index       |
|----------------------------|       |----------------------|       |----------------------|
| index_uid                  |       | unique_identifier    |       | IborIndex + fixings  |
| convention_dump            |       | rate                 |       +----------------------+
+----------------------------+       +----------------------+
          ^
          |
+---------------------+
| IndexTable          |
|---------------------|
| uid                 |
| unique_identifier   |
| index_type          |
+---------------------+
```

## Bootstrap Contract

`attach_pricing_schemas(...)` attaches already-cataloged pricing MetaTables and
seeds default market-data bindings only when explicitly requested.

`attach_pricing_schemas(...)` attaches to existing pricing MetaTables without
seeding defaults unless the caller opts in. It must not silently mutate existing
bindings unless the bootstrap call explicitly requests replacement.

The bootstrap API must expose options equivalent to:

```text
seed_default_market_data_bindings=True
replace_default_market_data_bindings=False
```

The seeded rows are pricing-owned MetaTable rows, not core `msm` rows.

## Consequences

- `msm.models.instruments.InstrumentsConfigurationTable` is removed.
- `msm.api.market_metadata.InstrumentsConfiguration` and related repository
  operations are removed.
- `msm_pricing.models.PricingMarketDataBindingTable` becomes the persisted
  pricing-owned table for named market-data contexts.
- `msm_pricing.data_interface` stops using `instruments_configuration`.
- Pricing examples and docs use DataNode identifiers, not platform table UIDs.
- Fresh pricing bootstraps create discoverable default bindings for
  `discount_curves` and `interest_rate_index_fixings`.
- New concepts such as `equity_vol_curves` are added as constants and binding
  rows, not schema columns.
- No backward-compatibility shim is added for the old naming or old table. The
  old boundary is misleading and should not remain alive.

## Implementation Tasks

- [x] Add `PricingMarketDataConfiguration` under `msm_pricing`.
- [x] Add initial static defaults for discount curves and interest-rate-index
  fixing reads.
- [x] Add a pricing bootstrap/configuration helper that installs an optional
  typed override and otherwise leaves the defaults active.
- [x] Replace `MSDataInterface.set_instruments_configuration(...)` with a
  pricing-named configuration path.
- [x] Update `MSDataInterface.get_historical_discount_curve(...)` to resolve the
  discount-curve DataNode from pricing market-data configuration.
- [x] Update `MSDataInterface.get_historical_fixings(...)` to resolve the
  fixing DataNode from pricing market-data configuration.
- [x] Prefer `APIDataNode.build_from_identifier(...)` for configured DataNode
  lookups and avoid platform table UIDs in static defaults.
- [x] Add pricing settings constants:
  `PRICING_CONTEXT_DEFAULT`, `PRICING_CONTEXT_EOD`,
  `PRICING_CONTEXT_LIVE`, `PRICING_CONTEXT_RISK_MANAGER`,
  `PRICING_CONCEPT_DISCOUNT_CURVES`,
  `PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS`, and
  `PRICING_CONCEPT_EQUITY_VOL_CURVES`.
- [x] Rename the built-in fixing DataNode identifier from `index_fixings` to
  `interest_rate_index_fixings` across config, DataNodes, docs, tests, and
  examples.
- [x] Add `PricingMarketDataBindingTable` under `msm_pricing` models with
  `context_key`, `concept_key`, `data_node_identifier`, `source`, and
  `metadata_json`.
- [x] Add a unique constraint or unique index on `(context_key, concept_key)`.
- [x] Add indexes on `context_key` and `concept_key`.
- [x] Register `PricingMarketDataBindingTable` through
  `msm_pricing.meta_tables` in dependency order.
- [x] Add `PricingMarketDataBinding` API rows under `msm_pricing.api`.
- [x] Add row APIs to upsert, search, and resolve bindings by
  `(context_key, concept_key)`.
- [x] Update `PricingMarketDataConfiguration` to carry `context_key` and
  optional direct per-concept identifier overrides.
- [x] Update `MSDataInterface` to resolve `discount_curves` and
  `interest_rate_index_fixings` through direct override, persisted binding, then
  static default.
- [x] Add bootstrap seeding for default `PricingMarketDataBinding` rows after
  pricing MetaTables are attached from the migration-maintained catalog.
- [x] Seed `(PRICING_CONTEXT_DEFAULT, PRICING_CONCEPT_DISCOUNT_CURVES)` to
  `markets_data_node_identifier("DiscountCurvesTS")`.
- [x] Seed
  `(PRICING_CONTEXT_DEFAULT, PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS)` to
  `markets_data_node_identifier("IndexFixingsTS")`.
- [x] Make default binding seeding idempotent and avoid overwriting existing
  rows unless the bootstrap call explicitly requests replacement.
- [x] Add bootstrap options equivalent to
  `seed_default_market_data_bindings` and
  `replace_default_market_data_bindings`.
- [x] Remove `InstrumentsConfigurationTable` from
  `src/msm/models/instruments.py` after the pricing-owned binding table exists.
- [x] Remove `InstrumentsConfiguration` API rows, service exports, and
  repository operations from core `msm` after the pricing-owned binding API
  exists.
- [x] Remove remaining code and example `set_instruments_configuration(...)`
  references and do not add compatibility shims.

## Documentation Tasks

- [x] Document pricing market-data contexts and concept bindings in
  `docs/knowledge/msm_pricing/index.md`.
- [x] Explain why bindings are vertical rows instead of one column per market-data
  source.
- [x] Document built-in context and concept constants:
  `default`, `eod`, `live`, `risk_manager`, `discount_curves`,
  `interest_rate_index_fixings`, and `equity_vol_curves`.
- [x] Update the pricing tutorial to show how a user selects a context and how
  pricing resolves `(context_key, concept_key)` to a DataNode identifier.
- [x] Update `src/msm_pricing/README.md`.
- [x] Update `examples/msm_pricing/bond_pricing_example` to show the default context
  workflow and a second named context such as `eod` when practical.
- [x] Update the fixed-income curve-building skill so coding agents use pricing
  concept constants and `PricingMarketDataBinding` rows instead of hard-coded
  DataNode field names.

## Validation Tasks

- [x] Test that static defaults resolve canonical DataNode identifiers.
- [x] Test that default bootstrap seeding creates the two built-in binding rows.
- [x] Test that seeding is idempotent and does not overwrite existing rows unless
  replacement is explicitly requested.
- [x] Test that explicit in-memory overrides take precedence over persisted
  bindings.
- [x] Test that persisted context bindings resolve by `(context_key, concept_key)`.
- [x] Test that no pricing path stores or requires platform table UIDs.
- [x] Test that pricing resolvers no longer require
  `set_instruments_configuration(...)`.
