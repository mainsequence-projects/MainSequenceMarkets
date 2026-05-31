# Models

The models concept owns SQLAlchemy definitions for the market-domain schema.
These declarations define what can be registered as Main Sequence MetaTables and
in which dependency order. Table declaration class names use the `Table` suffix;
for example, `AssetTable` is the SQLAlchemy MetaTable declaration while
`msm.api.assets.Asset` is the user-facing Pydantic row object.

`msm.models` does not export unsuffixed row names. Imports such as
`from msm.models import Asset` are removed; use `from msm.models import
AssetTable` for schema work or `from msm.api.assets import Asset` for row
operations.

Pricing-specific MetaTables are not core markets models. Tables such as
`IndexConventionDetailsTable`, `CurveTable`, and
`AssetCurrentPricingDetailsTable` live under `msm_pricing.models` and are
selected through `msm_pricing.meta_tables.pricing_sqlalchemy_models()`.
Runtime initialization should use
`msm_pricing.bootstrap.create_pricing_schemas(...)`, which includes core
dependencies such as `AssetTable`, `IndexTypeTable`, and `IndexTable` before
pricing extension tables and resolves them through the maintenance catalog.

## Scope

Models answer these questions:

- Which market objects are persisted as relational records?
- Which fields and indexes belong to the platform schema?
- Which relationships are database concerns rather than client concerns?
- In what order should MetaTables be registered?

## Primary Modules

- `msm.models.__init__`: aggregate model exports and `markets_sqlalchemy_models`.
- `msm.models.registration`: registration and resolution helpers for turning
  SQLAlchemy table declarations into Main Sequence MetaTables.
- `msm.models.accounts`: accounts and account target position assignments.
- `msm.models.assets`: asset-related models, including the core asset registry,
  registered asset types, categories, memberships, and provider details.
- `msm.models.assets.core`: core asset registry.
- `msm.models.assets.types`: registered asset type definitions.
- `msm.models.assets.bonds`: one-to-one bond asset detail rows.
- `msm.models.assets.categories`: categories and memberships.
- `msm.models.calendars`: calendars.
- `msm.models.execution`: execution tables.
- `msm.models.funds`: funds.
- `msm.models.indices`: index type registry and canonical index reference rows.
- `msm.models.issuers`: issuer reference data used by bond assets.
- `msm.models.portfolios`: portfolios and portfolio metadata.
- `msm.models.assets.provider_details`: provider-specific asset metadata.
- `msm.models.rebalancing`: rebalance strategy metadata.
- `msm.models.signals`: signal metadata.
- `msm.api.*`: user-facing Pydantic rows and class-owned row operations for all
  markets MetaTables.

## Key Contracts

`markets_sqlalchemy_models()` returns models in dependency order. Keep this list
updated when adding persistent market objects so schema registration stays
deterministic.

Models should represent durable schema. Runtime-only behavior belongs in
DataNodes, services, pricing classes, or `msm.api` row helpers depending on the
use case.

The core `markets_sqlalchemy_models()` list intentionally does not include
optional pricing-package tables. Use the pricing helper when a workflow needs
pricing-owned current instrument payloads, index conventions, or curve
identity rows.

Every model returned by `markets_sqlalchemy_models()` must be registerable as a
MetaTable in both platform-managed and external-registered modes.

Platform-managed models inherit `MarketsMetaTableMixin`, which delegates table
name derivation to the SDK `PlatformManagedMetaTable` mixin. Model classes should
declare `__metatable_identifier__`, `__metatable_description__`, and SQLAlchemy
`__table_args__`, but should not hand-write `__tablename__`; the physical name
is the SDK configured storage hash for the resolved table contract.

`__metatable_description__` is required on every concrete markets MetaTable,
including `PlatformTimeIndexMetaData` storage classes used by DataNodes. The
description is table-level discovery text: it should identify the row grain,
business intention, and expected use of the table. Column labels and column
descriptions stay on `mapped_column(info={...})`.

`__metatable_identifier__` is authored as the bare logical name, such as
`Asset`. At runtime the shared markets identifier rule keeps the bare name for
the default markets namespace and prefixes non-default namespaces, such as
`mainsequence.examples.Asset`.

## Extension Notes

When adding a model:

1. Define the SQLAlchemy class in the relevant module with a `Table` suffix.
2. Add it to `markets_sqlalchemy_models()` in dependency order.
3. Add repository operations if application code needs compiled database access.
4. Add a Pydantic row model under `msm.api` when users should manipulate typed
   row objects.
5. Add service wrappers if the operation is part of a broader application
   workflow.

## Related Concepts

- [Platform](../platform/index.md)
- [Repositories](../repositories/index.md)
- [Client](../client/index.md)
