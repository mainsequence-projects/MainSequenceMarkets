# Client

`msm.client` is no longer a market-domain runtime surface. Market domain code
should use SQLAlchemy models, compiled MetaTable repository operations, service
helpers, and DataNodes directly.

## Scope

The package is reserved for future generic helpers only. It must not contain
market DTOs that query platform endpoints, lazy constants, or object methods
that create/update market records.

Current market runtime boundaries are:

- `msm.models`: SQLAlchemy model definitions and MetaTable contracts.
- `msm.repositories`: compiled SQL operation builders for MetaTable execution.
- `msm.services`: workflow helpers built on repository operations and DataNode
  contracts.
- `msm.data_nodes.accounts`, `msm.data_nodes.assets`,
  `msm.data_nodes.execution`, and `msm.data_nodes.indices`: concept-specific
  DataNode modules. Shared asset-indexed behavior lives in
  `msm.data_nodes.assets.asset_indexed`.
- `msm.data_nodes.utils`: shared DataNode support code that is not a model
  concept package.

## Removed Runtime Surface

The old client model package has been removed from production runtime paths.
Code should not import `msm.client.models` or expect market objects to expose
active `.get()`, `.filter()`, `.create()`, or `.update()` methods.

Resolve market data through MetaTable services or pass explicit runtime objects
into DataNodes. For example, category-based portfolio code should resolve the
category membership through `msm.services.asset_categories` and pass the
resulting `asset_list` into the portfolio or price configuration.

## Extension Notes

Do not add market-domain persistence to `msm.client`. New market records belong
in `msm.models`, new compiled operations belong in `msm.repositories`, and
workflow orchestration belongs in `msm.services`.

## Related Concepts

- [Assets](../assets/index.md)
- [Models](../models/index.md)
- [Pricing](../../msm_pricing/index.md)
- [Repositories](../repositories/index.md)
