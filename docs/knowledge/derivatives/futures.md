# Futures

Futures are tradable assets whose contract terms are stored in a derivative
detail table.

In the current implementation, a future is a canonical `Asset` row with
`asset_type="future"`. The underlying is an `IndexTable` row, not another
`Asset`. This avoids creating fake assets for indexes just to satisfy a foreign
key.

```text
+-----------------------------+        one-to-one extension     +-----------------------------+
| AssetTable                  |-------------------------------->| FutureDetailsTable          |
|-----------------------------|        asset_uid PK/FK          |-----------------------------|
| uid                  PK     |                                 | asset_uid            PK/FK  |
| unique_identifier    unique |                                 | kind                        |
| asset_type = future         |                                 | underlying_index_uid FK     |
+-----------------------------+                                 | quote_unit                  |
                                                               | settlement_asset            |
                                                               | margin_asset                |
                                                               | settlement_model            |
                                                               | settlement_method           |
                                                               | contract_size               |
                                                               | contract_unit               |
                                                               | expires_at                  |
                                                               | settles_at                  |
                                                               | metadata                    |
                                                               +-----------------------------+
             +-----------------------------+
             | IndexTable                  |
             |-----------------------------|
             | uid                  PK     |
             | unique_identifier    unique |
             | display_name                |
             +-----------------------------+
```

## API

Application code should use `msm.api.derivatives.Future`. The class owns the
multi-table workflow, so callers do not pass MetaTable handles or repository
contexts.

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

`Future.upsert(...)` performs these writes:

1. upsert `AssetType(asset_type="future")`;
2. upsert `Asset(unique_identifier=<future>, asset_type="future")`;
3. upsert `FutureDetailsTable(asset_uid=<future uid>, ...)`;
4. return a typed `Future` object with the asset identity and contract terms.

OpenFIGI-backed workflows can resolve both the underlying index FIGI and the
future FIGI while keeping contract economics explicit:

```python
from decimal import Decimal

from msm.api.assets import Asset
from msm.services import register_index_future_from_figis

usd = Asset.upsert(unique_identifier="USD", asset_type="currency")
future = register_index_future_from_figis(
    "BBG01SWCTHK4",
    underlying_index_figi="BBG000KKFC45",
    settlement_asset_uid=usd.uid,
    margin_asset_uid=usd.uid,
    kind="EXPIRING",
    quote_unit="INDEX_POINT",
    settlement_model="LINEAR",
    settlement_method="CASH",
    contract_size=Decimal("50"),
    contract_unit="INDEX_POINT",
    expires_at="2026-12-18T22:00:00Z",
    settles_at="2026-12-18T22:00:00Z",
)
```

The helper requires the underlying index OpenFIGI row to have
`marketSector="Index"`. It does not infer settlement asset, margin asset,
contract size, or expiry from OpenFIGI.

See `examples/assets/derivatives/index_future_from_openfigi.py` for the concrete
workflow using index FIGI `BBG000KKFC45` and future FIGI `BBG01SWCTHK4`.

## Contract Fields

| Field | Meaning |
| --- | --- |
| `kind` | `PERPETUAL` or `EXPIRING`. |
| `underlying_index_uid` | `IndexTable.uid` of the underlying index. |
| `quote_unit` | Unit used to quote price, such as `USD`, `USDT`, or `INDEX_POINT`. |
| `settlement_asset` | `Asset.uid` of the asset used for settlement. |
| `margin_asset` | `Asset.uid` of the asset posted as margin. |
| `settlement_model` | `LINEAR`, `INVERSE`, `QUANTO`, or `UNKNOWN`. |
| `settlement_method` | `CASH`, `PHYSICAL`, or `UNKNOWN`. |
| `contract_size` | Positive size of one contract. |
| `contract_unit` | Contract-size unit, such as `INDEX_POINT` or another venue-defined unit. |
| `expires_at` | Required for `EXPIRING`, null for `PERPETUAL`. |
| `settles_at` | Final settlement or delivery timestamp, nullable for perpetuals. |
| `metadata` | JSON escape hatch for rare venue-specific attributes. |

## Validation

The typed API currently validates:

- canonical enum values, accepting lower-case or mixed-case input;
- `PERPETUAL` futures have no `expires_at`;
- `EXPIRING` futures have `expires_at`;
- positive `contract_size`;
- non-empty normalized `quote_unit` and `contract_unit`.

The SQLAlchemy contract declares foreign keys for `underlying_index_uid`,
`settlement_asset`, and `margin_asset`. Pre-write API checks that referenced
rows exist are still tracked as an open ADR task.

## Registration

`Future.__required_tables__` declares the minimum dependency set in order:

```text
AssetTypeTable
AssetTable
IndexTable
FutureDetailsTable
```

Production code normally assumes these MetaTables already exist. Application
startup can register only this dependency set explicitly:

```python
from msm.api.derivatives import Future

Future.create_schemas()
```

Examples and development scripts can instead set `MSM_AUTO_REGISTER_NAMESPACE`
before importing the API classes.

## Boundaries

The current `Future` workflow is for index-underlying futures. Do not add
nullable polymorphic columns for asset, rate, or other underlyings into
`FutureDetailsTable`. Add a later ADR when another underlying reference model
exists.

## Related Concepts

- [Indexes](../indices/index.md)
- [Assets](../assets/index.md)
- [Asset-Indexed DataNodes](../assets/asset_indexed_data_nodes.md)
