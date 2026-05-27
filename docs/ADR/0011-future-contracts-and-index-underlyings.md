# 0011. Future Contracts And Index Underlyings

## Status

Proposed

## Context

The previous `future_on_asset` design is too narrow. A future contract is a
tradable market asset, but the underlying is not always another `Asset`.
Important futures often reference indexes, and those indexes should not be
forced into `AssetTable` only to satisfy a foreign key.

`AssetTable` should stay the canonical registry for tradable assets. A future
contract can still be represented as an `Asset` row with `asset_type="future"`,
but the underlying reference needs its own model when the underlying is an
index.

This ADR introduces two related concepts:

- `IndexTable`: a first-class row-oriented reference table for market indexes.
- `FutureDetailsTable`: a one-to-one extension of a canonical future `Asset`
  row whose underlying is an `IndexTable` row in the first implementation.

This avoids pretending that index underlyings are assets while preserving the
library rule that users operate through typed API classes instead of table
handles.

## Decision

Add first-class index reference data and a futures extension keyed by a
canonical future asset.

### Index Model

Create a platform-managed MetaTable declaration:

```text
IndexTable
```

`IndexTable` is not an asset extension. It is a reference entity for indexes
that may be used as underlyings by derivatives.

Initial columns:

| Property | Type | Meaning |
| --- | --- | --- |
| `uid` | UUID PK | Internal row identity. |
| `unique_identifier` | string unique | Stable index identity, for example `SPX`, `NDX`, or provider-specific IDs. |
| `display_name` | string | Human-readable name. |
| `description` | text nullable | Optional explanation of the index. |
| `provider` | string nullable | Optional provider/source namespace. |
| `metadata_json` | JSON nullable | Escape hatch for provider-specific reference fields. |

Expose a public API model:

```python
from msm.api.indices import Index
```

`Index` should support the normal row API methods, including
`Index.create_schemas(...)`, `Index.upsert(...)`, `Index.get_by_uid(...)`, and
`Index.filter(...)`.

### Future Asset Type

The asset type key is:

```text
future
```

Do not use `future_on_asset` for this model. Human labels such as
`"Future"` belong in `AssetType.display_name`.

The future contract itself is still a canonical `Asset` row:

```text
Asset(asset_type="future")
```

The contract-specific terms belong in a detail table.

### Future Details Table

Create a platform-managed MetaTable declaration:

```text
FutureDetailsTable
```

The table is a one-to-one extension of the future asset row and references an
index underlying:

```text
+-----------------------------+        one-to-one extension     +-----------------------------+
| AssetTable                  |-------------------------------->| FutureDetailsTable          |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | kind                 enum   |
| asset_type=future           |                                 | underlying_index_uid FK     |
+-----------------------------+                                 | quote_unit           string |
                                                               | settlement_asset     FK     |
                                                               | margin_asset         FK     |
                                                               | settlement_model    enum   |
                                                               | settlement_method   enum   |
                                                               | contract_size       decimal|
                                                               | contract_unit       string |
                                                               | expires_at          ts?    |
                                                               | settles_at          ts?    |
                                                               | metadata            JSON   |
                                                               +-----------------------------+
             +-----------------------------+
             | IndexTable                  |
             |-----------------------------|
             | uid                  PK     |
             | unique_identifier    unique |
             | display_name                |
             +-----------------------------+
```

Columns:

| Property | Type | Meaning |
| --- | --- | --- |
| `asset_uid` | FK to `AssetTable.uid`, PK | The canonical future asset row being extended. |
| `kind` | enum | `PERPETUAL` or `EXPIRING`. |
| `underlying_index_uid` | FK to `IndexTable.uid` | The canonical index underlying. |
| `quote_unit` | string | Unit used to quote the future price, for example `USD`, `USDT`, or `INDEX_POINT` when appropriate for the index future. |
| `settlement_asset` | FK to `AssetTable.uid` | Asset used for settlement, typically a currency asset. |
| `margin_asset` | FK to `AssetTable.uid` | Asset posted as margin, typically a currency asset. |
| `settlement_model` | enum | `LINEAR`, `INVERSE`, `QUANTO`, or `UNKNOWN`. |
| `settlement_method` | enum | `CASH`, `PHYSICAL`, or `UNKNOWN`. |
| `contract_size` | decimal | Size of one contract. |
| `contract_unit` | string | Unit of the contract size, for example `INDEX_POINT`, `USD`, or another venue-defined unit. |
| `expires_at` | timestamp nullable | Expiration timestamp. Must be null for perpetuals. |
| `settles_at` | timestamp nullable | Final settlement or delivery time. Nullable for perpetuals. |
| `metadata` | JSON | Escape hatch for rare non-standard attributes. |

Implementation note: SQLAlchemy declarative classes reserve the `metadata`
attribute name through the base metadata object. The physical column should be
named `metadata`, but the SQLAlchemy class should use a Python-safe attribute
such as `metadata_payload = mapped_column("metadata", JSON, nullable=True)`.
The public API may expose the field as `metadata` if the row model can alias it
cleanly.

### Enums

Use strict enum values in the typed API:

```text
FutureKind: PERPETUAL, EXPIRING
FutureSettlementModel: LINEAR, INVERSE, QUANTO, UNKNOWN
FutureSettlementMethod: CASH, PHYSICAL, UNKNOWN
```

The API may accept lower-case or mixed-case input and normalize it, but examples
and docs should use canonical enum values.

### Validation

The typed API must enforce:

- `asset_type` for the future asset is `future`.
- `underlying_index_uid` references an existing `IndexTable` row.
- `settlement_asset` and `margin_asset` reference existing `Asset` rows.
- `kind="PERPETUAL"` requires `expires_at is None`.
- `kind="EXPIRING"` requires `expires_at` to be present.
- `contract_size` must be positive.
- `quote_unit` and `contract_unit` must be non-empty normalized strings.

Backend constraints should enforce what the MetaTable registration surface
supports, but the typed API must reject invalid payloads before writes.

### Public API Shape

Expose the index API under:

```python
from msm.api.indices import Index
```

Expose the future workflow under a derivatives-oriented API module:

```python
from msm.api.derivatives import Future
```

Expected usage:

```python
from decimal import Decimal

from msm.api.assets import Asset
from msm.api.derivatives import Future
from msm.api.indices import Index

spx = Index.upsert(
    unique_identifier="SPX",
    display_name="S&P 500 Index",
    provider="example",
)
usd = Asset.upsert(unique_identifier="USD", asset_type="currency")

future = Future.upsert(
    unique_identifier="CME:ESZ6",
    kind="EXPIRING",
    underlying_index_uid=spx.uid,
    quote_unit="INDEX_POINT",
    settlement_asset=usd.uid,
    margin_asset=usd.uid,
    settlement_model="LINEAR",
    settlement_method="CASH",
    contract_size=Decimal("50"),
    contract_unit="INDEX_POINT",
    expires_at="2026-12-18T22:00:00Z",
    settles_at="2026-12-18T22:00:00Z",
    metadata={"venue": "CME", "root": "ES"},
)
```

`Future.upsert(...)` should:

1. ensure or upsert `AssetType(asset_type="future")`;
2. upsert the canonical future `Asset`;
3. upsert `FutureDetailsTable` keyed by the future asset UID;
4. return a typed `Future` object with asset identity and contract detail
   fields.

Users should not pass MetaTable handles or repository contexts.

### Registration Dependencies

The required table order is:

```text
AssetTypeTable
AssetTable
IndexTable
FutureDetailsTable
```

`Index.__required_tables__` should include `IndexTable`.
`Future.__required_tables__` should include all required tables in dependency
order so lazy runtime resolution and optional development auto-registration can
register the minimum correct schema set.

## Consequences

This keeps `AssetTable` stable while recognizing that some underlyings are not
assets. Futures remain usable anywhere the platform expects a tradable asset
through `Asset.uid` and `Asset.unique_identifier`, while index reference data
gets its own row model and API surface.

This ADR intentionally implements futures whose underlying is an index. Futures
on assets, rates, or other underlying types should not be modeled with nullable
polymorphic columns in this table. Add a later ADR once the corresponding
reference model and API contract exist.

Using `metadata` as an escape hatch keeps the table practical for rare venue
attributes without widening `AssetTable` or `IndexTable` with provider-specific
fields. Common fields should graduate into explicit columns through follow-up
ADRs when they become part of the library contract.

## Implementation Tasks

- [x] Add `IndexTable` under `src/msm/models/indices.py` or a dedicated
  `src/msm/models/indices/` package.
- [x] Add the user-facing `msm.api.indices.Index` row model and payload models.
- [x] Export `Index` from `msm.api` without placing it under `msm.api.assets`.
- [x] Add enum definitions for future kind, settlement model, and settlement
  method in the derivatives typed API.
- [x] Add `FutureDetailsTable` under a derivatives-oriented model module.
- [x] Add `FutureDetailsTable` to model exports and MetaTable registration
  order after `AssetTable` and `IndexTable`.
- [x] Add foreign keys for `asset_uid`, `underlying_index_uid`,
  `settlement_asset`, and `margin_asset`.
- [x] Add indexes for `underlying_index_uid`, `settlement_asset`,
  `margin_asset`, and expiration fields needed by query workflows.
- [x] Add the user-facing `msm.api.derivatives.Future` row model and payload
  models.
- [x] Add `Future.upsert(...)` as the class-owned multi-table workflow.
- [x] Add typed validation for perpetual vs expiring futures, positive
  `contract_size`, and normalized unit fields.
- [ ] Add typed/runtime validation that `underlying_index_uid`,
  `settlement_asset`, and `margin_asset` resolve before writes if the API
  should reject missing references before backend FK enforcement.
- [x] Add tests under `tests/msm/api/`, `tests/msm/models/`, and any new nested
  concept folders for table shape, dependency order, enum normalization,
  validation, and the upsert workflows.
- [x] Add dedicated index docs and futures docs under `docs/knowledge/`.
- [x] Add examples for index registration and index future creation using the
  user-facing API only.
- [ ] Update asset and model skills if the final implementation changes the
  asset-extension workflow described there.
- [ ] Update tutorial material, MkDocs navigation, and changelog when
  implemented.
