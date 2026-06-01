from __future__ import annotations

import datetime as dt
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
    ASSET_TYPE_CURRENCY,
    ASSET_TYPE_CURRENCY_DEFINITION,
    INDEX_TYPE_EQUITY,
    INDEX_TYPE_EQUITY_DEFINITION,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm

EXAMPLE_UNDERLYING_INDEX_FIGI = "BBG000KKFC45"
EXAMPLE_FUTURE_FIGI = "BBG01SWCTHK4"
EXAMPLE_SETTLEMENT_CURRENCY = {
    "code": "USD",
    "currency_name": "US Dollar",
}
EXAMPLE_FUTURE_EXPIRES_AT = dt.datetime(2026, 12, 18, 22, tzinfo=dt.UTC)
EXAMPLE_FUTURE_SETTLES_AT = EXAMPLE_FUTURE_EXPIRES_AT


def create_index_future_from_openfigi() -> dict[str, Any]:
    """Create an index-underlying future using OpenFIGI identities."""

    msm.start_engine(
        models=["AssetType", "Asset", "IndexType", "Index", "FutureAssetDetails"],
    )

    from msm.api.assets import Asset, AssetType
    from msm.api.indices import Index, IndexType
    from msm.services import register_index_future_from_figis

    currency_asset_type = AssetType.upsert(**ASSET_TYPE_CURRENCY_DEFINITION.as_payload())
    equity_index_type = IndexType.upsert(**INDEX_TYPE_EQUITY_DEFINITION.as_payload())
    settlement_asset = Asset.upsert(
        unique_identifier=EXAMPLE_SETTLEMENT_CURRENCY["code"],
        asset_type=ASSET_TYPE_CURRENCY,
    )
    future = register_index_future_from_figis(
        EXAMPLE_FUTURE_FIGI,
        underlying_index_figi=EXAMPLE_UNDERLYING_INDEX_FIGI,
        underlying_index_type=INDEX_TYPE_EQUITY,
        settlement_asset_uid=settlement_asset.uid,
        margin_asset_uid=settlement_asset.uid,
        kind="EXPIRING",
        quote_unit="INDEX_POINT",
        settlement_model="LINEAR",
        settlement_method="CASH",
        contract_size=Decimal("50"),
        contract_unit="INDEX_POINT",
        expires_at=EXAMPLE_FUTURE_EXPIRES_AT,
        settles_at=EXAMPLE_FUTURE_SETTLES_AT,
        metadata={
            "source": "examples/msm/assets/derivatives/index_future_from_openfigi.py",
        },
    )

    return {
        "currency_asset_type": currency_asset_type,
        "equity_index_type": equity_index_type,
        "settlement_asset": settlement_asset,
        "underlying_index": Index.get_by_uid(future.underlying_index_uid),
        "future": future,
        "future_asset": Asset.get_by_uid(future.asset_uid),
    }


def main() -> None:
    print(create_index_future_from_openfigi())


if __name__ == "__main__":
    main()
