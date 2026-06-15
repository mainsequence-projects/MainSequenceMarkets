from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from mainsequence.client.command_center.connections import CONNECTION_TYPE_ADAPTER_FROM_API
from mainsequence.client.command_center.widgets.bindings import bind_tabular_seed_data
from mainsequence.client.command_center.widgets.connection_query import make_connection_query_props

from command_center.widgets.asset_monitor import (
    ASSET_MONITOR_OPERATION_ID,
    ASSET_MONITOR_WIDGET_ID,
)

CONNECTION_QUERY_WIDGET_ID = "connection-query"


def build_asset_monitor_workspace_document(
    *,
    connection_id: str | int,
    connection_type_id: str = CONNECTION_TYPE_ADAPTER_FROM_API,
    operation_id: str = ASSET_MONITOR_OPERATION_ID,
    title: str = "Main Sequence Market Asset Monitor",
    description: str = "Main Sequence Markets asset monitor workspace.",
    source_widget_id: str = "asset-monitor-source",
    monitor_widget_id: str = "asset-monitor",
    search: str = "",
    limit: int = 500,
    offset: int = 0,
    asset_type: str | None = None,
    unique_identifiers: Sequence[str] | None = None,
    max_rows: int = 500,
) -> dict[str, Any]:
    """Build the standard Asset Monitor workspace document."""

    query: dict[str, Any] = {
        "search": search,
        "limit": limit,
        "offset": offset,
    }
    if asset_type is not None:
        query["asset_type"] = asset_type
    if unique_identifiers is not None:
        query["unique_identifiers"] = list(unique_identifiers)

    return {
        "title": title,
        "description": description,
        "labels": ["markets", "asset-monitor"],
        "category": "Markets",
        "source": "user",
        "schemaVersion": 1,
        "layoutKind": "custom",
        "grid": {"columns": 48, "rowHeight": 15, "gap": 8},
        "controls": {
            "enabled": True,
            "refresh": {
                "enabled": True,
                "defaultIntervalMs": 300000,
                "intervals": [None, 30000, 60000, 300000],
            },
        },
        "widgets": [
            {
                "id": source_widget_id,
                "widgetId": CONNECTION_QUERY_WIDGET_ID,
                "title": "Asset source",
                "props": make_connection_query_props(
                    connection_id=connection_id,
                    connection_type_id=connection_type_id,
                    operation_id=operation_id,
                    query=query,
                    max_rows=max_rows,
                ),
                "managedBy": {
                    "ownerInstanceId": monitor_widget_id,
                    "role": "embedded-connection-source",
                },
                "presentation": {
                    "placementMode": "sidebar",
                    "railVisibility": "hidden",
                },
            },
            {
                "id": monitor_widget_id,
                "widgetId": ASSET_MONITOR_WIDGET_ID,
                "title": "Asset Monitor",
                "props": {
                    "assetScreenerSourceMode": "bound",
                    "columnConfigMode": "source",
                    "density": "compact",
                    "maxRenderedRows": max_rows,
                    "showDiagnostics": True,
                },
                "bindings": {
                    "seedData": bind_tabular_seed_data(source_widget_id=source_widget_id),
                },
                "layout": {"cols": 48, "rows": 20},
                "position": {"x": 0, "y": 0},
            },
        ],
    }
