# Portfolios

The portfolios concept owns portfolio construction workflows. It connects
assets, signals, rebalance strategies, portfolio weights,
portfolio metadata, and portfolio value time series.

## Scope

Portfolios answer these questions:

- Which assets are eligible for a portfolio?
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
- `msm_portfolios.models.portfolios`: SQLAlchemy MetaTable declarations for
  portfolio identity and portfolio descriptive metadata.
- `msm_portfolios.models.rebalancing` and `msm_portfolios.models.signals`:
  SQLAlchemy MetaTable declarations for rebalance strategy metadata and signal
  metadata.
- `msm_portfolios.api.portfolios`: typed row APIs for `Portfolio` and
  `PortfolioMetadata`.
- `msm_portfolios.api.market_metadata`: typed row APIs for `SignalMetadata` and
  `RebalanceStrategyMetadata`.
- `msm_portfolios.services.portfolios`: service helpers for portfolio rows.
- `msm_portfolios.contrib`: contributed price and signal DataNodes.
- `msm_portfolios.utils`: shared portfolio utility functions.

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
import msm_portfolios

from msm_portfolios.api.portfolios import Portfolio

msm_portfolios.start_engine(models=["Portfolio"])

portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_name="24/7",
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

Current portfolio SQLAlchemy declarations live under:

```text
src/msm_portfolios/models/portfolios/
├── __init__.py
├── core.py       PortfolioTable
└── metadata.py   PortfolioMetadataTable
```

`PortfolioTable` is the canonical portfolio identity row. It is keyed by
`unique_identifier` and stores optional `portfolio_index_uid` linkage to
`IndexTable`, plus DataNode UIDs for canonical portfolio outputs. A portfolio is
not an asset; optional index publication uses a core index row.

`PortfolioMetadataTable` is descriptive metadata keyed by portfolio
`unique_identifier`. It is intentionally not a foreign-key extension of
`PortfolioTable`; it is human-facing metadata that can be managed without
changing the portfolio identity row.

## Table Relationships

Portfolio identity and DataNode/index linkage:

```text
+-----------------------------+        optional portfolio index  +-----------------------------+
| PortfolioTable              |--------------------------------->| IndexTable                  |
|-----------------------------| portfolio_index_uid             |-----------------------------|
| uid PK                      |                                  | uid PK                      |
| unique_identifier unique    |                                  | unique_identifier unique    |
| calendar_name               |                                  | index_type                  |
| portfolio_weights_data_node_uid |--> PortfolioWeights           | display_name                |
| signal_weights_data_node_uid    |--> SignalWeights              +-----------------------------+
| portfolio_data_node_uid         |--> PortfoliosDataNode
| backtest_table_price_column_name|
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
+-----------------------------+             writes             +-----------------------------+
| PortfolioWeights            |------------------------------->| PortfolioWeightsStorage     |
| SignalWeights               |------------------------------->| SignalWeightsStorage        |
| PortfoliosDataNode          |------------------------------->| PortfoliosStorage           |
| InterpolatedPrices          |------------------------------->| InterpolatedPricesStorage   |
+-----------------------------+                                +-----------------------------+
          DataNode update logic                                  PlatformTimeIndexMetaData
```

See `examples/msm_portfolios/portfolio_equal_weights_example.py` for the
end-to-end workflow that creates the portfolio `Index`, prepares
`SignalWeights`, `PortfolioWeights`, and `PortfoliosDataNode`, and upserts the
`Portfolio` row with `portfolio_index_uid` plus the three DataNode storage UIDs.

## Extension Notes

Add new portfolio construction configuration in `msm_portfolios.configuration`.
Add reusable DataNodes under `msm_portfolios.data_nodes` or
`msm_portfolios.contrib`. Add rebalance logic under
`msm_portfolios.rebalance_strategy`. Add portfolio metadata persistence through
`msm_portfolios.models`, `msm_portfolios.repositories`, and
`msm_portfolios.services`.

## Related Concepts

- [Assets](../../msm/assets/index.md)
- [Execution](../../msm/execution/index.md)
- [Pricing](../../msm_pricing/index.md)
