# Currency And Currency Spot Assets

Single currencies and currency spot pairs are separate asset concepts.

- Single currencies such as `USD` and `EUR` are canonical `Asset` rows with
  `asset_type="currency"`.
- Currency spot pairs such as `EUR/USD` are canonical `Asset` rows with
  `asset_type="currency_spot"` plus a `CurrencySpotAssetDetailsTable` detail row that links
  the pair to its base and quote currency assets.

```text
+-----------------------------+        one-to-one extension     +-----------------------------+
| AssetTable                  |-------------------------------->| CurrencySpotAssetDetailsTable           |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | base_currency_uid    FK     |
| asset_type = currency_spot  |                                 | quote_currency_uid   FK     |
+-----------------------------+                                 +-----------------------------+
             ^                                                           |
             |                                                           |
             +------------- base_currency_uid / quote_currency_uid -------+
```

## Scope

Currency code metadata, such as `USD` -> `US Dollar`, is not part of the core
library. Keep that mapping in user code, a provider integration, or an
application-specific reference source.

Use `CurrencySpot` for tradable spot pair identity such as `EUR/USD`. The base
and quote currencies must already be `Asset` rows. This makes the component
currency identity explicit instead of hiding asset creation inside the spot-pair
workflow.

Do not add currency-specific columns to `AssetTable`. The core asset table owns
only stable identity fields. The relational base/quote relationship belongs to
`CurrencySpotAssetDetailsTable`.

## API

Application code should use `msm.api.assets.CurrencySpot` for the pair workflow.
The API owns the multi-table pair write, so callers do not pass table handles or
repository contexts.

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

`CurrencySpot.upsert(...)` performs these writes:

1. upsert `AssetType(asset_type="currency_spot")`;
2. upsert `Asset(unique_identifier=<pair>, asset_type="currency_spot")`;
3. upsert `CurrencySpotAssetDetailsTable(asset_uid=<pair uid>, base_currency_uid=..., quote_currency_uid=...)`;
4. return a typed `CurrencySpot` object with the pair asset identity and
   base/quote currency references.

The current API requires `base_currency_uid` and `quote_currency_uid`; it does
not silently create those component assets from strings.

## Asset Type Normalization

Typed asset APIs normalize asset type keys before writing them:

```text
"Currency"      -> "currency"
"Currency Spot" -> "currency_spot"
"Future"        -> "future"
```

Friendly text belongs in `AssetType.display_name` and `description`, not in the
stored `asset_type` key.

## Schema

`CurrencySpotAssetDetailsTable` is declared under `msm.models.assets.currency_spot` and is
exported through `msm.models`.

Key constraints:

- `asset_uid` is both the primary key and a foreign key to `AssetTable.uid`.
- `asset_uid` cascades on delete because the detail row should not outlive the
  pair asset.
- `base_currency_uid` and `quote_currency_uid` restrict deletion of component
  currency assets while pairs reference them.
- `(base_currency_uid, quote_currency_uid)` is unique in this first
  implementation.
- the typed API rejects rows where base and quote are the same currency asset.

## Registration

`CurrencySpot.__required_tables__` declares the minimum dependency set in order:

```text
AssetTypeTable
AssetTable
CurrencySpotAssetDetailsTable
```

Production code normally assumes these MetaTables already exist. Application
startup can register the dependency set explicitly:

```python
import msm

msm.start_engine(models=["AssetType", "Asset", "CurrencySpotAssetDetails"])
```

Examples and development scripts can set `MSM_AUTO_REGISTER_NAMESPACE` before
importing the API classes when they need an example namespace, but they still
must call `msm.start_engine(...)` during startup before row operations.

## Example

See `examples/msm/assets/currency_spot_workflow.py` for a workflow that registers
`USD` and `EUR` currency assets, resolves `BBG0013HGRV5` through OpenFIGI,
creates the `EUR/USD` `CurrencySpot`, and writes an `AssetSnapshot` for the
currencies and the spot pair.
