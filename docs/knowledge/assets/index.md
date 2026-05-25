# Assets

The assets concept owns market asset identity. It connects external identifiers,
asset categories, snapshots, pricing details, and provider metadata into a
consistent Main Sequence representation.

## Scope

Assets answer these questions:

- What is the canonical `unique_identifier` for an asset?
- Which asset master list owns the asset?
- Which categories or category memberships describe the asset?
- Which snapshots and pricing details are attached to the asset?
- Which provider details, such as OpenFIGI metadata, were used to resolve it?

## Primary Modules

- `msm.models.assets`: SQLAlchemy/MetaTable asset model. The `Asset` model lives
  here.
- `msm.data_nodes.assets`: DataNodes for asset snapshots and asset pricing
  details.
- `msm.services.assets`: application-facing asset service helpers over
  repositories.
- `msm.services.assets.openfigi`: OpenFIGI query, normalization, and row-building
  helpers.
- `msm.models.asset_categories`: category and membership models.
- `msm.models.asset_master_lists`: asset master list model.
- `msm.models.provider_details`: provider metadata such as OpenFIGI details.
- `msm.repositories.assets`, `msm.repositories.asset_categories`, and
  `msm.repositories.provider_details`: MetaTable operation builders for asset
  control-plane records.

## Key Contracts

The asset `unique_identifier` is the stable handle used by portfolios, holdings,
pricing details, and market data. Category membership should describe asset
classification without changing identity.

Pricing details are not the same thing as market prices. Pricing details store
terms needed to rebuild priceable instruments, while price histories live in
market-data workflows.

## Extension Notes

Add new DataNode schemas under `msm.data_nodes.assets` when the output is
time-indexed market data. Add provider-specific lookup or normalization under a
service submodule such as `msm.services.assets.openfigi`. Add new persistent
fields in `msm.models` only when the platform schema needs to own the field.

There is intentionally no `msm.assets` package boundary. Asset identity belongs
to MetaTable models and repositories, timestamped asset facts belong to
DataNodes, and external provider integration belongs to services.

See [AssetMasterList](asset_master_lists.md) for the control-plane reference
table contract.

## Related Concepts

- [Accounts](../accounts/index.md)
- [Portfolios](../portfolios/index.md)
- [Pricing](../pricing/index.md)
- [Platform](../platform/index.md)
