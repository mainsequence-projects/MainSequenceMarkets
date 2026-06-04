---
name: mainsequence-asset-model-extension
description: Use this skill when extending or reviewing the ms-markets Asset model, including AssetType registration and one-to-one asset property/detail tables. This skill owns the rule that AssetTable stays small and extension data belongs in relational detail tables keyed by AssetTable.uid. It does not own AssetIndexedDataNode design, price history, portfolios, or general DataNode implementation.
---

# Main Sequence Markets Asset Model Extension

Use this skill when an agent needs to add, review, or document asset identity
extensions in `ms-markets`.

## Core Rule

`AssetTable` is the canonical asset registry. Keep it small.

Do not add instrument, venue, provider, or lifecycle columns to `AssetTable`.
Examples of fields that do not belong there: maturity, expiry, strike, issuer,
exchange metadata, FIGI payloads, pricing terms, provider tickers, or raw
provider responses.

Extend the asset model with relational composition:

```text
AssetTable.uid 1 ---- 1 ExtensionDetailsTable.asset_uid
```

## AssetType

Use `AssetType` to register what an `Asset.asset_type` string means.

Current contract:

- `AssetTypeTable.asset_type` is unique.
- `AssetTypeTable` may also store `display_name`, `description`, and
  `metadata_json`.
- `Asset.asset_type` should match a registered `AssetType.asset_type`.
- In this release, `Asset.asset_type` is a logical classification string, not a
  database foreign key.
- Typed `msm.api.assets` payloads normalize asset type keys by stripping
  whitespace, lowercasing, and replacing whitespace runs with `_`.

Agent workflow:

1. Register or upsert the needed `AssetType` before creating assets of that
   type.
2. Use short, stable type keys such as `equity`, `crypto`, or `future`.
3. Put explanatory text in `display_name` and `description`, not in the key.

```python
from msm.api.assets import Asset, AssetType

AssetType.upsert(
    asset_type="future",
    display_name="Future",
    description="Futures contracts represented as market assets.",
)

asset = Asset.upsert(
    unique_identifier="future-example",
    asset_type="future",
)
```

## One-To-One Asset Detail Tables

For one-to-one asset properties, use `asset_uid` as both:

- the primary key of the detail table
- the foreign key to `AssetTable.uid`

Do not add a separate `uid` column to one-to-one detail tables.

Recommended SQLAlchemy shape:

```python
class FutureAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "FutureAssetDetails"

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{AssetTable.__table__.fullname}.uid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        info={"description": "Canonical AssetTable uid for this detail row."},
    )
```

Add only fields that belong to that specific extension. Use indexed columns for
lookup keys and JSON/text columns for provider payloads when the payload is not
part of the canonical asset identity.

## Public API Pattern

After the SDK migration provider has migrated and cataloged the SQLAlchemy
detail model, application code should attach it through `msm.start_engine(...)`
and then work through the Pydantic row API:

1. Upsert the `AssetType`.
2. Upsert the canonical `Asset`.
3. Upsert the detail row with `asset_uid=asset.uid`.

```python
import uuid

import msm
from pydantic import AliasChoices, Field

from msm.api.base import MarketsMetaTableRow


class FutureDetails(MarketsMetaTableRow):
    __table__ = FutureAssetDetailsTable
    __required_tables__ = [FutureAssetDetailsTable]
    __upsert_keys__ = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID

msm.start_engine(models=[FutureAssetDetailsTable])
```

`MarketsMetaTableRow` is the Pydantic row-operation wrapper. It is not
registered as a backend MetaTable. The SQLAlchemy detail model class is the
registered/cataloged artifact. If generic row helpers expect `uid`, expose `uid`
as an alias of `asset_uid` in the Pydantic row model. Do not change the SQL table
shape just to satisfy generic helpers.

## Currency Spot Reference Pattern

`CurrencySpotAssetDetailsTable` is the built-in currency spot extension
pattern. Single currencies such as `USD` and `EUR` are normal `Asset` rows with
`asset_type="currency"`. The spot pair is a normal `Asset` with
`asset_type="currency_spot"`; the detail table stores `asset_uid`,
`base_currency_uid`, and `quote_currency_uid` as references to `AssetTable.uid`.

Use the class-owned API workflow instead of requiring callers to pass table
handles:

```python
from msm.api.assets import Asset, CurrencySpot

EUR = {"code": "EUR", "currency_name": "Euro"}
USD = {"code": "USD", "currency_name": "US Dollar"}

eur = Asset.upsert(unique_identifier=EUR["code"], asset_type="currency")
usd = Asset.upsert(unique_identifier=USD["code"], asset_type="currency")

pair = CurrencySpot.upsert(
    unique_identifier="BBG0013HGRV5",
    base_currency_uid=eur.uid,
    quote_currency_uid=usd.uid,
)
```

Do not widen `AssetTable` with `base_currency_uid` or `quote_currency_uid`;
those are extension detail fields.

## Bond Reference Pattern

`BondAssetDetailsTable` is the built-in bond extension pattern. A bond is a
normal `Asset` row with `asset_type="bond"`. The detail table stores `asset_uid`,
`issuer_uid`, `currency_asset_uid`, `issue_date`, `maturity_date`, and
`status`.

Issuers are reference rows in `IssuerTable`, not assets and not loose strings.
Use `Issuer` for issuer reference data, then link bonds through `issuer_uid`.

Use the class-owned API workflow:

```python
import datetime as dt

from msm.api.assets import Asset, Bond
from msm.api.issuers import Issuer

issuer = Issuer.upsert(
    unique_identifier="example-issuer",
    display_name="Example Issuer",
)
usd = Asset.upsert(unique_identifier="USD", asset_type="currency")

bond = Bond.upsert(
    unique_identifier="example-usd-bond-2031",
    issuer_uid=issuer.uid,
    currency_asset_uid=usd.uid,
    issue_date=dt.date(2026, 5, 27),
    maturity_date=dt.date(2031, 5, 27),
    status="ACTIVE",
)
```

Do not widen `AssetTable` with issuer, currency, issue date, maturity date, or
status fields. Those belong to `BondAssetDetailsTable`. Pricing terms, coupons,
schedules, and instrument dumps belong to pricing/instrument contracts, not the
minimal bond asset extension.

## OpenFIGI Reference Pattern

`OpenFigiAssetDetailsTable` is the built-in example of this extension pattern.

Required architecture:

```text
+-----------------------------+        one-to-one provider      +-----------------------------+
| AssetTable                  |-------------------------------->| OpenFigiAssetDetailsTable   |
| uid                  PK     |        asset_uid PK/FK          | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | figi                        |
| asset_type                 |                                 | isin / ticker / metadata    |
+-----------------------------+                                 +-----------------------------+
```

For OpenFIGI and similar providers:

- keep canonical identity in `Asset`
- keep provider-specific facts in the provider detail table
- store raw provider response separately from normalized lookup columns
- preserve existing column mappings such as `metadata_text =
  mapped_column("metadata", Text, nullable=True)`

## Boundaries

- For timestamped or panel data keyed by assets, use the
  `AssetIndexedDataNode` skill and docs instead.
- For price histories, do not add price columns to asset or detail tables.
- For portfolio or holding semantics, use portfolio-specific models.
- For provider lookup services, keep API-key and normalization logic in
  services, then persist only normalized asset/detail rows.

## Validation Checklist

When changing asset extension code, verify:

- `AssetTable` did not gain extension columns.
- new asset type strings are represented by `AssetType`.
- one-to-one detail tables use `asset_uid` as the only primary key.
- detail table foreign keys point to `AssetTable.uid` and use cascade delete when
  the detail row should not outlive the asset.
- Pydantic row models, repository helpers, tests, docs, and examples match the
  table identity shape.
- startup examples call `msm.start_engine(models=[DetailTable])` after SDK
  migrations, not direct registration or row-level schema helpers.
