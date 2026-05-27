from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_AUTO_REGISTER_ENV,
    EXAMPLE_METATABLE_NAMESPACE,
)

os.environ.setdefault(EXAMPLE_AUTO_REGISTER_ENV, EXAMPLE_METATABLE_NAMESPACE)

from msm.services.assets.openfigi import (  # noqa: E402
    build_asset_snapshot_frame_from_openfigi_result,
    query_by_figi,
)


SAMPLE_OPENFIGI_FIGI = "BBG000B9XRY4"


def main() -> None:
    from msm.api.assets import Asset, OpenFigiDetails

    normalized = query_by_figi(SAMPLE_OPENFIGI_FIGI)
    asset = Asset.upsert(
        unique_identifier=normalized["unique_identifier"],
        asset_type="equity",
    )
    open_figi_details = OpenFigiDetails.upsert(
        asset_uid=asset.uid,
        figi=normalized.get("figi"),
        composite=normalized.get("composite"),
        share_class=normalized.get("share_class"),
        isin=normalized.get("isin"),
        ticker=normalized.get("ticker"),
        name=normalized.get("name"),
        exchange_code=normalized.get("exchange_code"),
        security_type=normalized.get("security_type"),
        security_type_2=normalized.get("security_type_2"),
        security_market_sector=normalized.get("security_market_sector"),
        security_description=normalized.get("security_description"),
        unique_id=normalized.get("unique_id"),
        unique_id_fut_opt=normalized.get("unique_id_fut_opt"),
        metadata_text=normalized.get("metadata"),
        raw_payload=normalized.get("raw_payload"),
    )
    snapshot_frame = build_asset_snapshot_frame_from_openfigi_result(
        normalized,
        time_index=dt.datetime.now(dt.UTC).replace(microsecond=0),
    )

    print(asset.unique_identifier)
    print(open_figi_details.figi)
    print(snapshot_frame.index.names)


if __name__ == "__main__":
    main()
