# Models

The models concept owns SQLAlchemy definitions for the market-domain schema.
These models define what can be registered as Main Sequence MetaTables and in
which dependency order.

## Scope

Models answer these questions:

- Which market objects are persisted as relational records?
- Which fields and indexes belong to the platform schema?
- Which relationships are database concerns rather than client concerns?
- In what order should MetaTables be registered?

## Primary Modules

- `msm.models.__init__`: aggregate model exports and `markets_sqlalchemy_models`.
- `msm.models.accounts`: accounts and account target position assignments.
- `msm.models.assets`: assets.
- `msm.models.asset_categories`: categories and memberships.
- `msm.models.asset_master_lists`: asset master lists.
- `msm.models.calendars`: calendars.
- `msm.models.execution`: execution tables.
- `msm.models.funds`: funds.
- `msm.models.instruments`: pricing and instruments configuration.
- `msm.models.portfolios`: portfolios and portfolio metadata.
- `msm.models.provider_details`: provider-specific metadata.
- `msm.models.rebalancing`: rebalance strategy metadata.
- `msm.models.signals`: signal metadata.

## Key Contracts

`markets_sqlalchemy_models()` returns models in dependency order. Keep this list
updated when adding persistent market objects so schema registration stays
deterministic.

Models should represent durable schema. Runtime-only behavior belongs in
DataNodes, services, pricing classes, or client helpers depending on the use
case.

Every model returned by `markets_sqlalchemy_models()` must be registerable as a
MetaTable in both platform-managed and external-registered modes.

## Extension Notes

When adding a model:

1. Define the SQLAlchemy class in the relevant module.
2. Add it to `markets_sqlalchemy_models()` in dependency order.
3. Add repository operations if application code needs compiled database access.
4. Add service wrappers if the operation is part of an application workflow.

## Related Concepts

- [Platform](../platform/index.md)
- [Repositories](../repositories/index.md)
- [Client](../client/index.md)
