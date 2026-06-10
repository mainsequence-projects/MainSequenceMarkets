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
`unique_identifier` and stores optional `published_index_uid` linkage to
`IndexTable`, plus DataNode UIDs for canonical portfolio outputs. A portfolio is
not an asset. The optional published index link is metadata for workflows that
want to expose the portfolio as an index-like observable; core portfolio
weights, values, account expansion, and virtual-fund allocation use
`PortfolioTable.uid` / `PortfolioTable.unique_identifier`.

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

Portfolio identity, calendar linkage, and optional published-index linkage:

```text
+-----------------------------+        optional published index  +-----------------------------+
| PortfolioTable              |--------------------------------->| IndexTable                  |
|-----------------------------| published_index_uid             |-----------------------------|
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

+-----------------------------+        required parent          +--------------------------------------+
| SignalMetadataTable         |<-------------------------------| SignalWeightsStorage                 |
|-----------------------------| signal_uid FK                  |--------------------------------------|
| uid PK                      |                                | time_index                           |
| signal_uid unique           |                                | signal_uid                           |
| signal_description          |                                | asset_identifier                     |
+-----------------------------+                                +--------------------------------------+
```

`PortfoliosStorage.portfolio_identifier` references
`PortfolioTable.unique_identifier`; portfolio value rows must be written for a
real portfolio identity. `PortfoliosDataNode` resolves this value from the
attached `PortfolioTable` row or from the explicit runtime identifier before
normalizing rows.

Portfolio construction depends on a real price source, but portfolio logic does
not own price ingestion. Example workflows publish normalized OHLCV bars to
`ExternalPricesStorage` only so the example is self-contained. Production users
can point portfolio configurations at any registered compatible price storage
table, including one produced by another library, vendor connector, or project
DataNode.

## Price Source Resolution

Portfolio prices are not stored on `PortfolioTable`. They are provided by the
portfolio build configuration and consumed through DataNode dependencies.

The current portfolio path is explicit:

```text
+-----------------------------+       writes        +-----------------------------+
| source price DataNode       |-------------------->| source price storage        |
| e.g. ExampleDailyBars       |                     | ExternalPricesStorage       |
+--------------+--------------+                     +--------------+--------------+
               |                                                   |
               | explicit upstream dependency                      | APIDataNode lookup
               v                                                   v
+-----------------------------+       writes        +-----------------------------+
| InterpolatedPrices          |-------------------->| configured price storage    |
| optional price workflow     |                     | InterpolatedPricesStorage   |
+--------------+--------------+                     +--------------+--------------+
               |                                                   |
               | explicit portfolio dependency                     | reads
               +--------------------------+------------------------+
                                          v
                             +-----------------------------+
                             | PortfoliosDataNode          |
                             | portfolio calculation       |
                             +-----------------------------+
```

`PortfolioBuildConfiguration.price_source_instance` receives the price source
that portfolio construction consumes. The price source may be an
`InterpolatedPrices` instance, another DataNode, or an `APIDataNode` pointing at
compatible registered storage. The price source must expose rows keyed by
`(time_index, asset_identifier)` and include the configured price column, for
example `close`. `ImmediateSignal` does not require source volume; it writes
empty volume fields in portfolio-weight output when the consumed price source
does not provide volume. Volume-aware rebalance strategies, such as
`VolumeParticipation`, still require volume explicitly.

This producer boundary is intentional. Price collection, normalization, vendor
mapping, and connector-specific scheduling are separate concerns from portfolio
construction. Portfolio extensions should focus on universe selection, signals,
rebalancing, execution assumptions, and portfolio output storage. They should
consume a registered price storage contract instead of importing or constructing
the price producer that wrote it.

If persistent interpolation is needed, `InterpolatedPrices` is built before the
portfolio and then passed into `PortfolioBuildConfiguration` like any other
dependency. `InterpolatedPricesConfig` accepts either `source_price_instance`
or `source_time_index_meta_table_uid`. Use `source_price_instance` when the
source price `DataNode` or `APIDataNode` is already part of the graph. Use
`source_time_index_meta_table_uid` when attaching an already registered
compatible source table through `APIDataNode.build_from_table_uid(...)`.
`InterpolatedPrices` validates the registered source cadence, exposes the
resolved source from `dependencies()`, and writes the configured interpolation
output.

The interpolation policy is storage identity, not row metadata.
`InterpolatedPrices` builds a configured storage class whose
`__metatable_extra_hash_components__` include the source `TimeIndexMetaTable`
UID, the source table cadence, `upsample_frequency_id`, and
`intraday_bar_interpolation_rule`; those components determine the configured
physical table identity. The rows keep the normal price-bar grain
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
`ExternalPricesStorage` UID and cadence metadata, builds the
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

`PortfolioBuildConfiguration.price_column` chooses which column from the
explicit price source drives portfolio returns. For example,
`PriceTypeNames.CLOSE` uses the `close` column. `PortfoliosDataNode` may locally
align the consumed price frame to the rebalance index for calculation, but it
does not create persistent interpolation storage and does not hide an upstream
DataNode.

When a portfolio value series is already ahead of the usable price-source
coverage, `PortfoliosDataNode` treats the update as an exhausted window and
returns no new rows before asking the rebalance calendar for a schedule. This
keeps calendar validation strict while making repeated or forced portfolio runs
idempotent when upstream prices have not advanced.

In code, the important wiring is:

```python
source_bars_node = ExampleDailyBars(asset_identifiers=["asset-btc", "asset-eth"])
source_bars_node.run(debug_mode=True, update_tree=False, force_update=True)

price_source = InterpolatedPrices(
    interpolation_config=InterpolatedPricesConfig(
        asset_list=["asset-btc", "asset-eth"],
        intraday_bar_interpolation_rule="ffill",
        source_price_instance=source_bars_node,
        upsample_frequency_id="1d",
    )
)

signal_weights = FixedWeights.from_signal_configuration(...)

portfolio_configuration = PortfolioConfiguration(
    portfolio_build_configuration=PortfolioBuildConfiguration(
        price_source_instance=price_source,
        price_column=PriceTypeNames.CLOSE,
        portfolio_prices_frequency="1d",
        execution_configuration=PortfolioExecutionConfiguration(...),
        backtesting_weights_configuration=BacktestingWeightsConfig(
            signal_weights_instance=signal_weights,
            rebalance_strategy_instance=ImmediateSignal(...),
        ),
    ),
    portfolio_markets_configuration=PortfolioMarketsConfig(...),
)
```

`PortfoliosDataNode.dependencies()` exposes the signal node and the explicit
price source. Price sources may contain more assets than the signal requires;
portfolio calculation filters to the signal-required asset subset and reports
missing required assets when the consumed price source does not cover them.
The portfolio update window is also scoped to the assets the portfolio needs:
the signal preflight universe, any previous portfolio-weight assets that still
need valuation or liquidation, and any explicit portfolio value override asset.
It does not use unrelated assets present in the source price table when deciding
the usable source-data end timestamp. If the workflow cannot determine that
asset scope before deriving the source-data window, it fails instead of falling
back to table-wide price-source progress.

Existing portfolio output progress is scoped by `portfolio_identifier` because
`PortfoliosStorage` is keyed by `(time_index, portfolio_identifier)`. A later
row for another portfolio in the shared storage table must not move this
portfolio's start date; if this portfolio has no progress entry, the workflow
treats it as a fresh portfolio rather than using the table-wide maximum.

Signal output progress is scoped by `signal_uid` because `SignalWeightsStorage`
is keyed by `(time_index, signal_uid, asset_identifier)`. `signal_uid` is a
required reference to `SignalMetadataTable.signal_uid`, so signal metadata must
be registered before signal-weight rows are published. Contributed signal nodes
must read progress under their own `signal_uid`; a later row from another
signal in the shared table must not shorten this signal's source-data window.

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

## Portfolio Construction And Account Virtual-Fund Allocation Boundary

Portfolio construction produces portfolio artifacts. It does not own
virtual-fund identity, and it does not write virtual-fund allocation rows.
Virtual funds are account-owned allocation views that target a portfolio after
that portfolio exists. Their canonical docs live in core
[`msm` account virtual funds](../../msm/accounts/virtual_funds.md).

```text
Portfolio construction produces portfolio artifacts.
It does not own virtual-fund identity and it does not connect directly to
virtual-fund allocation rows.

+------------------+       +------------------+       +------------------+
| Price DataNodes  |       | Signal DataNodes |       | Rebalance Logic  |
+--------+---------+       +--------+---------+       +--------+---------+
         \                          |                          /
          \                         |                         /
           v                        v                        v
        +---------------------------------------------------------+
        | Portfolio construction                                  |
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
        | - optional published_index_uid -> IndexTable.uid        |
        +---------------------------------------------------------+
```

`PortfoliosDataNode.run(..., update_pointers=True)` updates the
`PortfolioTable` DataNode pointer fields after the portfolio graph has
published. This is enabled by default for portfolio-configuration runs, so
examples and callers do not need to manually re-upsert the portfolio row after
execution. Pass `update_pointers=False` only when deliberately running the graph
without updating portfolio registry links.

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
- `VirtualFundTable` is core `msm` account-allocation state that binds an
  account to a target portfolio.
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
`portfolio_identifier` for portfolio value rows and portfolio weight rows. The
`portfolio_identifier` value is `PortfolioTable.unique_identifier`; for
portfolio values this is enforced by the `PortfoliosStorage` foreign key. It
does not require a linked `IndexTable` row.

See `examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py` for the
schema-preparation stage and
`examples/msm_portfolios/portfolio_equal_weights_run.py` for the normal
portfolio run. The reusable implementation lives in
`examples/msm_portfolios/portfolio_equal_weights_example.py`; it reuses the
shared crypto `Asset` example rows, creates or reuses a `CRYPTO_24_7` calendar
from `pandas_market_calendars`, publishes example OHLCV bars to
`ExternalPricesStorage`, interpolates those prices, runs
`SignalWeights`, `PortfolioWeights`, and `PortfoliosDataNode`, and upserts the
`Portfolio` row with `calendar_uid` plus the published DataNode update UIDs.
The example narrates each setup, source-price
publication, and portfolio step so terminal output explains what was created.
It does not create virtual funds or virtual-fund allocation rows; those require
an explicit account funding policy and belong in the core account
virtual-funds workflow.

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
- [Virtual Funds](../../msm/accounts/virtual_funds.md)
- [Execution](../../msm/execution/index.md)
- [Pricing](../../msm_pricing/index.md)
