from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from mainsequence.client.command_center.contracts.tabular import (
    CORE_TABULAR_FRAME_CONTRACT,
    TabularFrameFieldResponse,
    TabularFrameResponse,
    build_tabular_field,
    build_tabular_frame,
)

ASSET_MONITOR_WIDGET_ID = "main-sequence-markets__asset-screener"
ASSET_MONITOR_OPERATION_ID = "getAssetMonitorFrame"

ASSET_MONITOR_COLUMNS: tuple[str, ...] = (
    "uid",
    "unique_identifier",
    "asset_type",
    "ticker",
    "name",
    "figi",
    "composite_figi",
    "exchange_code",
    "security_type",
    "security_market_sector",
    "currency",
)


def asset_monitor_fields() -> list[TabularFrameFieldResponse]:
    """Return the canonical field descriptors for Asset Monitor frames."""

    return [
        build_tabular_field(
            key="uid",
            label="UID",
            field_type="string",
            nullable=False,
            description="Backend AssetTable row uid.",
        ),
        build_tabular_field(
            key="unique_identifier",
            label="Asset Identifier",
            field_type="string",
            nullable=False,
            description="Stable AssetTable unique_identifier used as the market asset key.",
        ),
        build_tabular_field(
            key="asset_type",
            label="Asset Type",
            field_type="string",
            nullable=True,
            description="Optional AssetTable asset_type.",
        ),
        build_tabular_field(
            key="ticker",
            label="Ticker",
            field_type="string",
            nullable=True,
            description="Ticker from asset detail or snapshot metadata when available.",
        ),
        build_tabular_field(
            key="name",
            label="Name",
            field_type="string",
            nullable=True,
            description="Human-readable asset name from detail or snapshot metadata.",
        ),
        build_tabular_field(
            key="figi",
            label="FIGI",
            field_type="string",
            nullable=True,
            description="OpenFIGI identifier when available.",
        ),
        build_tabular_field(
            key="composite_figi",
            label="Composite FIGI",
            field_type="string",
            nullable=True,
            description="OpenFIGI composite identifier when available.",
        ),
        build_tabular_field(
            key="exchange_code",
            label="Exchange",
            field_type="string",
            nullable=True,
            description="Exchange code from detail or snapshot metadata.",
        ),
        build_tabular_field(
            key="security_type",
            label="Security Type",
            field_type="string",
            nullable=True,
            description="OpenFIGI security type when available.",
        ),
        build_tabular_field(
            key="security_market_sector",
            label="Market Sector",
            field_type="string",
            nullable=True,
            description="OpenFIGI market sector when available.",
        ),
        build_tabular_field(
            key="currency",
            label="Currency",
            field_type="string",
            nullable=True,
            description="Currency from asset detail metadata when available.",
        ),
    ]


def asset_monitor_meta() -> dict[str, Any]:
    """Return frame metadata that identifies asset roles for consumers."""

    return {
        "contract": CORE_TABULAR_FRAME_CONTRACT,
        "widget": {
            "id": ASSET_MONITOR_WIDGET_ID,
            "input": "seedData",
        },
        "marketAsset": {
            "assetKeyField": "unique_identifier",
            "uidField": "uid",
            "tickerField": "ticker",
            "assetTypeField": "asset_type",
        },
    }


def build_asset_monitor_frame(
    assets: Iterable[Any],
    *,
    details_by_asset_uid: Mapping[str | uuid.UUID, Any] | None = None,
    snapshots_by_identifier: Mapping[str, Any] | None = None,
    source: Mapping[str, Any] | None = None,
    status: str = "ready",
) -> TabularFrameResponse:
    """Build an Asset Monitor frame from already-loaded asset rows."""

    rows = asset_monitor_rows(
        assets,
        details_by_asset_uid=details_by_asset_uid,
        snapshots_by_identifier=snapshots_by_identifier,
    )
    return build_tabular_frame(
        status=status,
        columns=ASSET_MONITOR_COLUMNS,
        rows=rows,
        fields=asset_monitor_fields(),
        meta=asset_monitor_meta(),
        source=source,
    )


def asset_monitor_rows(
    assets: Iterable[Any],
    *,
    details_by_asset_uid: Mapping[str | uuid.UUID, Any] | None = None,
    snapshots_by_identifier: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize asset rows and optional detail rows into monitor rows."""

    normalized: list[dict[str, Any]] = []
    detail_lookup = {
        str(asset_uid): details for asset_uid, details in (details_by_asset_uid or {}).items()
    }
    snapshot_lookup = dict(snapshots_by_identifier or {})

    for asset in assets:
        asset_payload = _record_payload(asset)
        uid = _string_or_none(_value(asset_payload, "uid"))
        unique_identifier = _string_or_none(
            _first_present(
                _value(asset_payload, "unique_identifier"),
                _value(asset_payload, "asset_identifier"),
            )
        )
        details = list(_detail_records(asset_payload))
        if uid is not None and uid in detail_lookup:
            details.extend(_as_list(detail_lookup[uid]))

        snapshot = _record_payload(
            _first_present(
                _value(asset_payload, "current_snapshot"),
                snapshot_lookup.get(unique_identifier or ""),
            )
        )

        ticker = _string_or_none(
            _first_present(
                _value(asset_payload, "ticker"),
                _value(snapshot, "ticker"),
                _first_detail_value(details, "ticker"),
            )
        )

        row = {
            "uid": uid,
            "unique_identifier": unique_identifier,
            "asset_type": _string_or_none(_value(asset_payload, "asset_type")),
            "ticker": ticker,
            "name": _string_or_none(
                _first_present(
                    _value(asset_payload, "name"),
                    _value(snapshot, "name"),
                    _first_detail_value(details, "name"),
                )
            ),
            "figi": _string_or_none(_first_detail_value(details, "figi")),
            "composite_figi": _string_or_none(
                _first_present(
                    _first_detail_value(details, "composite_figi"),
                    _first_detail_value(details, "compositeFIGI"),
                )
            ),
            "exchange_code": _string_or_none(
                _first_present(
                    _value(asset_payload, "exchange_code"),
                    _value(snapshot, "exchange_code"),
                    _first_detail_value(details, "exchange_code"),
                    _first_detail_value(details, "exchCode"),
                )
            ),
            "security_type": _string_or_none(
                _first_present(
                    _first_detail_value(details, "security_type"),
                    _first_detail_value(details, "securityType"),
                )
            ),
            "security_market_sector": _string_or_none(
                _first_present(
                    _first_detail_value(details, "security_market_sector"),
                    _first_detail_value(details, "marketSector"),
                )
            ),
            "currency": _string_or_none(_first_detail_value(details, "currency")),
        }
        normalized.append(row)

    return normalized


def _record_payload(record: Any) -> dict[str, Any]:
    if record is None:
        return {}
    if isinstance(record, Mapping):
        return dict(record)
    if hasattr(record, "model_dump"):
        return record.model_dump()
    return {
        key: getattr(record, key)
        for key in dir(record)
        if not key.startswith("_") and not callable(getattr(record, key))
    }


def _value(payload: Mapping[str, Any], key: str) -> Any:
    return payload.get(key)


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _detail_records(asset_payload: Mapping[str, Any]) -> Iterable[dict[str, Any]]:
    for detail in _as_list(asset_payload.get("details")):
        yield _record_payload(detail)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return list(value)
    return [value]


def _first_detail_value(details: Sequence[Mapping[str, Any]], key: str) -> Any:
    for detail in details:
        value = detail.get(key)
        if value is not None and value != "":
            return value
    return None


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    return str(value)
