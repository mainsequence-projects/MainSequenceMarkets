from __future__ import annotations

from uuid import UUID

from examples.platform.bootstrap import configure_examples_metatable_namespace

configure_examples_metatable_namespace()

from msm.data_nodes.assets import AssetSnapshot  # noqa: E402
from msm.models import Asset  # noqa: E402
from msm.services.assets.openfigi import (  # noqa: E402
    build_asset_rows_from_openfigi_result,
    normalize_openfigi_result,
)


SAMPLE_OPENFIGI_RESULT = {
    "figi": "BBG000B9XRY4",
    "compositeFIGI": "BBG000B9XRY4",
    "shareClassFIGI": "BBG001S5N8V8",
    "ticker": "AAPL",
    "name": "APPLE INC",
    "exchCode": "US",
    "securityType": "Common Stock",
    "securityType2": "Common Stock",
    "marketSector": "Equity",
    "securityDescription": "AAPL",
}


def main() -> None:
    normalized = normalize_openfigi_result(SAMPLE_OPENFIGI_RESULT)
    asset_rows = build_asset_rows_from_openfigi_result(
        SAMPLE_OPENFIGI_RESULT,
        asset_uid=UUID("00000000-0000-0000-0000-000000000001"),
    )

    assert isinstance(asset_rows.asset, Asset)
    assert asset_rows.asset.unique_identifier == normalized["unique_identifier"]
    assert asset_rows.snapshot_frame.index.names == AssetSnapshot.default_config().index_names

    print(asset_rows.asset.unique_identifier)
    print(asset_rows.open_figi_details.figi)
    print(asset_rows.snapshot_frame.index.names)


if __name__ == "__main__":
    main()
