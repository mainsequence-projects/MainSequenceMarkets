# Platform

The platform concept owns shared integration primitives between `msm` and the
Main Sequence runtime. It is the foundation for MetaTable registration, market
DataNode behavior, and common ORM helpers.

## Scope

Platform utilities answer these questions:

- How do market-domain SQLAlchemy models register as Main Sequence MetaTables?
- What shared base class and schema naming rules do market models use?
- How do market-specific DataNodes normalize storage and configuration?
- Which helpers should remain common across accounts, assets, execution, and
  portfolios?

## Primary Modules

- `msm.base`: shared SQLAlchemy base, market schema settings, and model mixins.
- `msm.models.registration`: MetaTable registration helpers for market-domain models.
- `msm.maintenance.migrations`: SDK-managed MetaTable migration commands and
  catalog finalization helpers.
- `msm.migrations`: package-owned model registry and Python migration modules.
- `msm.settings`: shared markets constants such as the canonical asset identity
  dimension.
- `msm.data_nodes.accounts`: account holdings DataNodes.
- `msm.data_nodes.assets`: asset-specific DataNode package, including
  `AssetSnapshot` and shared asset-indexed behavior in
  `msm.data_nodes.assets.asset_indexed`.
- `msm.data_nodes.execution`: execution DataNodes for orders, order events,
  trades, and execution errors.
- `msm.data_nodes.indices`: index-specific DataNode package, including
  timestamped index facts and canonical `IndexTable` source-table foreign keys.
- `msm.data_nodes.utils`: shared DataNode utilities that are not tied to one
  model concept, including source-table contracts, timestamp normalization,
  stamped-frame behavior, and namespace defaulting.
- `msm_portfolios.data_nodes`: portfolio and virtual-fund DataNodes that build
  on the shared markets DataNode machinery without entering the core `msm`
  registration graph.
- `cli`: explicit command-line helpers, including
  `msm copy-msm-skills` for installing packaged ms-markets agent skills into a
  host project.

## Key Contracts

Platform primitives should stay low-level. They should not know about business
logic for a specific concept such as pricing, portfolio construction, or asset
translation.

Asset-indexed DataNode subclasses should use `AssetIndexedDataNode` for asset
scope and namespace behavior. Timestamped asset facts should use
`AssetTimestampedDataNode` plus `AssetDataNodeConfiguration`, with schema,
indexes, dtypes, nullability, and source-table foreign keys declared only on the
storage MetaTable. The broad legacy compatibility names were removed;
asset-indexed DataNode code should use the explicit asset-indexed base classes
directly.

See [MetaTable Registration](meta_table_registration.md) for runtime attachment
and model registration concepts. See
[MetaTable Migrations](metatable_migrations.md) for the admin-owned schema
creation and evolution workflow.

The `msm` import path is side-effect free. Installing the package makes the
ms-markets skill bundle available as package data, but skills are copied into a
host project only when a user runs `msm copy-msm-skills --path <project>`.
That command writes to `.agents/skills/ms_markets/` and leaves Main Sequence
scaffold skills and project-state files untouched.

## Extension Notes

Add behavior here only when at least two concept packages need the same platform
primitive. If DataNode behavior is specific to one concept, keep it in that
concept package first. If it is shared DataNode machinery and not model-shaped,
place it under `msm.data_nodes.utils`.

Repository-level maintenance workflows live in Open Agent skills under
`.agents/skills/`. Use `.agents/skills/library_maintenance/SKILL.md` when making
relevant library changes so implementation, docs, examples, tutorials, changelog,
and validation stay aligned.

## Related Concepts

- [Models](../models/index.md)
- [Accounts](../accounts/index.md)
- [Assets](../assets/index.md)
- [Portfolios](../../msm_portfolios/portfolios/index.md)
