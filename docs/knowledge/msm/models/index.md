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
`msm_pricing.bootstrap.attach_pricing_schemas(...)`, which includes core
dependencies such as `AssetTable`, `IndexTypeTable`, and `IndexTable` before
pricing extension tables and resolves them through direct backend attachment.

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
- `msm.models.accounts`: account registry, account target portfolios, position
  sets, account groups, and account model portfolios.
- `msm.models.accounts.core`: core account registry, account target portfolio,
  and position-set tables.
- `msm.models.accounts.groups`: account group and account model-portfolio
  tables.
- `msm.models.assets`: asset-related models, including the core asset registry,
  registered asset types, categories, memberships, and provider details.
- `msm.models.assets.core`: core asset registry.
- `msm.models.assets.types`: registered asset type definitions.
- `msm.models.assets.bonds`: one-to-one bond asset detail rows.
- `msm.models.assets.categories`: categories and memberships.
- `msm.models.calendars`: calendar identity, date, session, and event tables.
- `msm.models.execution`: execution tables.
- `msm_portfolios.models.virtual_funds`: funds.
- `msm.models.indices`: index type registry and canonical index reference rows.
- `msm.models.issuers`: issuer reference data used by bond assets.
- `msm_portfolios.models.portfolios`: portfolios and portfolio metadata.
- `msm.models.assets.provider_details`: provider-specific asset metadata.
- `msm_portfolios.models.rebalancing`: rebalance strategy metadata.
- `msm_portfolios.models.signals`: signal metadata.
- `msm.api.*` and `msm_portfolios.api.*`: user-facing Pydantic rows and
  class-owned row operations for markets MetaTables.

## Key Contracts

`markets_sqlalchemy_models()` returns core `msm` models in dependency order.
`msm_portfolios.models.portfolio_sqlalchemy_models()` returns portfolio and
virtual-fund models. Keep the owning package list updated when adding persistent
market objects so schema registration stays deterministic.

Models should represent durable schema. Runtime-only behavior belongs in
DataNodes, services, pricing classes, or `msm.api` row helpers depending on the
use case.

The core `markets_sqlalchemy_models()` list intentionally does not include
portfolio-package or optional pricing-package tables. Use `msm_portfolios` for
portfolio/virtual-fund workflows and the pricing helper when a workflow needs
pricing-owned current instrument payloads, index conventions, or curve identity
rows.

Every model returned by `markets_sqlalchemy_models()` must be registerable as a
MetaTable in both platform-managed and external-registered modes.

Platform-managed models inherit `MarketsMetaTableMixin`, which assigns the
physical SQLAlchemy table name through the package naming convention. Model
classes should declare `__metatable_identifier__`, `__metatable_description__`,
and SQLAlchemy `__table_args__`, but should not hand-write `__tablename__`.
The physical name is `ms_markets__<lowercase-concept>` and gains an
`MSM_AUTO_REGISTER_NAMESPACE` suffix when that environment variable is set
before model import.

Project-local extension models can keep the markets mixins while using a
project-owned physical table-name app segment. Set `__markets_storage_app__` in
the SQLAlchemy model class, or in an abstract project-local mixin, before the
model is imported and mapped:

```python
class MyProjectMarketsMetaTableMixin(MarketsMetaTableMixin):
    __abstract__ = True
    __markets_storage_app__ = "my_project_markets"


class BinanceSpotAccountDetailsTable(MyProjectMarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "com.my_project.BinanceSpotAccountDetails"
    __metatable_description__ = (
        "Project-local Binance spot account details keyed by AssetTable.uid."
    )
```

That changes only the SQLAlchemy physical table name, for example
`my_project_markets__com_my_project_binancespotaccountdetails`. It does not
replace `__metatable_identifier__`, which remains the logical catalog and row
runtime identity.

`__metatable_description__` is required on every concrete markets MetaTable,
including `PlatformTimeIndexMetaTable` storage classes used by DataNodes. The
description is table-level discovery text: it should identify the row grain,
business intention, and expected use of the table. Column labels and column
descriptions stay on SQLAlchemy column `info` metadata. Built-in markets and
pricing tables are validated so every physical column has a non-empty
description before registration-facing tests pass.

`__metatable_identifier__` is authored as the bare logical name, such as
`Asset`. At runtime the shared markets identifier rule keeps the bare name for
the default markets namespace and prefixes non-default namespaces, such as
`mainsequence.examples.Asset`.

## Extension Notes

When adding a built-in library model:

1. Define the SQLAlchemy class in the relevant module with a `Table` suffix.
2. Add it to `markets_sqlalchemy_models()` in dependency order.
3. Add repository operations if application code needs compiled database access.
4. Add a `MarketsMetaTableRow` Pydantic row model under `msm.api` when users
   should manipulate typed row objects.
5. Add service wrappers if the operation is part of a broader application
   workflow.

Project-local extension models do not need to modify `markets_sqlalchemy_models()`.
Pass the SQLAlchemy model class directly to
`msm.start_engine(models=[MyExtensionTable])`; bootstrap expands SQLAlchemy
`ForeignKey(...)` dependencies and attaches the model through the shared direct
backend lookup path.

## Related Concepts

- [Platform](../platform/index.md)
- [Repositories](../repositories/index.md)
- [Client](../client/index.md)
