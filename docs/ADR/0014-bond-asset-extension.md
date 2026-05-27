# 0014. Bond Asset And Issuer Extension

## Status

Accepted

## Context

`AssetTable` is the canonical asset registry and must remain small. A bond is a
tradable asset, so it should have a canonical `Asset` row, but bond-specific
issuer, currency, and lifecycle fields do not belong on `AssetTable`.

The first bond model should also stay separate from pricing. Coupon schedules,
day count conventions, discount curves, instrument serialization, and valuation
inputs belong to pricing-specific models or the current pricing-details ADR.
This ADR only covers the minimal relational identity extension needed to
register a bond as an asset.

## Decision

Add a first-class `bond` asset extension using issuer reference data and a
one-to-one bond detail table.

### Asset Type

The normalized asset type key is:

```text
bond
```

Human labels belong in `AssetType.display_name`, not in the stored
`asset_type` key.

Expected asset type registration:

```python
from msm.api.assets import AssetType

AssetType.upsert(
    asset_type="bond",
    display_name="Bond",
    description="Debt instruments represented as tradable assets.",
)
```

### Issuer Table

Create a platform-managed MetaTable declaration:

```text
IssuerTable
```

Issuers are reference data, not assets. Do not force issuers into `AssetTable`
just to make bond foreign keys work.

Initial columns:

| Property | Type | Meaning |
| --- | --- | --- |
| `uid` | UUID PK | Internal issuer row identity. |
| `unique_identifier` | string unique | Stable local or provider issuer identity. |
| `display_name` | string | Human-readable issuer name. |
| `metadata_json` | JSON nullable | Provider-specific issuer attributes that are not yet canonical. |

Expose a user-facing issuer API under:

```python
from msm.api.issuers import Issuer
```

### Bond Detail Table

Create a platform-managed MetaTable declaration:

```text
BondDetailsTable
```

The table is a one-to-one extension of the canonical bond asset row:

```text
+-----------------------------+        one-to-one extension     +-----------------------------+
| AssetTable                  |-------------------------------->| BondDetailsTable            |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | issuer_uid           FK     |
| asset_type = bond           |                                 | currency_asset_uid   FK     |
+-----------------------------+                                 | issue_date                 |
             ^                                                  | maturity_date              |
             |                                                  | status                     |
             +------------------------ currency_asset_uid -------+-----------------------------+
                                      issuer_uid
                                           |
                                           v
                              +-----------------------------+
                              | IssuerTable                 |
                              |-----------------------------|
                              | uid                  PK     |
                              | unique_identifier    unique |
                              | display_name                |
                              +-----------------------------+
```

Initial columns:

| Property | Type | Meaning |
| --- | --- | --- |
| `asset_uid` | UUID PK/FK | Canonical `AssetTable.uid` for the bond asset. |
| `issuer_uid` | UUID FK | Canonical `IssuerTable.uid` for who issued the bond. |
| `currency_asset_uid` | UUID FK | Currency `AssetTable.uid` for the bond denomination. |
| `issue_date` | date | Date the bond was issued. |
| `maturity_date` | date nullable | Date the bond matures; null for perpetual bonds. |
| `status` | enum/string | One of `ACTIVE`, `MATURED`, `DEFAULTED`, `CALLED`, `REDEEMED`, or `UNKNOWN`. |

Use `issuer_uid` and `currency_asset_uid` in the table and API, not generic
`issuer` or `currency` attributes, because both fields store foreign keys.

Do not add a separate `uid` column to `BondDetailsTable`. If a Pydantic row
helper needs a `uid` field, expose `uid` as an alias of `asset_uid`.

### Foreign Keys And Deletion

Foreign-key behavior:

- `asset_uid` references `AssetTable.uid` and uses `ondelete="CASCADE"` because
  the bond detail row must not outlive the canonical bond asset.
- `issuer_uid` references `IssuerTable.uid` and should not cascade, because
  deleting an issuer while bonds reference it should be blocked by the backend.
- `currency_asset_uid` references `AssetTable.uid` and should not cascade,
  because deleting a currency asset while bonds reference it should be blocked
  by the backend.

### Indexes

Add indexes for lookup workflows:

- `issuer_uid`
- `currency_asset_uid`
- `status`
- `maturity_date`

The primary key on `asset_uid` is the one-to-one uniqueness constraint.

### Public API Shape

Expose the user-facing model under:

```python
from msm.api.assets import Bond
```

Expected usage:

```python
import datetime as dt

from msm.api.assets import Asset, AssetType, Bond
from msm.api.issuers import Issuer

AssetType.upsert(asset_type="currency", display_name="Currency")
AssetType.upsert(asset_type="bond", display_name="Bond")

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

`Bond.upsert(...)` should:

1. verify `issuer_uid` resolves to an `IssuerTable` row;
2. verify `currency_asset_uid` resolves to an `AssetTable` row;
3. ensure or upsert `AssetType(asset_type="bond")`;
4. upsert the canonical `Asset` with `asset_type="bond"`;
5. upsert `BondDetailsTable` keyed by `asset_uid`;
6. return a typed `Bond` object with the asset identity and bond detail fields.

Users should not pass MetaTable handles or repository contexts.

### Validation

The typed API should enforce:

- `status` is one of `ACTIVE`, `MATURED`, `DEFAULTED`, `CALLED`, `REDEEMED`, or
  `UNKNOWN`, accepting lower-case or mixed-case input and normalizing to the
  canonical value.
- `maturity_date` may be null for perpetual bonds.
- when `maturity_date` is present, it must not be earlier than `issue_date`.
- `issuer_uid` resolves to an existing `IssuerTable` row before writing if the
  API is expected to reject missing references before backend FK enforcement.
- `currency_asset_uid` resolves to an existing `Asset` row before writing if the
  API is expected to reject missing references before backend FK enforcement.

The first implementation should not infer lifecycle status from dates. Status
is a stored issuer/provider/workflow fact and may be updated independently.

### Registration Dependencies

The required table order is:

```text
AssetTypeTable
AssetTable
IssuerTable
BondDetailsTable
```

`Issuer.__required_tables__` should include `IssuerTable`.
`Bond.__required_tables__` should include all required tables in dependency
order so lazy runtime resolution and optional development auto-registration can
register the minimum correct schema set.

## Consequences

`AssetTable` remains stable and does not gain bond-specific columns.

Bond rows become normal assets. They can be referenced by portfolios, orders,
trades, DataNodes, provider detail tables, and pricing-details rows through the
same canonical `Asset.uid` and `Asset.unique_identifier` surfaces.

The model deliberately avoids coupons, schedules, accrued interest, and pricing
terms. Those belong to pricing/instrument-specific contracts, not to the minimal
bond asset identity extension.

## Implementation Tasks

- [x] Add `IssuerTable` under `src/msm/models/issuers.py` or a dedicated
  reference-data module.
- [x] Add `uid`, `unique_identifier`, `display_name`, and `metadata_json`
  columns to `IssuerTable`.
- [x] Add unique and lookup indexes for `IssuerTable.unique_identifier` and
  `IssuerTable.display_name`.
- [x] Add the user-facing `msm.api.issuers.Issuer` row model and payload
  models.
- [x] Add `BondDetailsTable` under `src/msm/models/assets/` or a dedicated
  assets submodule.
- [x] Use `asset_uid` as the only primary key and as a foreign key to
  `AssetTable.uid` with `ondelete="CASCADE"`.
- [x] Add `issuer_uid`, `currency_asset_uid`, `issue_date`, `maturity_date`, and
  `status` columns.
- [x] Add a foreign key from `issuer_uid` to `IssuerTable.uid` without cascade
  delete.
- [x] Add a foreign key from `currency_asset_uid` to `AssetTable.uid` without
  cascade delete.
- [x] Add indexes for `issuer_uid`, `currency_asset_uid`, `status`, and
  `maturity_date`.
- [x] Add the user-facing `msm.api.assets.Bond` row model and payload models.
- [x] Add `BondStatus` enum values: `ACTIVE`, `MATURED`, `DEFAULTED`, `CALLED`,
  `REDEEMED`, and `UNKNOWN`.
- [x] Add `Bond.upsert(...)` as the class-owned multi-table workflow.
- [x] Add typed validation for status normalization and
  `maturity_date >= issue_date` when maturity is present.
- [x] Add runtime validation for `issuer_uid` and `currency_asset_uid`
  resolution if this project chooses to reject missing references before backend
  FK enforcement.
- [x] Add tests under `tests/msm/api/` and `tests/msm/models/` for table shape,
  dependency order, enum normalization, validation, and the upsert workflow.
- [x] Add dedicated bond docs under `docs/knowledge/assets/bonds.md` and link
  them from the asset knowledge page.
- [x] Add an example under `examples/assets/` using the user-facing API only.
- [x] Update tutorial material and changelog when implemented.
- [x] Update ms-markets asset skills if the final implementation changes the
  asset-extension workflow described there.
