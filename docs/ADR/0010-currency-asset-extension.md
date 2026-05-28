# 0010. Currency Asset Extension

## Status

Accepted

## Context

`ms-markets` is starting its migration toward the newer Main Sequence SDK while
keeping market-domain behavior in the supported `ms-markets` package. The first
asset extension needed for that migration is a relational representation for
currency instruments.

`AssetTable` is the canonical asset registry and must remain small. It should
hold only stable asset identity fields such as `uid`, `unique_identifier`, and
`asset_type`. Currency-specific relationships do not belong on `AssetTable`.

The target workflow is:

```text
Asset(unique_identifier="BBG0013HGRV5", asset_type="currency_spot")
    base_currency  -> Asset(unique_identifier="EUR", asset_type="currency")
    quote_currency -> Asset(unique_identifier="USD", asset_type="currency")
```

This gives the pair itself a canonical asset row while preserving explicit
foreign keys to the canonical assets that form the pair.

The current Main Sequence documentation positions the SDK around generic
platform data products and app-facing row data. `ms-markets` should hide the
underlying table-registration details behind its own typed API so client code
works with market objects such as `Asset`, `AssetType`, and `CurrencySpot`.

## Decision

Add a first-class currency asset extension using relational composition.

### Asset Type Normalization

Client-side `msm.api` asset type registration must normalize asset type keys
before writing them:

```text
"Currency"      -> "currency"
"Currency Spot" -> "currency_spot"
"Asset Future"  -> "asset_future"
"currency pair" -> "currency_pair"
```

Rules:

- strip leading and trailing whitespace;
- lowercase the value;
- replace one or more whitespace runs with `_`;
- reject empty results;
- apply the same normalization to `Asset.asset_type` and
  `AssetType.asset_type` payloads in the typed API.

The database should still store the normalized string. Friendly names belong in
`AssetType.display_name`, not in `asset_type`.

For this extension, the required spot-pair registry key is:

```text
currency_spot
```

The `currency` registry key remains available for single currency assets such
as `USD` and `EUR`.

### Table Shape

Create a new platform-managed MetaTable declaration:

```text
CurrencySpotAssetDetailsTable
```

The table is a one-to-one extension of the pair asset row:

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

Columns:

- `asset_uid`: primary key and foreign key to `AssetTable.uid`.
- `base_currency_uid`: foreign key to `AssetTable.uid`.
- `quote_currency_uid`: foreign key to `AssetTable.uid`.

Foreign-key behavior:

- `asset_uid` should use cascade delete because the detail row should not
  outlive the pair asset.
- `base_currency_uid` and `quote_currency_uid` should restrict deletion of
  component currency assets while currency spot pairs reference them.

Indexes and constraints:

- unique index on `(base_currency_uid, quote_currency_uid)` for the first
  implementation;
- index on `base_currency_uid`;
- index on `quote_currency_uid`;
- reject rows where `base_currency_uid == quote_currency_uid` when the backend
  constraint surface supports it, otherwise enforce this in the typed API.

Do not add a separate `uid` column to `CurrencySpotAssetDetailsTable`. If the generic row
helpers need a `uid` attribute, expose `uid` as an API-model alias of
`asset_uid`, following the existing one-to-one detail-table pattern.

### Public API Shape

Expose a user-facing model under:

```python
from msm.api.assets import CurrencySpot
```

The row API should own the multi-table workflow. Users should not have to pass
table handles or repository contexts.

Expected usage:

```python
from msm.api.assets import Asset, CurrencySpot

EUR = {"code": "EUR", "currency_name": "Euro"}
USD = {"code": "USD", "currency_name": "US Dollar"}

eur = Asset.upsert(unique_identifier=EUR["code"], asset_type="currency")
usd = Asset.upsert(unique_identifier=USD["code"], asset_type="currency")

eur_usd = CurrencySpot.upsert(
    unique_identifier="BBG0013HGRV5",
    base_currency_uid=eur.uid,
    quote_currency_uid=usd.uid,
)
```

`CurrencySpot.upsert(...)` should:

1. ensure or upsert `AssetType(asset_type="currency_spot")`;
2. upsert the pair asset with `asset_type="currency_spot"`;
3. upsert the `CurrencySpotAssetDetailsTable` row keyed by the pair asset UID;
4. return a typed `CurrencySpot` object that includes the pair asset identity
   and base/quote currency references.

The API may also accept `base_unique_identifier` and `quote_unique_identifier`
as convenience inputs if that does not make ambiguity worse. If accepted, those
identifiers must resolve to existing `Asset` rows or be created through an
explicit documented policy.

### Registration Dependencies

The required table order is:

```text
AssetTypeTable
AssetTable
CurrencySpotAssetDetailsTable
```

`CurrencySpot.__required_tables__` should include all required tables in
dependency order so explicit startup bootstrap can initialize the minimum
correct schema set.

## Consequences

This keeps `AssetTable` stable and avoids widening it with extension-specific
columns.

Currency spot pairs become normal assets. That means they can be referenced by
portfolios, orders, trades, DataNodes, and provider detail tables through the
same canonical `Asset.uid` and `Asset.unique_identifier` surfaces.

The `currency_spot` asset type means the tradable spot pair instrument.
Standalone base and quote currencies remain normal `Asset` rows with
`asset_type="currency"`.

The unique `(base_currency_uid, quote_currency_uid)` constraint intentionally
excludes venue-specific duplicate pairs in the first implementation.
Venue-specific pair listings should be modeled later with a provider/listing
extension rather than by overloading the core currency spot relationship.

## Implementation Tasks

- [x] Add a shared asset-type normalizer for the typed API.
- [x] Apply normalization to `AssetTypeCreate`, `AssetTypeUpsert`,
  `AssetCreate`, `AssetUpsert`, and `AssetUpdate`.
- [x] Add tests proving asset type values are lowercased and spaces become
  underscores before repository operations.
- [x] Add `CurrencySpotAssetDetailsTable` under `src/msm/models/assets/`.
- [x] Add `CurrencySpotAssetDetailsTable` to model exports and MetaTable registration
  order after `AssetTable`.
- [x] Add indexes and foreign keys for `asset_uid`, `base_currency_uid`, and
  `quote_currency_uid`.
- [x] Add the user-facing `msm.api.assets.CurrencySpot` row model and payload
  models.
- [x] Add `CurrencySpot.upsert(...)` as the class-owned multi-table workflow.
- [x] Use existing typed runtime resolution and generic repository operations
  inside `CurrencySpot.upsert(...)` without requiring users to pass table
  handles.
- [x] Add tests under `tests/msm/assets/` or `tests/msm/api/` for table shape,
  type normalization, and the currency upsert workflow.
- [x] Add dedicated currency docs at `docs/knowledge/assets/currency.md`.
- [x] Update asset knowledge docs, tutorial material, examples, and changelog.
- [x] Add a minimal ms-markets asset-skill note showing how to create a
  currency asset extension; do not turn the skill into full currency
  documentation.
