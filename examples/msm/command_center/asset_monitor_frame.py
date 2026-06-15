from __future__ import annotations

from command_center.widgets.asset_monitor import build_asset_monitor_frame


def main() -> None:
    frame = build_asset_monitor_frame(
        [
            {
                "uid": "00000000-0000-0000-0000-000000000001",
                "unique_identifier": "MXN-BONO-2031",
                "asset_type": "fixed_income",
                "details": [
                    {
                        "ticker": "BONO",
                        "name": "Mexican Government Bond 2031",
                        "security_type": "Government",
                        "security_market_sector": "Govt",
                        "currency": "MXN",
                    }
                ],
            }
        ],
        source={
            "kind": "example",
            "id": "asset-monitor-frame-example",
            "label": "Asset Monitor frame example",
        },
    )
    print(frame.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
