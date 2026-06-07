# Portfolios

The portfolios concept owns portfolio construction workflows. It connects
assets, signals, rebalance strategies, portfolio weights,
portfolio metadata, and portfolio value time series.

## Scope

Portfolios answer these questions:

- Which assets are eligible for a portfolio?
- Which price source provides bars for those assets?
- Which signals produce target weights?
- Which rebalance strategy converts signals into portfolio weights?
- Which DataNodes store canonical portfolio values, signal weights, and
  portfolio weights?
- Which metadata identifies portfolios, signals, and rebalance strategies?

## Primary Modules

- `msm_portfolios.configuration`: portfolio configuration models.
- `msm_portfolios.data_nodes`: canonical DataNodes for portfolios, portfolio
  weights, signal weights, storage initialization, and identity helpers.
- `msm_portfolios.rebalance_strategy`: rebalance strategy base classes and
  built-in strategies.
- `msm.models.portfolios`: core SQLAlchemy MetaTable declaration for portfolio
  identity/reference data.
- `msm_portfolios.models.portfolios`: SQLAlchemy MetaTable declarations for
  portfolio descriptive metadata.
- `msm_portfolios.models.rebalancing` and `msm_portfolios.models.signals`:
  SQLAlchemy MetaTable declarations for rebalance strategy metadata and signal
  metadata.
- `msm.api.portfolios`: typed row API for core `Portfolio` identity rows.
- `msm_portfolios.api.portfolios`: typed row API for `PortfolioMetadata`.
- `msm_portfolios.api.market_metadata`: typed row APIs for `SignalMetadata` and
  `RebalanceStrategyMetadata`.
- `msm.services.portfolios`: service helpers for portfolio identity rows.
- `msm_portfolios.contrib`: contributed price and signal DataNodes.
- `msm_portfolios.utils`: small shared logging and time constants only.
- `msm_portfolios.contrib.signals.regression_utils`: regression helpers used by
  contributed replicator-style signals.

## Key Contracts

Portfolio DataNodes use canonical time-indexed frames. Portfolio identity should
be deterministic: configuration hashes and signal/rebalance UIDs must be stable
for equivalent configuration payloads.

Canonical markets DataNodes derive their published identifiers from the same
rule as MetaTables: the default markets namespace keeps bare logical
identifiers, while a non-default `MSM_AUTO_REGISTER_NAMESPACE` prefixes them.
That namespace also becomes the default DataNode `hash_namespace`. Pass an
explicit namespace only for isolated tests or experiments.

Forward-fill behavior, price source selection, signal semantics, and rebalance
frequency should be explicit in configuration rather than inferred from data.

Use the typed row API for registry records:

```python
import msm

from msm.api.calendars import Calendar
from msm.api.portfolios import Portfolio

msm.start_engine(models=["Calendar", "CalendarDate", "CalendarSession", "Portfolio"])

calendar = Calendar.create_from_pandas_calendar(
    source_identifier="24/7",
    unique_identifier="CRYPTO_24_7",
    display_name="Crypto 24/7",
    valid_from="2026-05-25",
    valid_to="2026-05-25",
    timezone="UTC",
)

portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_uid=calendar.uid,
    calendar_name=calendar.unique_identifier,
)
```

`Portfolio.upsert(...)` writes only the portfolio identity row. Portfolio
constituents, weights, values, and optional index publication are separate
portfolio workflows.

## Portfolio Registry Tables

Portfolio registry tables are regular platform-managed MetaTables. They describe
portfolio identity and relationships; they do not store historical portfolio
values. Historical values, weights, and signal outputs live in DataNode storage
tables.

Portfolio identity is core reference data and lives under:

```text
src/msm/models/portfolios/
├── __init__.py
└── core.py       PortfolioTable
```

`PortfolioTable` is the canonical portfolio identity row. It is keyed by
`unique_identifier` and stores optional `portfolio_index_uid` linkage to
`IndexTable`, plus DataNode UIDs for canonical portfolio outputs. A portfolio is
not an asset; optional index publication uses a core index row.

Portfolio descriptive metadata remains in `msm_portfolios`:

```text
src/msm_portfolios/models/portfolios/
├── __init__.py
└── metadata.py   PortfolioMetadataTable
```

`PortfolioMetadataTable` is descriptive metadata keyed by portfolio
`unique_identifier`. It is intentionally not a foreign-key extension of
`PortfolioTable`; it is human-facing metadata that can be managed without
changing the portfolio identity row.

Rebalance strategy calendar keys resolve persisted core `CalendarTable` rows
first. Legacy pandas-market calendar keys remain a fallback path, but durable
portfolio records should use `PortfolioTable.calendar_uid`.

## Table Relationships

Portfolio identity, calendar linkage, and DataNode/index linkage:

```text
+-----------------------------+        optional portfolio index  +-----------------------------+
| PortfolioTable              |--------------------------------->| IndexTable                  |
|-----------------------------| portfolio_index_uid             |-----------------------------|
| uid PK                      |                                  | uid PK                      |
| unique_identifier unique    |                                  | unique_identifier unique    |
| calendar_uid FK ------------+----+                             | index_type                  |
| calendar_name deprecated    |    |                             | display_name                |
| portfolio_weights_data_node_uid |--> PortfolioWeights           +-----------------------------+
| signal_weights_data_node_uid    |--> SignalWeights
| portfolio_data_node_uid         |--> PortfoliosDataNode
| backtest_table_price_column_name|
+-----------------------------+
                                  |
                                  | durable calendar relationship
                                  v
                         +-----------------------------+
                         | CalendarTable               |
                         |-----------------------------|
                         | uid PK                      |
                         | unique_identifier unique    |
                         | valid_from / valid_to       |
                         +-----------------------------+
```

Portfolio metadata is a separate descriptive table:

```text
+-----------------------------+              same logical key              +-----------------------------+
| PortfolioTable              |------------------------------------------->| PortfolioMetadataTable      |
|-----------------------------| unique_identifier by convention           |-----------------------------|
| uid PK                      |              no database FK                | uid PK                      |
| unique_identifier unique    |                                           | unique_identifier unique    |
| registry/config fields      |                                           | description                 |
+-----------------------------+                                           +-----------------------------+
```

Portfolio DataNode storage is separate from registry MetaTables. These storage
classes are registered through the same catalog bootstrap, after their FK target
MetaTables:

```text
+-----------------------------+             writes             +--------------------------------------+
| PortfolioWeights            |------------------------------->| PortfolioWeightsStorage              |
| SignalWeights               |------------------------------->| SignalWeightsStorage                 |
| PortfoliosDataNode          |------------------------------->| PortfoliosStorage                    |
| External price DataNodes    |------------------------------->| ExternalPricesStorage                |
| InterpolatedPrices          |------------------------------->| configured InterpolatedPricesStorage |
+-----------------------------+                                +--------------------------------------+
          DataNode update logic                                  PlatformTimeIndexMetaTable
```

Portfolio construction depends on a real price source, but portfolio logic does
not own price ingestion. Example workflows publish normalized OHLCV bars to
`ExternalPricesStorage` only so the example is self-contained. Production users
can point portfolio configurations at any registered compatible price storage
table, including one produced by another library, vendor connector, or project
DataNode.

## Price Source Resolution

Portfolio prices are not stored on `PortfolioTable`. They are provided by the
portfolio build configuration and consumed through DataNode dependencies.

The price path is:

```text
+--------------------------------------+       resolves UID       +--------------------------+
| PricesConfiguration                  |------------------------->| APIDataNode              |
|--------------------------------------|                          |--------------------------|
| source_time_index_meta_table_uid     |                          | build_from_table_uid(...)|
| upsample_frequency_id                |                                       |
| interpolation rule                   |                                       | reads
+------------------+-------------------+                                       v
                   |                                            +--------------------------+
                   |                                            | registered source bars   |
                   |                                            | storage contract         |
                   |                                            | time_indexed_profile     |
                   |                                            | cadence                  |
                   |                                            | time_index               |
                   |                                            | asset_identifier         |
                   |                                            | open/high/low/close/...  |
                   |                                            +-------------+------------+
                   |                                                          ^
                   |                                                          | writes
                   v                                                          |
+--------------------------------------+                         +-------------+------------+
| InterpolatedPrices                   |                         | source price DataNode    |
| owner: msm_portfolios                |                         | outside portfolio config |
+------------------+-------------------+                         +--------------------------+
                   |
                   | writes
                   v
+--------------------------------------+
| Configured InterpolatedPricesStorage |
| table name = configured storage hash |
| row grain: time_index, asset_identifier |
| open/high/low/close/...              |
+------------------+-------------------+
                   |
                   | consumed by
                   v
+--------------------------------------+
| PortfoliosDataNode                   |
| computes portfolio value             |
+--------------------------------------+
```

`PricesConfiguration` stores the source bars storage UID, not the producer
DataNode instance and not a DataNodeUpdate UID. The source must be a registered
`PlatformTimeIndexMetaTable` that exposes normalized OHLCV bars keyed by
`(time_index, asset_identifier)` and declares its raw bar cadence through
backend TimeIndexMetaTable cadence metadata. `InterpolatedPrices` resolves that
UID through `APIDataNode.build_from_table_uid(...)`, validates that the
registered source exposes cadence, and uses that cadence as the source bar
frequency. The portfolio can recover the source across processes and does not
require the original producer class to be present.

This producer boundary is intentional. Price collection, normalization, vendor
mapping, and connector-specific scheduling are separate concerns from portfolio
construction. Portfolio extensions should focus on universe selection, signals,
rebalancing, execution assumptions, and portfolio output storage. They should
consume a registered price storage contract instead of importing or constructing
the price producer that wrote it.

The interpolation policy is storage identity, not row metadata. `InterpolatedPrices`
builds a configured storage class whose `__metatable_extra_hash_components__`
include the source storage hash, the source table cadence,
`upsample_frequency_id`, and `intraday_bar_interpolation_rule`; the configured
storage hash becomes the physical table name. The rows keep the normal price-bar grain
`(time_index, asset_identifier)`. The policy values are not repeated on every
price row.

Configured interpolation storage is a dynamic schema artifact. It is derived
from a real registered source price storage table and a concrete interpolation
policy, so it is not part of the package-wide static `start_engine(...)` model
list. Prepare it before the normal portfolio run:

```bash
python examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py
python examples/msm_portfolios/portfolio_equal_weights_run.py
```

The preparation step attaches the static schema, reads the registered
`ExternalPricesStorage` `storage_hash` and cadence metadata, builds the
configured `InterpolatedPricesStorage` class, and uses the active migration
namespace from the SDK migration provider to find or generate the real dynamic
Alembic revision. It then runs the dynamic provider upgrade before any portfolio
DataNode writes, even when a stale `TimeIndexMetaTable` metadata row already
exists. Metadata alone is not considered schema preparation; the physical table
must be created by the migration flow. If an older registered
`ExternalPricesStorage` row is missing cadence metadata, the preparation script
patches that metadata to the model-declared cadence before deriving the dynamic
table. Runtime portfolio code then uses the registered table; it does not
create or migrate dynamic storage.

`AssetsConfiguration.price_type` chooses which column from the interpolated
price table drives portfolio returns. For example, `PriceTypeNames.CLOSE` uses
the `close` column. The source table cadence, `upsample_frequency_id`, and
`intraday_bar_interpolation_rule` control how `InterpolatedPrices` shapes the
source bars before `PortfoliosDataNode` calculates returns. Users do not pass a
separate source bar frequency in `PricesConfiguration`.

In code, the important wiring is:

```python
source_bars_node = ExampleDailyBars(asset_identifiers=["asset-btc", "asset-eth"])
source_bars_node.run(debug_mode=True, update_tree=False, force_update=True)

assets_configuration = AssetsConfiguration(
    asset_list=["asset-btc", "asset-eth"],
    price_type=PriceTypeNames.CLOSE,
    prices_configuration=PricesConfiguration(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_time_index_meta_table_uid=runtime.table(
            ExternalPricesStorage
        ).meta_table_uid,
    ),
)
```

`PortfoliosDataNode` creates its `InterpolatedPrices` dependency from that
`AssetsConfiguration`; users should not manually attach portfolio value frames
for normal construction workflows.

## Account Target-Position Exposure To Portfolios

Account allocation registry rows remain core `msm` account concepts:
`AccountAllocationModelTable`, `AccountTargetAllocationTable`, and
`PositionSetTable`. The timestamped target exposure rows that can reference a
constructed portfolio are also core account allocation storage. They live in
`msm.data_nodes.accounts.storage.TargetPositionsStorage`; portfolio workflows may read or
expand them, but they do not own the table.

```text
+-----------------------------+       position_set_uid       +-----------------------------+
| PositionSetTable            |<-----------------------------| TargetPositionsStorage      |
| owner: msm                  |                              | owner: msm                  |
|-----------------------------|                              |-----------------------------|
| uid PK                      |                              | time_index                  |
| account_target_allocation_uid|                              | target_type                 |
| position_set_time UTC       |                              | target_uid                  |
+-----------------------------+                              | asset_uid nullable FK       |
                                                               | portfolio_uid nullable FK   |
                                                               | exposure columns            |
                                                               +-------------+---------------+
                                                                             |
                                                                             | portfolio_uid
                                                                             v
                                                               +-----------------------------+
                                                               | PortfolioTable              |
                                                               | owner: msm                  |
                                                               | uid PK                      |
                                                               | unique_identifier unique    |
                                                               +-----------------------------+
```

A target row has exactly one target:

```text
target_type = asset
  target_uid = asset_uid
  asset_uid -> AssetTable.uid

target_type = portfolio
  target_uid = portfolio_uid
  portfolio_uid -> PortfolioTable.uid
```

Portfolio target rows are mandate exposure, not custody holdings and not
portfolio indices. They are expanded into asset-level exposure only when a
downstream workflow explicitly calls the portfolio expansion service and
provides a resolver for current portfolio weights.

## Portfolio Construction And Virtual Fund Allocation Relationships

Portfolio construction produces portfolio artifacts. It does not own
virtual-fund identity, and it does not write virtual-fund allocation rows.
Virtual funds are account-owned allocation views that target a portfolio after
that portfolio exists.

```text
Virtual Fund Builder / portfolio construction produces portfolio artifacts.
It does not own virtual-fund identity and it does not connect directly to
virtual-fund allocation rows.

+------------------+       +------------------+       +------------------+
| Price DataNodes  |       | Signal DataNodes |       | Rebalance Logic  |
+--------+---------+       +--------+---------+       +--------+---------+
         \                          |                          /
          \                         |                         /
           v                        v                        v
        +---------------------------------------------------------+
        | Portfolio construction / VFB                            |
        | - computes signal weights, portfolio weights, values    |
        | - writes portfolio DataNode outputs                     |
        +---------------------------+-----------------------------+
                                    |
                                    v
+-------------------------+   +-------------------------+   +-------------------------+
| SignalWeights           |   | PortfolioWeights        |   | PortfoliosDataNode      |
| DataNode                |   | DataNode                |   | DataNode                |
+------------+------------+   +------------+------------+   +------------+------------+
             |                             |                             |
             v                             v                             v
+-------------------------+   +-------------------------+   +-------------------------+
| SignalWeightsStorage    |   | PortfolioWeightsStorage |   | PortfoliosStorage       |
| PlatformTimeIndexMeta   |   | PlatformTimeIndexMeta   |   | PlatformTimeIndexMeta   |
+------------+------------+   +------------+------------+   +------------+------------+
             |                             |                             |
             | DataNodeUpdate UID          | DataNodeUpdate UID          | DataNodeUpdate UID
             +-----------------------------+-----------------------------+
                                           |
                                           v
        +---------------------------------------------------------+
        | PortfolioTable                                          |
        | - portfolio identity                                    |
        | - signal_weights_data_node_uid                          |
        | - portfolio_weights_data_node_uid                       |
        | - portfolio_data_node_uid                               |
        | - optional portfolio_index_uid -> IndexTable.uid        |
        +---------------------------------------------------------+
```

Virtual-fund allocation is a separate relationship over account holdings and a
target portfolio:

```text
+---------------------+        target_portfolio_uid        +---------------------+
| PortfolioTable      |<-----------------------------------| VirtualFundTable    |
| portfolio identity  |                                    | allocation identity |
+---------------------+                                    | account_uid         |
                                                           +----------+----------+
                                                                      |
                                                                      | account_uid
                                                                      v
+---------------------+        account_uid                +---------------------+
| AccountTable        |<-----------------------------------| AccountHoldingsSet |
| custody account     |                                    | source snapshot    |
+---------------------+                                    +----------+----------+
                                                                      |
                                                                      | source_account_holdings_set_uid
                                                                      v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsSetTable |
                                                           | allocation set identity     |
                                                           +-------------+---------------+
                                                                         |
                                                                         v
                                                           +-----------------------------+
                                                           | VirtualFundHoldingsStorage  |
                                                           | allocated_quantity          |
                                                           | direction                   |
                                                           | asset_identifier -> Asset   |
                                                           +-----------------------------+
```

The boundary is intentional:

- `PortfolioTable` identifies the portfolio and points at portfolio output
  storage.
- `VirtualFundTable` binds an account to a target portfolio.
- `AccountHoldingsSetTable` is the source account snapshot.
- `VirtualFundHoldingsSetTable` records one allocation view from one source
  holdings set.
- `VirtualFundHoldingsStorage` stores allocated exposure rows, not custody.

Virtual funds are not assets. They should not appear as synthetic rows in
`AccountHoldingsStorage`; account-level virtual-fund exposure is reconstructed
from `VirtualFundTable`, `VirtualFundHoldingsSetTable`, and
`VirtualFundHoldingsStorage`.

Storage dimensions use explicit names instead of reusing bare
`unique_identifier`: `asset_identifier` for asset-keyed rows,
`portfolio_identifier` for portfolio value rows, and
`portfolio_index_identifier` for portfolio index publication rows. These
columns still point to the corresponding MetaTable `unique_identifier` values
where a source-table foreign key exists.

See `examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` for the
schema-preparation stage and
`examples/msm_portfolios/portfolio_equal_weights_run.py` for the normal
portfolio run. The reusable implementation lives in
`examples/msm_portfolios/portfolio_equal_weights_example.py`; it reuses the
shared crypto `Asset` example rows, creates or reuses a `CRYPTO_24_7` calendar
from `pandas_market_calendars`, creates the portfolio `Index`, publishes
example OHLCV bars to `ExternalPricesStorage`, interpolates those prices, runs
`SignalWeights`, `PortfolioWeights`, and `PortfoliosDataNode`, and upserts the
`Portfolio` row with `calendar_uid`, `portfolio_index_uid`, plus the published
DataNode update UIDs. The example narrates each setup, source-price
publication, and portfolio step so terminal output explains what was created.
It does not create virtual funds or virtual-fund allocation rows; those require
an explicit account funding policy and belong in the virtual-funds workflow.

## Extension Notes

Add new portfolio construction configuration in `msm_portfolios.configuration`.
Add reusable DataNodes under `msm_portfolios.data_nodes` or
`msm_portfolios.contrib`. Add rebalance logic under
`msm_portfolios.rebalance_strategy`. Add portfolio identity persistence through
core `msm.models`, `msm.repositories`, `msm.services`, and `msm.api`. Add
portfolio metadata persistence through `msm_portfolios.models` and
`msm_portfolios.api`.

## Related Concepts

- [Assets](../../msm/assets/index.md)
- [Execution](../../msm/execution/index.md)
- [Pricing](../../msm_pricing/index.md)
