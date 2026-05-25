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
- `msm.markets_data_node`: shared DataNode and configuration behavior for
  market-domain publishers.

## Key Contracts

Platform primitives should stay low-level. They should not know about business
logic for a specific concept such as pricing, portfolio construction, or asset
translation.

Market DataNode subclasses should use the shared base behavior for consistent
configuration, record definitions, and storage metadata.

See [MetaTable Registration](meta_table_registration.md) for the registration
workflow and the two supported management modes.

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
