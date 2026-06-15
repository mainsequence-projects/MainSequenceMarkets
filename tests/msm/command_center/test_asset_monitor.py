from __future__ import annotations

from command_center.widgets.asset_monitor import build_asset_monitor_frame
from command_center.workspaces.asset_monitor import build_asset_monitor_workspace_document


def test_build_asset_monitor_frame_uses_ticker_without_symbol_alias() -> None:
    frame = build_asset_monitor_frame(
        [
            {
                "uid": "asset-1",
                "unique_identifier": "MXN-GOVT-BILL-28D",
                "asset_type": "fixed_income",
                "details": [
                    {
                        "ticker": "CETE 28D",
                        "figi": "BBG000000001",
                        "security_type": "Bill",
                        "security_market_sector": "Govt",
                    }
                ],
            }
        ]
    )

    assert frame.status == "ready"
    assert "unique_identifier" in frame.columns
    assert "Symbol" not in frame.columns
    assert frame.rows == [
        {
            "uid": "asset-1",
            "unique_identifier": "MXN-GOVT-BILL-28D",
            "asset_type": "fixed_income",
            "ticker": "CETE 28D",
            "name": None,
            "figi": "BBG000000001",
            "composite_figi": None,
            "exchange_code": None,
            "security_type": "Bill",
            "security_market_sector": "Govt",
            "currency": None,
        }
    ]
    assert frame.meta is not None
    assert frame.meta.model_dump()["marketAsset"]["assetKeyField"] == "unique_identifier"


def test_build_asset_monitor_frame_does_not_create_symbol_alias() -> None:
    frame = build_asset_monitor_frame(
        [
            {
                "uid": "asset-2",
                "unique_identifier": "MXN-BONO-2031",
                "asset_type": "fixed_income",
            }
        ]
    )

    assert frame.rows[0]["unique_identifier"] == "MXN-BONO-2031"
    assert "Symbol" not in frame.rows[0]


def test_build_asset_monitor_workspace_document_binds_dataset_to_seed_data() -> None:
    workspace = build_asset_monitor_workspace_document(connection_id="connection-1")

    source, monitor = workspace["widgets"]
    assert source["widgetId"] == "connection-query"
    assert source["props"]["queryModelId"] == "api-operation"
    assert source["props"]["query"]["operationId"] == "getAssetMonitorFrame"
    assert monitor["widgetId"] == "main-sequence-markets__asset-screener"
    assert monitor["bindings"]["seedData"] == {
        "sourceWidgetId": "asset-monitor-source",
        "sourceOutputId": "dataset",
    }
