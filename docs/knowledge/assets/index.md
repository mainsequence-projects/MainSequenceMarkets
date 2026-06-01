# Assets

The assets concept owns market asset identity. `Asset` is the user-facing API
model for registering and querying canonical market assets. It connects external
identifiers, asset categories, provider metadata, and asset-indexed data
products into a consistent Main Sequence representation.

Most application code should work with `msm.api.assets.Asset`. That Pydantic row
model is backed by `msm.models.assets.AssetTable`, the SQLAlchemy MetaTable
schema declaration used for platform registration and compiled SQL operations.
Use `AssetTable` when authoring schema, repository, or registration code; use
`Asset` when application code needs to create, upsert, filter, update, or delete
asset rows.

## Asset Model

`AssetTable` is intentionally small. It is the asset registry, not the place to
store every instrument-specific field. The stable identity fields are:

- `uid`: internal row identity used by relational detail tables.
- `unique_identifier`: the canonical public handle for the asset.
- `asset_type`: a short classification string, such as `crypto`, `equity`, or
  `future`.

`AssetType` is the type registry. Register an `asset_type` before using it in
new asset workflows so the meaning of the string is discoverable. In the current
schema, `Asset.asset_type` is a string classification field whose values should
match rows in `AssetType`; it is not a database foreign key in this release.

Use `msm.constants` for built-in asset type keys instead of repeating literals
across projects:

```python
from msm.constants import (
    ASSET_TYPE_BOND,
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_SPOT,
    ASSET_TYPE_EQUITY,
    ASSET_TYPE_FUTURE,
)

assert ASSET_TYPE_BOND == "bond"
assert ASSET_TYPE_CRYPTO == "crypto"
assert ASSET_TYPE_CURRENCY == "currency"
assert ASSET_TYPE_CURRENCY_SPOT == "currency_spot"
assert ASSET_TYPE_EQUITY == "equity"
assert ASSET_TYPE_FUTURE == "future"
```

The constants module also exposes `BUILT_IN_ASSET_TYPE_DEFINITIONS`, whose
entries can produce payloads for `AssetType.upsert(...)`:

```python
from msm.api.assets import AssetType
from msm.constants import BUILT_IN_ASSET_TYPE_DEFINITIONS

for definition in BUILT_IN_ASSET_TYPE_DEFINITIONS:
    AssetType.upsert(**definition.as_payload())
```

```text
+-----------------------------+        logical value        +-----------------------------+
| AssetType                   |<----------------------------| Asset                       |
|-----------------------------|                             |-----------------------------|
| uid                         |                             | uid                         |
| asset_type        unique    |                             | unique_identifier unique    |
| display_name                |                             | asset_type                  |
| description                 |                             +-----------------------------+
| metadata_json               |
+-----------------------------+
```

The intended extension model is relational composition. Do not extend
`AssetTable` by adding columns such as maturity, strike, expiry, issuer,
venue-specific payloads, or serialized pricing instruments. Instead, add a
detail table keyed by the asset row and keep the core `AssetTable` stable.

Futures use the same extension pattern:

```text
+-----------------------------+        one-to-one detail        +-----------------------------+
| AssetTable                  |-------------------------------->| FutureAssetDetailsTable          |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | kind                        |
| asset_type                 |                                 | underlying_index_uid FK     |
+-----------------------------+                                 | settlement_asset FK         |
                                                                | margin_asset FK             |
                                                                | expires_at                  |
                                                                | contract_size               |
                                                                | metadata_json               |
                                                                +-----------------------------+
```

`FutureAssetDetailsTable` is the built-in futures detail table. Its public API
mirrors the current pattern: a SQLAlchemy `FutureAssetDetailsTable` for schema
work and a Pydantic `Future` row model for application code. For one-to-one
instrument details, the detail table's `asset_uid` should be both the primary
key and the foreign key to `AssetTable.uid`; a separate detail-row `uid` is
unnecessary.

## Currency Assets

Single currency code/name metadata is user or provider-owned data. Keep it in
the workflow using it, then register single currencies as normal `Asset` rows
with `asset_type="currency"`.

`CurrencySpot` is the built-in extension for tradable spot pairs such as
`EUR/USD`. The pair is stored as a normal `Asset` with
`asset_type="currency_spot"`, while `CurrencySpotAssetDetailsTable` stores the
base and quote currency references:

```python
from msm.api.assets import Asset, CurrencySpot
from msm.constants import ASSET_TYPE_CURRENCY

USD = {"code": "USD", "currency_name": "US Dollar"}
EUR = {"code": "EUR", "currency_name": "Euro"}

usd = Asset.upsert(unique_identifier=USD["code"], asset_type=ASSET_TYPE_CURRENCY)
eur = Asset.upsert(unique_identifier=EUR["code"], asset_type=ASSET_TYPE_CURRENCY)

eur_usd = CurrencySpot.upsert(
    unique_identifier="BBG0013HGRV5",
    base_currency_uid=eur.uid,
    quote_currency_uid=usd.uid,
)
```

The typed asset API normalizes asset type strings before writing them:
`"Currency"` becomes `currency`, `"Currency Spot"` becomes `currency_spot`, and
`"Future"` becomes `future`. Friendly display names belong in
`AssetType.display_name`.

See [Currency Assets](currency.md) for the schema, registration dependency
order, and the exact `CurrencySpot.upsert(...)` workflow.

## Bond Assets

Bonds are normal `Asset` rows with `asset_type="bond"` plus a one-to-one
`BondAssetDetailsTable` row. Issuers are separate reference rows in `IssuerTable`,
not assets and not loose strings.

```python
import datetime as dt

from msm.api.assets import Asset, Bond
from msm.api.issuers import Issuer
from msm.constants import ASSET_TYPE_CURRENCY

issuer = Issuer.upsert(
    unique_identifier="example-issuer",
    display_name="Example Issuer",
)
usd = Asset.upsert(unique_identifier="USD", asset_type=ASSET_TYPE_CURRENCY)

bond = Bond.upsert(
    unique_identifier="example-usd-bond-2031",
    issuer_uid=issuer.uid,
    currency_asset_uid=usd.uid,
    issue_date=dt.date(2026, 5, 27),
    maturity_date=dt.date(2031, 5, 27),
    status="ACTIVE",
)
```

See [Bond Assets](bonds.md) for the issuer table, bond detail schema, lifecycle
status values, and registration dependency order.

See `examples/assets/us_treasury_bond_workflow.py` for a Treasury note example
that uses CUSIP `91282CQQ7` as the canonical asset identifier, stores FIGI
`BBG0221YLR31` in `OpenFigiDetails`, and keeps coupon/tenor terms out of the
minimal bond detail schema.

## OpenFIGI As Asset Properties

OpenFIGI metadata is the built-in example of extending the asset model with
provider-specific properties. `OpenFigiDetails` is not part of `AssetTable`; it
is a one-to-one detail table keyed by the asset row. This keeps canonical asset
identity small while still allowing provider facts such as FIGI, ISIN, ticker,
security type, exchange, and raw provider payload to be stored relationally.

```text
+-----------------------------+        one-to-one provider      +-----------------------------+
| AssetTable                  |-------------------------------->| OpenFigiAssetDetailsTable        |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | figi                        |
| asset_type                 |                                 | composite                   |
+-----------------------------+                                 | share_class                 |
                                                                | isin                        |
                                                                | ticker                      |
                                                                | security_type               |
                                                                | metadata                    |
                                                                | raw_payload                 |
                                                                +-----------------------------+
```

Application code should still start with the `Asset` API. Resolve provider data,
upsert the canonical asset, then upsert its OpenFIGI detail row using
`asset_uid=asset.uid`:

```python
from msm.api.assets import Asset, AssetType, OpenFigiDetails
from msm.constants import ASSET_TYPE_EQUITY
from msm.services.assets.openfigi import query_by_figi

AssetType.upsert(asset_type=ASSET_TYPE_EQUITY, display_name="Equity")

normalized = query_by_figi("BBG00FNFPQH4")
asset = Asset.upsert(
    unique_identifier=normalized["unique_identifier"],
    asset_type=ASSET_TYPE_EQUITY,
)
details = OpenFigiDetails.upsert(
    asset_uid=asset.uid,
    figi=normalized["figi"],
    composite=normalized["composite"],
    share_class=normalized["share_class"],
    isin=normalized["isin"],
    ticker=normalized["ticker"],
    name=normalized["name"],
    exchange_code=normalized["exchange_code"],
    security_type=normalized["security_type"],
    security_type_2=normalized["security_type_2"],
    security_market_sector=normalized["security_market_sector"],
    security_description=normalized["security_description"],
    unique_id=normalized["unique_id"],
    unique_id_fut_opt=normalized["unique_id_fut_opt"],
    metadata_text=normalized["metadata"],
    raw_payload=normalized["raw_payload"],
)
```

`OpenFigiAssetDetailsTable.asset_uid` is both the primary key and the foreign key to
`AssetTable.uid`. There is no separate `uid` column on the detail table.
`OpenFigiDetails.uid` in the Pydantic row API resolves to the same value as
`asset_uid` so generic row identity helpers still have a stable row identifier.

## Scope

Assets answer these questions:

- What is the canonical `unique_identifier` for an asset?
- Which registered asset type classifies the asset?
- Which categories or category memberships describe the asset?
- Which provider details, such as OpenFIGI metadata, were used to resolve it?

## Primary Modules

- `msm.models.assets`: asset-related SQLAlchemy/MetaTable declarations,
  including `AssetTable`, `AssetTypeTable`, asset categories, memberships, and
  provider detail tables.
- `msm.models.assets.core`: core asset registry model.
- `msm.models.assets.types`: asset type registry model.
- `msm.models.assets.currency_spot`: currency spot relationship detail model.
- `msm.models.assets.bonds`: bond relationship and lifecycle detail model.
- `msm.models.issuers`: issuer reference data used by bond assets.
- `msm.api.assets`: user-facing Pydantic rows and typed class operations for
  `Asset`, `AssetType`, `AssetCategory`, `AssetCategoryMembership`,
  `Bond`, `CurrencySpot`, and `OpenFigiDetails`.
- `msm.api.issuers`: user-facing Pydantic rows and typed class operations for
  issuer reference data.
- `msm.constants`: static built-in asset type keys and built-in `AssetType`
  definitions for application and project code.
- `msm.data_nodes.assets`: asset-indexed DataNodes such as `AssetSnapshot`.
- `msm.services.assets`: application-facing asset service helpers over
  repositories.
- `msm.services.assets.openfigi`: OpenFIGI query, normalization, and row-building
  helpers.
- `msm.models.assets.categories`: category and membership models.
- `msm.models.assets.provider_details`: provider metadata such as OpenFIGI
  details.
- `msm.repositories.assets`, `msm.repositories.asset_categories`, and
  `msm.repositories.provider_details`: MetaTable operation builders for asset
  control-plane records.

## Key Contracts

The asset `unique_identifier` is the stable handle used by portfolios, holdings,
pricing details, and market data. Category membership should describe asset
classification without changing identity.

`AssetType` records a unique `asset_type`, optional `display_name`, optional
`description`, and optional `metadata_json`. Use it as a lightweight registry of
what each type string means in a namespace.

Pricing details are not the same thing as core asset details or market prices.
Serialized priceable instrument terms belong to `msm_pricing`, not
`msm.models.assets`: current terms are stored in
`msm_pricing.models.AssetCurrentPricingDetailsTable`, historical pricing-detail
observations live in `msm_pricing.data_nodes.pricing_details`, and users attach
or load them through `Instrument.attach_to_asset(asset)` and
`Instrument.load_from_asset(asset)`. Price histories and display snapshots
remain market-data workflows.

## Creating, Querying, And Deleting Assets

Use Pydantic row models in `msm.api.assets` for normal application workflows.
They expose class methods over the active markets runtime and return typed
objects.

```python
from msm.api.assets import Asset, AssetType
from msm.constants import ASSET_TYPE_CRYPTO, ASSET_TYPE_CRYPTO_DEFINITION

AssetType.upsert(**ASSET_TYPE_CRYPTO_DEFINITION.as_payload())

asset = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type=ASSET_TYPE_CRYPTO,
)
asset_by_identifier = Asset.get_by_unique_identifier(
    unique_identifier="example-asset-btc",
)
asset_by_uid = Asset.get_by_uid(asset.uid)
crypto_assets = Asset.filter(
    unique_identifier_contains="example-asset-",
    asset_type=ASSET_TYPE_CRYPTO,
)
# Optional cleanup for temporary custom assets only:
# Asset.delete(asset.uid)
```

When a workflow owns startup preflight, register the required MetaTables before
row operations run:

```python
import msm

runtime = msm.start_engine(models=["AssetType", "Asset"])
asset_table_handle = runtime.table("Asset")
```

Production code normally assumes the `Asset` MetaTable is already registered.
The process must initialize or attach the runtime during startup. If no runtime
exists, or if the active runtime does not include the required asset tables,
the row API raises with instructions to run explicit startup preflight.

Example and test workflows that need isolated MetaTables can opt into
the example namespace by setting `MSM_AUTO_REGISTER_NAMESPACE` before importing
`msm.api` row classes, then running explicit bootstrap:

```python
import os

from examples.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

from msm.api.assets import Asset
from msm.constants import ASSET_TYPE_CRYPTO

msm.start_engine(models=["AssetType", "Asset"])

asset = Asset.upsert(
    unique_identifier="example-asset-btc",
    asset_type=ASSET_TYPE_CRYPTO,
)
```

The namespace is part of runtime/table registration, not an asset payload field.
Use `msm.start_engine(models=[...])` for controlled startup preflight with a
selected table set.

Use `runtime.context` or `runtime.table(...)` for lower-level multi-table
repository operations that need to compile statements across registered models.

Prefer `Asset.upsert(...)` in setup scripts and repeatable examples because it
is safe to rerun for the same `unique_identifier`. Use lower-level
`create_asset(...)` only when a duplicate asset should fail the workflow.

Use `AssetCategory` and `AssetCategoryMembership` when the universe itself is a
named reusable object:

```python
from msm.api.assets import Asset, AssetCategory
from msm.constants import ASSET_TYPE_CRYPTO

btc = Asset.upsert(unique_identifier="BTC", asset_type=ASSET_TYPE_CRYPTO)
eth = Asset.upsert(unique_identifier="ETH", asset_type=ASSET_TYPE_CRYPTO)
category = AssetCategory.upsert(
    unique_identifier="crypto-majors",
    display_name="Crypto Majors",
)
memberships = AssetCategory.replace_memberships(
    category_uid=category.uid,
    asset_uids=[btc.uid, eth.uid],
)
```

See `examples/assets/asset_category_workflow.py` for a lifecycle example that
creates a category, adds assets, removes assets, and prints category membership
after each change. The normal run leaves assets in the category; only the
explicit cleanup flag clears and deletes the temporary category. The asset
examples share identifiers, asset type payloads, currency payloads, and FIGI
constants through
`examples/assets/utils/reference_data.py`.

Use `OpenFigiDetails.upsert(...)` for typed provider metadata rows when the
asset row already exists. The OpenFIGI section above shows the provider-detail
extension pattern. Provider services may still build `AssetTable` or
`OpenFigiAssetDetailsTable` instances internally when authoring SQLAlchemy schema
rows.

Do not delete assets as part of the normal setup path. Only use cleanup for
temporary test assets or custom organization-owned records. Public or shared
mastered assets should be treated as reference data; remove category memberships
or downstream references instead of deleting the canonical identity row.

See `examples/assets/asset_crud_workflow.py` for a focused example that creates
temporary custom assets, registers asset types, resolves `BBG00FNFPQH4` through
OpenFIGI, registers the returned provider details, writes an example
AssetSnapshot frame, searches by type, and lists the created assets. FIGI
resolution requires the Main Sequence secret `OPEN_FIGI_API_KEY`; create it in
`www.main-sequence.app/app/main_sequence_workbench/secrets` before running the
example. Cleanup is opt-in through `--delete-temporary-assets`.

See `examples/assets/currency_spot_workflow.py` for a focused currency example
that creates `EUR` and `USD` assets, resolves `BBG0013HGRV5` through OpenFIGI,
uses `CurrencySpot.upsert(...)` to create the `EUR/USD` pair, and writes
matching `AssetSnapshot` rows.

## Asset-Indexed DataNodes

Timestamped asset facts, such as snapshots and pricing details, belong in
asset-indexed DataNodes instead of columns on `AssetTable`. See
[Asset-Indexed DataNodes](asset_indexed_data_nodes.md) for the detailed
`AssetIndexedDataNode` contract, the difference from a generic Main Sequence
`DataNode`, and `AssetSnapshot` as the concrete implementation.

## Extension Notes

Add new DataNode schemas under `msm.data_nodes.assets` when the output is
time-indexed market data. Add provider-specific lookup or normalization under a
service submodule such as `msm.services.assets.openfigi`. Add new persistent
fields in `msm.models` only when the platform schema needs to own the field.

There is intentionally no `msm.assets` package boundary. Asset identity belongs
to MetaTable models and repositories, timestamped asset facts belong to
DataNodes, and external provider integration belongs to services.

## Related Concepts

- [Accounts](../accounts/index.md)
- [Asset-Indexed DataNodes](asset_indexed_data_nodes.md)
- [Bond Assets](bonds.md)
- [Currency Assets](currency.md)
- [Portfolios](../portfolios/index.md)
- [Pricing](../pricing/index.md)
- [Platform](../platform/index.md)
