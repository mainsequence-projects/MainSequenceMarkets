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
- `msm.meta_tables`: MetaTable registration helpers for market-domain models.
- `msm.settings`: shared markets constants such as the canonical asset identity
  dimension.
- `msm.asset_indexed_data_node`: shared DataNode and configuration behavior for
  publishers whose persisted identity includes an asset `unique_identifier`.
- `msm.markets_data_node`: temporary compatibility shim for the old
  `MarketDataNode` and `MarketDataNodeConfiguration` imports.
- `msm.cli`: explicit command-line helpers, including
  `msm copy-msm-skills` for installing packaged ms-markets agent skills into a
  host project.

## Key Contracts

Platform primitives should stay low-level. They should not know about business
logic for a specific concept such as pricing, portfolio construction, or asset
translation.

Asset-indexed DataNode subclasses should use `AssetIndexedDataNode` and
`AssetIndexedDataNodeConfiguration` for consistent asset scope, record
definitions, and storage metadata. New code should not import the old
`MarketDataNode` names unless it is intentionally preserving compatibility with
existing callers.

See [MetaTable Registration](meta_table_registration.md) for the registration
workflow and the two supported management modes.

The `msm` import path is side-effect free. Installing the package makes the
ms-markets skill bundle available as package data, but skills are copied into a
host project only when a user runs `msm copy-msm-skills --path <project>`.
That command writes to `.agents/skills/ms_markets/` and leaves Main Sequence
scaffold skills and project-state files untouched.

## Extension Notes

Add behavior here only when at least two concept packages need the same platform
primitive. If behavior is specific to one concept, keep it in that concept
package first.

Repository-level maintenance workflows live in Open Agent skills under
`.agents/skills/`. Use `.agents/skills/library_maintenance/SKILL.md` when making
relevant library changes so implementation, docs, examples, tutorials, changelog,
and validation stay aligned.

## Related Concepts

- [Models](../models/index.md)
- [Accounts](../accounts/index.md)
- [Assets](../assets/index.md)
- [Portfolios](../portfolios/index.md)
