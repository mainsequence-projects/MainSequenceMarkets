---
name: mainsequence-asset-model-extension
description: Use this skill when extending or reviewing the ms-markets Asset model, including AssetType registration and one-to-one asset property/detail tables. This skill owns the rule that AssetTable stays small and extension data belongs in relational detail tables keyed by AssetTable.uid. It does not own AssetIndexedUpdater design, price history, portfolios, or general TimeIndexTableUpdater implementation.
---

# Main Sequence Markets Asset Model Extension

Use this skill when an agent needs to add, review, or document asset identity
extensions in `ms-markets`.

If Assets are only component subjects for a calculated spread, basket, ratio,
or hedged market observable, route the methodology to the derived-index
workflow skill. Keep only Asset identity and detail-table changes here.

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

Recommended SQLAlchemy shape for a project's detail table:

```python
import uuid

from metatables import sqlalchemy_naming_convention
from sqlalchemy import ForeignKey, MetaData, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from msm.base import MarketsMetaTableMixin
from msm.models import AssetTable


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class MyProjectMarketsMetaTableMixin(MarketsMetaTableMixin):
    __abstract__ = True
    __metatable_namespace__ = "com.my_project"
    __markets_storage_app__ = "my_project_markets"


class MyAssetDetailsTable(MyProjectMarketsMetaTableMixin, Base):
    __markets_base_identifier__ = "MyAssetDetails"
    __metatable_description__ = "Project asset details keyed one-to-one by AssetTable.uid."

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(AssetTable.__table__.c.uid, ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        info={"description": "Canonical AssetTable uid for this detail row."},
    )
    internal_asset_class: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={"description": "Internal asset class assigned by the project."},
    )
```

`Base` is the project's own declarative base, never `MarketsBase`, and the
project's migration provider targets `Base.metadata`
(`platform/metatable_migrations`). The key passes Markets' column object, because
a key given as text resolves only inside one metadata. Only built-in ms-markets
models, such as `FutureAssetDetailsTable`, are declared on `MarketsBase`.

Add only fields that belong to that specific extension. Use indexed columns for
lookup keys and JSON/text columns for provider payloads when the payload is not
part of the canonical asset identity.

For project-local extension tables, define an abstract project-local mixin with
the project's default `__metatable_namespace__` and, when needed,
`__markets_storage_app__`. Concrete extension tables should declare
`__markets_base_identifier__` as the bare table concept. ms-markets combines the
mixin namespace and base identifier into the globally unique MetaTable identity
used by runtime attachment.

The mixin namespace is final. Isolated tests and examples use a separate database,
such as MetaTables' local SQLite runtime, selected with
`metatables.configure_local_client()` before client models are imported.

Changing `__metatable_namespace__` or `__markets_storage_app__` after the table
has been migrated and registered is a logical or physical table rotation and
must go through the MetaTables migration and registration path.

## Public API Pattern

After the MetaTables migration provider has migrated and registered the SQLAlchemy
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
from my_project.markets_models import MyAssetDetailsTable


class MyAssetDetails(MarketsMetaTableRow):
    __table__ = MyAssetDetailsTable
    __required_tables__ = [MyAssetDetailsTable]
    __upsert_keys__ = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    internal_asset_class: str

msm.start_engine(models=[MyAssetDetailsTable])
```

`MarketsMetaTableRow` is the Pydantic row-operation wrapper. It is not
registered as a backend MetaTable. The SQLAlchemy detail model class is the
registered backend artifact. If generic row helpers expect `uid`, expose `uid`
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
- do not register assets with raw ticker symbols as `Asset.unique_identifier`;
  tickers can collide, change, and require exchange/security context
- when only a ticker is available for a listed provider-backed asset, resolve it
  through OpenFIGI with the required market/exchange/security context and use
  the resolved FIGI as the stable `Asset.unique_identifier`
- store raw provider response separately from normalized lookup columns
- preserve existing column mappings such as `metadata_text =
  mapped_column("metadata", Text, nullable=True)`

## Trading Calendar Link: Required For Price Interpolation

`AssetCalendar` is the one-to-one detail table that links an asset to the stored
`Calendar` whose sessions decide its price bars (ADR 0056). Name the calendar
when you register the asset (ADR 0057):

```python
from msm.api.assets import Asset, AssetCalendar
from msm.api.calendars import Calendar

Calendar.create_from_pandas_calendar("24/7", "CRYPTO_24_7", display_name="Crypto 24/7")
Calendar.create_from_pandas_calendar("NYSE")

Asset.upsert_many(
    [
        {"unique_identifier": "example-asset-btc", "asset_type": "crypto", "calendar_identifier": "CRYPTO_24_7"},
        {"unique_identifier": "example-asset-acme", "asset_type": "equity", "calendar_identifier": "NYSE"},
        {"unique_identifier": "USD", "asset_type": "currency"},
    ]
)
```

Assets that already exist are linked in one call, by identifier:

```python
result = AssetCalendar.link_many(
    ["example-asset-acme", "example-asset-beta"],
    calendar_identifier="NYSE",
)
result.linked, result.moved, result.unchanged, result.unknown
```

Rules:

- Link every asset that will have price bars when you register it. A payload
  without `calendar_identifier` or `calendar_uid` leaves the asset as it is: a
  new asset then has no trading calendar.
- `calendar_identifier` is the stored calendar's `unique_identifier`. Every
  payload that writes an asset takes it: `Asset.create`, `Asset.upsert`,
  `Asset.upsert_many`, `CurrencySpot`, `Bond`, `Future`, and each asset of an
  account registration.
- A payload that names a calendar moves an asset that is on another one. An
  account registration does not: it links only an asset that has no calendar.
- The calendar must exist first. With an unknown calendar, `Asset.upsert_many`
  fails after writing the assets; send the same call again once the calendar is
  stored. An account registration is refused before it writes anything.
- Link many existing assets with `AssetCalendar.link_many`, in one transaction.
  Do not loop over `AssetCalendar.upsert`. Read `result.unknown`: an identifier
  no asset has is reported, not refused.
- `AssetCalendar.unlinked_assets(asset_type=...)` lists the assets with no
  trading calendar. `AssetCalendar.delete(asset_uid)` removes a link.
- There is no default calendar. Never assume an unlinked asset is 24/7; link a
  24/7 asset to a stored 24/7 calendar.
- `InterpolatedPrices` resolves the link of every asset in its scope before it
  reads a bar. One unlinked asset fails the whole run with
  `AssetCalendarMissingError`, which names each such asset. Fix it by linking the
  asset, not by catching the error or skipping the asset.
- Do not pass a calendar in the asset scope. A `calendar` key in a scope mapping
  is refused.
- Do not link an asset to a calendar nobody chose, in a migration or a job, to
  make a run pass.
- An asset that is never interpolated, such as a currency used only as a
  denomination, needs no link.

## Boundaries

- For timestamped or panel data keyed by assets, use the
  `AssetIndexedUpdater` skill and docs instead.
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
- a project's detail table is on the project's own declarative base and passes
  column objects to its keys to Markets; only built-in tables are on `MarketsBase`.
- Pydantic row models, repository helpers, tests, docs, and examples match the
  table identity shape.
- startup examples call `msm.start_engine(models=[DetailTable])` after MetaTables
  migrations, not direct registration or row-level schema helpers.
