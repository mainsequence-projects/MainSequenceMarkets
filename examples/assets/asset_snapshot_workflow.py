from __future__ import annotations

import datetime as dt

from msm.data_nodes.assets import AssetSnapshot


def build_example_asset_snapshot():
    snapshot_time = dt.datetime.now(dt.UTC).replace(microsecond=0)
    return AssetSnapshot().set_snapshots(
        [
            {
                "time_index": snapshot_time,
                "unique_identifier": "example-asset-btc",
                "name": "Bitcoin",
                "ticker": "BTC",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
            },
            {
                "time_index": snapshot_time,
                "unique_identifier": "example-asset-eth",
                "name": "Ethereum",
                "ticker": "ETH",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
            },
        ],
    )


def main() -> None:
    node = build_example_asset_snapshot()
    snapshot_time = dt.datetime.now(dt.UTC).replace(microsecond=0)
    frame = AssetSnapshot.build_frame(
        [
            {
                "time_index": snapshot_time,
                "unique_identifier": "example-asset-btc",
                "ticker": "BTC",
            }
        ],
        config=node.config,
    )
    print(node.config.node_metadata.identifier)
    print(frame)


if __name__ == "__main__":
    main()
