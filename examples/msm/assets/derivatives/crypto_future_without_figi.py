from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[4]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (
    EXAMPLE_NAMESPACE_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)
from msm.constants import (
    ASSET_TYPE_CRYPTO,
    ASSET_TYPE_CRYPTO_DEFINITION,
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_DEFINITION,
    INDEX_TYPE_CRYPTO,
    INDEX_TYPE_CRYPTO_DEFINITION,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

EXAMPLE_VENUE = "example_crypto_venue"
EXAMPLE_BASE_CRYPTO = {
    "code": "BTC",
    "name": "Bitcoin",
}
EXAMPLE_MARGIN_CURRENCY = {
    "code": "USDT",
    "name": "Tether USD",
}
EXAMPLE_UNDERLYING_INDEX_IDENTIFIER = "example-crypto-btcusdt-index"
EXAMPLE_FUTURE_IDENTIFIER = "example-crypto-btcusdt-perpetual"


def create_crypto_future_without_figi() -> dict[str, Any]:
    """Create a crypto perpetual future using local identifiers only."""

    msm.start_engine(
        models=["AssetType", "Asset", "IndexType", "Index", "FutureAssetDetails"],
    )

    from msm.api.assets import Asset, AssetType
    from msm.api.derivatives import Future
    from msm.api.indices import Index, IndexType

    crypto_asset_type = AssetType.upsert(**ASSET_TYPE_CRYPTO_DEFINITION.as_payload())
    currency_asset_type = AssetType.upsert(**ASSET_TYPE_CURRENCY_DEFINITION.as_payload())
    crypto_index_type = IndexType.upsert(**INDEX_TYPE_CRYPTO_DEFINITION.as_payload())
    btc = Asset.upsert(
        unique_identifier=EXAMPLE_BASE_CRYPTO["code"],
        asset_type=ASSET_TYPE_CRYPTO,
    )
    usdt = Asset.upsert(
        unique_identifier=EXAMPLE_MARGIN_CURRENCY["code"],
        asset_type=ASSET_TYPE_CURRENCY,
    )
    underlying_index = Index.upsert(
        unique_identifier=EXAMPLE_UNDERLYING_INDEX_IDENTIFIER,
        index_type=INDEX_TYPE_CRYPTO,
        display_name="BTC/USDT Perpetual Reference Index",
        description=(
            "Local crypto venue reference index used as the underlying for a "
            "BTC/USDT perpetual future."
        ),
        metadata_json={
            "venue": EXAMPLE_VENUE,
            "base_asset_uid": str(btc.uid),
            "base_asset_unique_identifier": btc.unique_identifier,
            "quote_asset_uid": str(usdt.uid),
            "quote_asset_unique_identifier": usdt.unique_identifier,
            "figi": None,
        },
    )
    future = Future.upsert(
        unique_identifier=EXAMPLE_FUTURE_IDENTIFIER,
        kind="PERPETUAL",
        underlying_index_uid=underlying_index.uid,
        quote_unit=EXAMPLE_MARGIN_CURRENCY["code"],
        settlement_asset=usdt.uid,
        margin_asset=usdt.uid,
        settlement_model="LINEAR",
        settlement_method="CASH",
        contract_size=Decimal("1"),
        contract_unit=EXAMPLE_BASE_CRYPTO["code"],
        metadata={
            "venue": EXAMPLE_VENUE,
            "venue_symbol": "BTCUSDT-PERP",
            "base_asset_uid": str(btc.uid),
            "margin_asset_uid": str(usdt.uid),
            "figi": None,
            "source": "examples/msm/assets/derivatives/crypto_future_without_figi.py",
        },
    )

    return {
        "crypto_asset_type": crypto_asset_type,
        "currency_asset_type": currency_asset_type,
        "crypto_index_type": crypto_index_type,
        "base_asset": btc,
        "margin_asset": usdt,
        "underlying_index": underlying_index,
        "future": future,
        "future_asset": Asset.get_by_uid(future.asset_uid),
    }


def main() -> None:
    print(create_crypto_future_without_figi())


if __name__ == "__main__":
    main()
