# Tutorial

This section will contain guided, end-to-end learning material for `ms-markets`.

Planned tutorial areas:

- setting up a markets project
- working with assets and asset categories
- building market data nodes
- constructing portfolios
- installing the optional pricing extra and using `msm_pricing` priceable instruments
- exposing markets workflows through Main Sequence applications with the
  optional `public_api` extra

## Library Maintenance Workflow

When changing this library, use the local Open Agent skill at
`.agents/skills/library_maintenance/SKILL.md`.

The maintenance loop for any meaningful implementation change is:

1. Classify the affected `msm` concept area.
2. Update the closest knowledge documentation under `docs/knowledge/`.
3. Add or update an example under `examples/msm/`,
   `examples/msm_portfolios/`, or `examples/msm_pricing/`.
4. Update this tutorial section or add a focused tutorial page.
5. Update `CHANGELOG.md` for maintainer- or user-facing changes.
6. Run focused validation and report any skipped maintenance item explicitly.

This tutorial requirement is intentional: examples show isolated usage, while
tutorials show the order a user should follow.

## Installing MS Markets Agent Skills

Use the `msm` CLI when a host Main Sequence project should receive the
ms-markets agent skills:

```bash
msm copy-msm-skills --path .
```

The command copies the packaged bundle into `.agents/skills/ms_markets/` and
overwrites only matching skill folders under that namespace. It does not touch
`.agents/skills/mainsequence`, project-state files, or `AGENTS.md`.

Run it only from a separate host project. The CLI rejects the ms-markets source
checkout to avoid deleting the package-owned skill bundle.

Do not rely on `import msm` for this setup. Imports are side-effect free and do
not copy skills into the current working tree.

## Schema Migrations Before Runtime

`msm.start_engine(...)` is runtime attachment. It resolves finalized
`MetaTable` and `TimeIndexMetaTable` resources directly by each selected
model's SQLAlchemy table name, then binds those backend objects for row APIs.
It does not create or evolve schema.

Run admin migrations before application startup:

```bash
mainsequence migrations current --provider migrations:migration --json
mainsequence migrations upgrade --provider migrations:migration head
```

See [Migrations](../knowledge/msm/migrations/index.md)
for the package registry, SDK Alembic provider, upgrade flow, catalog
finalization, and runtime attachment lifecycle.

## Asset Identity And Provider Rows

Use this workflow when ingesting external asset metadata:

1. Resolve or normalize provider data through a service module, for example
   `msm.services.assets.openfigi`.
2. Register the asset type through `msm.api.assets.AssetType` when the type is
   new to the project or namespace. Use `msm.constants` for built-in type keys
   such as `ASSET_TYPE_BOND`, `ASSET_TYPE_CRYPTO`, `ASSET_TYPE_CURRENCY`,
   `ASSET_TYPE_CURRENCY_SPOT`, `ASSET_TYPE_EQUITY`, and
   `ASSET_TYPE_FUTURE`.
3. Persist canonical identity through the user-facing `msm.api.assets.Asset`
   row API. Row operations attach to registered MetaTables lazily.
4. Store timestamped asset facts through DataNode schemas in
   `msm.data_nodes.assets`.

The package boundary is deliberate: `msm.api` owns user row operations,
`msm.models.*Table` owns SQLAlchemy schema declarations, DataNodes own
time-indexed market facts, and services own external provider integration.

```python
from msm.data_nodes.assets import AssetSnapshot
from msm.services.assets.openfigi import (
    query_by_figi,
)
from msm.constants import ASSET_TYPE_BOND
```

See `examples/msm/assets/asset_crud_workflow.py` for the asset workflow covering
OpenFIGI resolution, `Asset` registration, `OpenFigiDetails`, and
`AssetSnapshot` writes. The OpenFIGI helpers read the API key from the Main
Sequence secret `OPEN_FIGI_API_KEY`.

See `examples/msm/assets/asset_type_constants.py` for a small import-only example
that prints the built-in constants and `AssetType.upsert(...)` payloads.

For timestamped facts keyed to index reference rows, use the same stamped
DataNode workflow with `msm.data_nodes.indices.IndexTimestampedDataNode` and an
`IndexDataNodeConfiguration` subclass. The frame contract is
`["time_index", "index_identifier"]`, with a canonical source-table foreign key
from `index_identifier` to `IndexTable.unique_identifier`. Keep index identity
on `uid` and `unique_identifier`; do not add legacy platform Constant-name
fields.

## Calendar Materialization

Use this workflow when a project needs durable market, settlement, fixing, or
custom calendar facts:

1. Before runtime, run the admin migration flow with
   `mainsequence migrations upgrade --provider migrations:migration head`.
2. Attach `Calendar`, `CalendarDate`, `CalendarSession`, and `CalendarEvent`
   with `msm.start_engine(...)`.
3. Use `Calendar.create_from_pandas_calendar(...)` for generated market
   calendars, including `source_identifier="24/7"` for the standard crypto
   24/7 calendar.
4. Use `msm.services.calendars` directly only when lower-level materialization
   control is required.

`pandas_market_calendars` is not the durable source of truth. It is an adapter
that writes into `CalendarDateTable` and `CalendarSessionTable`; consumers
should read the persisted rows or reference `CalendarTable.uid`.

```python
from msm.api.calendars import Calendar

calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="CRYPTO_24_7",
    display_name="Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)
```

See `examples/msm/calendars/calendar_materialization_workflow.py` for the
calendar workflow covering XNYS materialization from `pandas_market_calendars`
and a `CRYPTO_24_7` calendar. See
`examples/msm_portfolios/portfolio_equal_weights_example.py` for the portfolio
workflow using the generated crypto calendar as `Portfolio.calendar_uid`.

## Account Holdings Workflow

Use this workflow when publishing and inspecting account positions:

1. Before runtime, run the admin migration flow with
   `mainsequence migrations upgrade --provider migrations:migration head`
   so the package schema and catalog are finalized.
2. Attach account holdings through `msm.start_engine(...)`. When target
   positions can reference portfolios, attach `Portfolio` and
   `TargetPositionsStorage` through `msm_portfolios.start_engine(...)`.
3. Create or upsert the account model portfolio and account group, then create
   the account with `account_group_uid`.
4. Create the `AccountTargetPortfolio` relation for the account and model
   portfolio, then create a UTC `PositionSet` snapshot under that relation.
5. Build target-position rows with
   `msm_portfolios.services.build_target_positions_frame(...)` using
   `position_set.uid` as `position_set_uid`, and use `asset_uid` for direct
   asset targets or `portfolio_uid` for portfolio sleeve targets.
6. Build holdings rows with `build_account_holdings_frame(...)` and attach the
   real combined frame to `AccountHoldings` with `set_frame(...)`. For a single
   account, `set_account_holdings_frame(...)` is the convenience path.
7. Run the node and unpack the SDK result:
   `error_on_last_update, holdings_frame = holdings_node.run(...)`.
8. Pass only `holdings_frame` to `Account.pretty_print_positions(...)`.

See `examples/msm/accounts/account_workflow.py` for the full account path. By
default it chains `examples/msm_portfolios/portfolio_equal_weights_example.py`
to create a reusable portfolio sleeve, then creates the account group, two
accounts, canonical asset snapshots with ticker/name metadata, one shared
account model portfolio, account-owned target portfolio relationships, direct
asset plus portfolio `PositionSet` target-row publication, holdings
publication, and pretty-printed account positions.

## Pricing Instrument Identity

Use this workflow when connecting pricing terms to a canonical asset:

1. Persist or resolve the asset through `msm.api.assets.Asset`.
2. Store the asset-to-pricing relationship in pricing-owned persistence, keyed
   by the asset UID.
3. Keep `InstrumentModel` payloads limited to priceable terms. Do not include
   `main_sequence_asset_id`, `uid`, or `asset_uid` in serialized instrument
   terms.

This keeps instrument reconstruction independent from Main Sequence persistence
identity. The pricing details row decides which asset currently uses a given
serialized instrument definition. See
`examples/msm_pricing/instrument_identity_boundary.py` for a minimal payload
boundary example.

When the pricing persistence tables are needed, attach them through
`msm_pricing.bootstrap.attach_pricing_schemas(...)`. That startup flow includes
the core asset and index tables first, then pricing extension tables, and uses
the same direct backend attachment contract as `msm.start_engine(...)`.

Pricing bootstrap also seeds default market-data bindings for the built-in
pricing market-data set:

```text
PricingMarketDataSet(set_key="default")
  -> PricingMarketDataSetBinding(concept_key="discount_curves")
       data_node_uid = DiscountCurvesStorage.get_meta_table_uid()
  -> PricingMarketDataSetBinding(concept_key="interest_rate_index_fixings")
       data_node_uid = IndexFixingsStorage.get_meta_table_uid()
```

The binding row maps `(market_data_set_uid, concept_key)` to a backend DataNode
storage table UID. Use `msm_pricing.api.PricingMarketDataSet` and
`PricingMarketDataSetBinding` when an application needs an `eod`, `live`, or
`risk_manager` source set:

```python
from msm_pricing.api import PricingMarketDataSet, PricingMarketDataSetBinding
from msm_pricing.data_nodes.storage import DiscountCurvesStorage
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_MARKET_DATA_SET_EOD,
)

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

Pricing resolution looks up the active market-data set and concept, then reads
the resulting DataNode with `APIDataNode.build_from_table_uid(...)`. Public
workflows should bind storage table UIDs; identifiers are diagnostic only.
Callers select a non-default source set at valuation time:

```python
bond.price(market_data_set="eod")
bond.price(market_data_set="live")
```

The user-facing write and read path belongs to instrument classes:

```python
from msm_pricing import Instrument, ZeroCouponBond

bond = ZeroCouponBond(...)
bond.attach_to_asset(asset)

loaded = Instrument.load_from_asset(asset)
```

Use `Instrument.load_from_asset(asset)` when the asset is known but the concrete
pricing instrument is not. Use a typed loader such as
`ZeroCouponBond.load_from_asset(asset)` when the caller expects a specific
instrument family and wants a type check.

When an instrument references a market index, register the pricing registry rows
before publishing curve observations:

1. Register the canonical index type through `msm.api.indices.IndexType`.
   Fixed-income examples use the built-in `interest_rate` type.
2. Persist the canonical index through `msm.api.indices.Index`.
3. Upsert `msm_pricing.api.IndexConventionDetails` with the index UID and the
   serializable convention payload needed to rebuild the pricing index.
4. Upsert `msm_pricing.api.Curve` with a stable curve `unique_identifier`, the
   index UID, and curve construction metadata.
5. Publish curve observations through `DiscountCurvesNode` with
   `curve_identifier` set to the same curve `unique_identifier`.

See `examples/msm_pricing/pricing_registry_rows.py` for the row API workflow.

Serialized pricing instruments should reference these rows by UUID, not by
mutable names. Use `floating_rate_index_uid` on floating-rate bonds and
`float_leg_index_uid` on swaps. The runtime resolver turns those UUIDs into the
correct convention row, curve row, QuantLib index, curve, and fixing series.

For a full floating-rate bond workflow, use
`examples/msm_pricing/bond_pricing_example/`. It follows this order:

1. Register or resolve the bond asset type, issuer, currency asset, and bond
   asset through `msm.api.assets` and `msm.api.issuers`.
2. Register the `interest_rate` index type through `msm.api.indices.IndexType`,
   then register the canonical index through `msm.api.indices.Index`.
3. Upsert `IndexConventionDetails` and `Curve` rows under `msm_pricing.api`.
4. Publish one month of mock fixings through a `FixingRatesNode` subclass and a
   sampled flat-forward curve through a `DiscountCurvesNode` subclass. The
   pricing storage classes declare their EOD cadence as `__cadence__ = "1d"`.
5. Attach pricing storage tables, then upsert the `default` market-data set and
   its concept bindings with `PricingMarketDataSet` and
   `PricingMarketDataSetBinding`.
6. Create a `FloatingRateBond` with `floating_rate_index_uid=index.uid`.
7. Attach the instrument with `instrument.attach_to_asset(asset, ...)`.
8. Reload it generically with `Instrument.load_from_asset(asset)`, set the
   valuation date, then call `price(market_data_set="default")`,
   `analytics()`, `get_cashflows()`, and `carry_roll_down(...)`.

The reusable mock market-data components live in `examples/msm_pricing/utils/` so
the same curve and fixing DataNode extension pattern can be reused by swap
pricing examples.

## Markets MetaTable Models

Use this workflow when adding or reviewing a market-domain relational table:

1. Define the SQLAlchemy model under `msm.models` with
   `MarketsMetaTableMixin` and `MarketsBase`.
2. Set `__metatable_identifier__` to the stable table identity.
3. Put schema, table info, indexes, and constraints in `__table_args__`.
4. Do not set `__tablename__`; the markets mixin assigns the package-owned
   physical table name as `ms_markets__<lowercase-identity>`, with an
   `MSM_AUTO_REGISTER_NAMESPACE` suffix when configured before model import.
5. Add the model to `markets_sqlalchemy_models()` in foreign-key dependency
   order.
6. Generate or update a normal Alembic revision under the active namespace
   directory in `src/migrations/versions/`.
7. Use the SDK migration upgrade flow for schema/catalog mutation, then
   `msm.start_engine(...)` for runtime attachment. Do not call model
   `.register()` methods or local registration helpers from application code.

`msm.start_engine(...)` does not read the internal maintenance catalog during
runtime startup. It resolves selected tables by backend identifier using
`model.__table__.name`; it does not import or register missing tables.

Examples that use example-scoped platform-managed MetaTables must set
`MSM_AUTO_REGISTER_NAMESPACE=mainsequence.examples` before importing
MetaTable-backed `msm.api`, `msm.models`, or `msm.maintenance.models` modules,
then run explicit startup attachment. Row operations never register or attach
MetaTables on first use. A different namespace or registration configuration is
rejected for the already-initialized process.

Pass `models=[...]` to explicit preflight when a workflow only needs a subset of
tables, for example `msm.start_engine(models=["Asset"])`. Normal examples and
application code should use typed row classes such as
`msm.api.assets.Asset.upsert(...)`. Use `runtime.table(...)` and
`runtime.context` only for lower-level repository or service internals.

See `examples/msm/platform/inspect_markets_metatable_models.py` for a small offline
inspection example that prints the SDK-derived table names.

## Project-Local MetaTable Extensions

Use this workflow when an application owns a custom markets table that should be
cataloged with the same migration/finalization path as built-in tables:

1. Define the SQLAlchemy model with `MarketsMetaTableMixin` and `MarketsBase`.
2. Give it one stable `__metatable_identifier__`.
3. Declare relationships with normal SQLAlchemy `ForeignKey(...)` targets.
4. Add or sync the package/project migration that creates or refreshes the
   table and finalizes the catalog.
5. Attach at runtime with `msm.start_engine(models=[MyModelTable])`.
6. Put row operations in an optional `MarketsMetaTableRow` wrapper.

The `models=[...]` selector is the public runtime attachment boundary. It
expands foreign-key dependencies, verifies and attaches the selected SQLAlchemy
model through direct backend lookup, and binds the resolved backend
`MetaTable` object back to that model. Do not build a project-local UID map or call
row `create_schemas()` helpers as the extension mechanism.

For asset detail tables keyed by `AssetTable.uid`, expose `uid` as an alias of
`asset_uid` in the row wrapper while keeping the SQLAlchemy primary key on
`asset_uid`.

See `examples/msm/platform/custom_asset_details_extension.py` for a minimal
project-local asset detail table, row wrapper, and startup function.
