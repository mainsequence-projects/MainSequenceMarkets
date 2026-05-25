# Portfolios

The portfolios concept owns portfolio construction and Virtual Fund Builder
workflows. It connects assets, signals, rebalance strategies, portfolio weights,
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

- `msm.portfolios.models`: portfolio and VFB configuration models.
- `msm.portfolios.data_nodes`: canonical DataNodes for portfolios, portfolio
  weights, signal weights, storage initialization, and identity helpers.
- `msm.portfolios.rebalance_strategy`: rebalance strategy base classes and
  built-in strategies.
- `msm.models.portfolios`, `msm.models.rebalancing`, and `msm.models.signals`:
  SQLAlchemy models for portfolio metadata, rebalance metadata, and signal
  metadata.
- `msm.services.portfolios`: service helpers for portfolio rows and portfolio
  asset details.
- `msm.portfolios.contrib`: contributed price and signal DataNodes.
- `msm.portfolios.utils`: shared portfolio utility functions.

## Key Contracts

Portfolio DataNodes use canonical time-indexed frames. Portfolio identity should
be deterministic: configuration hashes and signal/rebalance UIDs must be stable
for equivalent configuration payloads.

Forward-fill behavior, price source selection, signal semantics, and rebalance
frequency should be explicit in configuration rather than inferred from data.

## Extension Notes

Add new portfolio construction configuration in `models`. Add reusable
DataNodes under `data_nodes` or `contrib`. Add rebalance logic under
`rebalance_strategy`. Add metadata persistence through `msm.models`,
`msm.repositories`, and `msm.services`.

## Related Concepts

- [Assets](../assets/index.md)
- [Accounts](../accounts/index.md)
- [Execution](../execution/index.md)
- [Pricing](../pricing/index.md)
