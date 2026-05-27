# Bond Assets

Bonds are canonical `Asset` rows with `asset_type="bond"` plus a one-to-one
`BondDetailsTable` row for issuer, currency, lifecycle dates, and status.

Issuers are reference data, not assets. Use `Issuer` for the issuer row and
link the bond detail row to `IssuerTable.uid`.

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

## Scope

The bond extension stores minimal asset identity facts:

- who issued the bond;
- which currency asset denominates it;
- issue and maturity dates;
- lifecycle status.

It does not store coupons, schedules, day-count conventions, curves, accrued
interest, or serialized pricing terms. Those belong in pricing or instrument
contracts.

## API

Application code should use `msm.api.issuers.Issuer` and
`msm.api.assets.Bond`.

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

`Bond.upsert(...)` performs these writes:

1. verify `issuer_uid` resolves to an `IssuerTable` row;
2. verify `currency_asset_uid` resolves to an `AssetTable` row;
3. upsert `AssetType(asset_type="bond")`;
4. upsert `Asset(unique_identifier=<bond>, asset_type="bond")`;
5. upsert `BondDetailsTable(asset_uid=<bond uid>, ...)`;
6. return a typed `Bond` object with the asset identity and detail fields.

## Schema

`IssuerTable` is declared under `msm.models.issuers`.

| Field | Meaning |
| --- | --- |
| `uid` | Internal issuer row identity. |
| `unique_identifier` | Stable local or provider issuer identity. |
| `display_name` | Human-readable issuer name. |
| `metadata_json` | Optional provider-specific issuer attributes. |

`BondDetailsTable` is declared under `msm.models.assets.bonds`.

| Field | Meaning |
| --- | --- |
| `asset_uid` | Primary key and foreign key to the canonical bond asset. |
| `issuer_uid` | Foreign key to `IssuerTable.uid`. |
| `currency_asset_uid` | Foreign key to the currency `AssetTable.uid`. |
| `issue_date` | Date the bond was issued. |
| `maturity_date` | Date the bond matures, nullable for perpetual bonds. |
| `status` | `ACTIVE`, `MATURED`, `DEFAULTED`, `CALLED`, `REDEEMED`, or `UNKNOWN`. |

`asset_uid` cascades on asset deletion because the detail row should not outlive
the bond asset. `issuer_uid` and `currency_asset_uid` restrict deletion while
bonds reference those rows.

## Registration

`Bond.__required_tables__` declares the minimum dependency set in order:

```text
AssetTypeTable
AssetTable
IssuerTable
BondDetailsTable
```

Production code normally assumes these MetaTables already exist. Application
startup can register this dependency set explicitly:

```python
from msm.api.assets import Bond

Bond.create_schemas()
```

Examples and development scripts can instead set `MSM_AUTO_REGISTER_NAMESPACE`
before importing the API classes.

## Example

See `examples/assets/bond_workflow.py` for a minimal workflow that creates an
issuer, a USD currency asset, and a USD bond using the user-facing API.
