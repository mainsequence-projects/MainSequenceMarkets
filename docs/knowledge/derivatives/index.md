# Derivatives

Derivatives are tradable contracts whose contract terms live outside the core
`AssetTable`.

The current implemented derivative workflow is futures on indexes. The future
contract itself is a canonical `Asset` with `asset_type="future"`, while
`FutureDetailsTable` stores contract terms and references an `IndexTable`
underlying.

## Scope

Derivatives docs own:

- derivative asset type conventions;
- detail-table relationships for contract-specific fields;
- user-facing derivative API workflows under `msm.api.derivatives`;
- references from derivative contracts to non-asset underlyings such as
  `IndexTable`.

They do not own timestamped market data or pricing engines. Historical prices
belong in DataNodes, and valuation-specific runtime code belongs in optional
pricing packages.

## Primary Modules

- `msm.models.derivatives`: SQLAlchemy MetaTable declarations for derivative
  contract details.
- `msm.api.derivatives`: user-facing typed derivative APIs.
- `msm.models.indices`: index reference data used by index-underlying futures.
- `msm.api.indices`: user-facing typed index APIs.

## Related Concepts

- [Futures](futures.md)
- [Indexes](../indices/index.md)
- [Assets](../assets/index.md)
- [Asset-Indexed DataNodes](../assets/asset_indexed_data_nodes.md)
