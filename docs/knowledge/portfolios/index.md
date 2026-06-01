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

- `msm.portfolios.models`: portfolio configuration models.
- `msm.portfolios.data_nodes`: canonical DataNodes for portfolios, portfolio
  weights, signal weights, storage initialization, and identity helpers.
- `msm.portfolios.rebalance_strategy`: rebalance strategy base classes and
  built-in strategies.
- `msm.models.portfolios`: SQLAlchemy MetaTable declarations for portfolio
  identity, portfolio asset details, and portfolio descriptive metadata.
- `msm.models.rebalancing` and `msm.models.signals`: SQLAlchemy MetaTable
  declarations for rebalance strategy metadata and signal metadata.
- `msm.api.portfolios`: typed row APIs for `Portfolio`,
  `PortfolioAssetDetail`, and `PortfolioMetadata`.
- `msm.api.market_metadata`: typed row APIs for `SignalMetadata` and
  `RebalanceStrategyMetadata`.
- `msm.services.portfolios`: service helpers for portfolio rows and portfolio
  asset details.
- `msm.portfolios.contrib`: contributed price and signal DataNodes.
- `msm.portfolios.utils`: shared portfolio utility functions.

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
from msm.api.portfolios import Portfolio

portfolio = Portfolio.upsert(
    unique_identifier="btc-eth-target",
    calendar_name="24/7",
)
```

`Portfolio.upsert(...)` is the first domain-specific multi-table row operation:
when an `asset_detail` payload is provided, it also upserts the
`PortfolioAssetDetail` row after the portfolio identity exists.

## Portfolio Registry Tables

Portfolio registry tables are regular platform-managed MetaTables. They describe
portfolio identity and relationships; they do not store historical portfolio
values. Historical values, weights, and signal outputs live in DataNode storage
tables.

Current portfolio SQLAlchemy declarations live under:

```text
src/msm/models/portfolios/
├── __init__.py
├── core.py       PortfolioTable, PortfolioAssetDetailTable
└── metadata.py   PortfolioMetadataTable
```

`PortfolioTable` is the canonical portfolio identity row. It is keyed by
`unique_identifier` and stores the optional portfolio index asset, DataNode UIDs
for canonical portfolio outputs, construction flags, stats, and metadata.

`PortfolioAssetDetailTable` is the one-to-one detail row for explicit portfolio
index asset linkage. It lets the portfolio point to an `AssetTable` row while
also keeping a denormalized asset unique identifier for lookup/display.

`PortfolioMetadataTable` is descriptive metadata keyed by portfolio
`unique_identifier`. It is intentionally not a foreign-key extension of
`PortfolioTable`; it is human-facing metadata that can be managed without
changing the portfolio identity row.

## Table Relationships

Portfolio identity and asset linkage:

```text
+-----------------------------+        optional index asset      +-----------------------------+
| PortfolioTable              |--------------------------------->| AssetTable                  |
|-----------------------------| portfolio_index_asset_uid       |-----------------------------|
| uid PK                      |                                  | uid PK                      |
| unique_identifier unique    |                                  | unique_identifier unique    |
| calendar_name               |                                  | asset_type                  |
| portfolio_*_data_node_uid   |                                  +-----------------------------+
| construction flags          |
| stats_json / metadata_json  |
+-----------------------------+
          |
          | 1 to 0..1, cascade on portfolio delete
          v
+-----------------------------+        optional canonical asset  +-----------------------------+
| PortfolioAssetDetailTable   |--------------------------------->| AssetTable                  |
|-----------------------------| asset_uid                       |-----------------------------|
| uid PK                      |                                  | uid PK                      |
| portfolio_uid unique FK     |                                  | unique_identifier unique    |
| asset_uid nullable FK       |                                  +-----------------------------+
| asset_unique_identifier     |
| metadata_json               |
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
| ExternalPrices              |------------------------------->| ExternalPricesStorage       |
+-----------------------------+                                +-----------------------------+
          DataNode update logic                                  PlatformTimeIndexMetaData
```

## Extension Notes

Add new portfolio construction configuration in `models`. Add reusable
DataNodes under `data_nodes` or `contrib`. Add rebalance logic under
`rebalance_strategy`. Add metadata persistence through `msm.models`,
`msm.repositories`, and `msm.services`.

## Related Concepts

- [Assets](../assets/index.md)
- [Execution](../execution/index.md)
- [Pricing](../pricing/index.md)
