from __future__ import annotations

from msm.services import build_asset_snapshot_node, update_asset_snapshot_frame


EXAMPLE_ASSET_SNAPSHOT_IDENTIFIER = "examples.mainsequence.markets.asset_snapshots"


def build_example_asset_snapshot():
    return build_asset_snapshot_node(
        [
            {
                "unique_identifier": "example-asset-btc",
                "name": "Bitcoin",
                "ticker": "BTC",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
                "venue_specific_properties": {"source": "example"},
            },
            {
                "unique_identifier": "example-asset-eth",
                "name": "Ethereum",
                "ticker": "ETH",
                "exchange_code": "CRYPTO",
                "asset_ticker_group_id": "crypto-majors",
                "venue_specific_properties": {"source": "example"},
            },
        ],
        identifier=EXAMPLE_ASSET_SNAPSHOT_IDENTIFIER,
        hash_namespace="examples",
    )


def main() -> None:
    node = build_example_asset_snapshot()
    frame = update_asset_snapshot_frame(
        [
            {
                "unique_identifier": "example-asset-btc",
                "ticker": "BTC",
                "venue_specific_properties": {"source": "example"},
            }
        ],
        identifier=EXAMPLE_ASSET_SNAPSHOT_IDENTIFIER,
        hash_namespace="examples",
    )
    print(node.config.node_metadata.identifier)
    print(frame)


if __name__ == "__main__":
    main()
