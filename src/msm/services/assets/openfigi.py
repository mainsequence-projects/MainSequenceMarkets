from __future__ import annotations

import datetime as dt
import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from importlib import resources
from typing import TYPE_CHECKING, Any
from uuid import UUID

import pandas as pd
import requests

if TYPE_CHECKING:
    from msm.models import AssetTable, OpenFigiAssetDetailsTable

OPENFIGI_MAPPING_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_SEARCH_URL = "https://api.openfigi.com/v3/search"
OPENFIGI_API_KEY_SECRET_NAME = "OPEN_FIGI_API_KEY"
OPENFIGI_SECRET_SETUP_URL = "https://www.main-sequence.app/app/main_sequence_workbench/secrets"
OPENFIGI_API_URL_ENV = "FIGI_API_URL"
OPENFIGI_INDEX_MARKET_SECTOR = "Index"
OPENFIGI_PROVIDER_NAME = "OpenFIGI"


class OpenFigiConfigurationError(RuntimeError):
    """Raised when OpenFIGI credentials are not configured for the workflow."""


@dataclass(frozen=True)
class OpenFigiAssetRows:
    """Client-owned rows derived from one OpenFIGI result."""

    asset: AssetTable
    open_figi_details: OpenFigiAssetDetailsTable
    snapshot_frame: pd.DataFrame


def normalize_openfigi_result(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one OpenFIGI response row to SDK snake_case fields."""

    return {
        "unique_identifier": item.get("figi"),
        "figi": item.get("figi"),
        "composite": item.get("compositeFIGI"),
        "share_class": item.get("shareClassFIGI"),
        "isin": item.get("isin"),
        "ticker": item.get("ticker"),
        "name": item.get("name"),
        "exchange_code": item.get("exchCode"),
        "security_type": item.get("securityType"),
        "security_type_2": item.get("securityType2"),
        "security_market_sector": item.get("marketSector"),
        "security_description": item.get("securityDescription"),
        "unique_id": item.get("uniqueID"),
        "unique_id_fut_opt": item.get("uniqueIDFutOpt"),
        "metadata": item.get("metadata"),
        "raw_payload": dict(item),
    }


def build_asset_rows_from_openfigi_result(
    item: dict[str, Any],
    *,
    asset_uid: UUID | str,
    time_index: dt.datetime | pd.Timestamp | str,
) -> OpenFigiAssetRows:
    """Build SQLAlchemy/MetaTable asset rows from one OpenFIGI result."""

    from msm.models import AssetTable, OpenFigiAssetDetailsTable

    normalized = normalize_openfigi_result(item)
    unique_identifier = normalized.get("unique_identifier")
    if not unique_identifier:
        raise ValueError("OpenFIGI result does not include `figi`.")
    resolved_asset_uid = UUID(str(asset_uid))
    asset = AssetTable(uid=resolved_asset_uid, unique_identifier=unique_identifier)
    open_figi_details = OpenFigiAssetDetailsTable(
        asset_uid=resolved_asset_uid,
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
        time_index=time_index,
    )
    return OpenFigiAssetRows(
        asset=asset,
        open_figi_details=open_figi_details,
        snapshot_frame=snapshot_frame,
    )


def build_asset_snapshot_frame_from_openfigi_result(
    item: dict[str, Any],
    *,
    time_index: dt.datetime | pd.Timestamp | str,
) -> pd.DataFrame:
    """Build one AssetSnapshot DataNode frame row from an OpenFIGI result."""

    from msm.data_nodes.assets import AssetSnapshot

    normalized = item if "unique_identifier" in item else normalize_openfigi_result(item)
    unique_identifier = normalized.get("unique_identifier")
    if not unique_identifier:
        raise ValueError("OpenFIGI result does not include `figi`.")

    return AssetSnapshot.build_frame(
        {
            "time_index": time_index,
            "asset_identifier": unique_identifier,
            "name": normalized.get("name") or "",
            "ticker": normalized.get("ticker") or "",
            "exchange_code": normalized.get("exchange_code") or "",
            "asset_ticker_group_id": normalized.get("share_class") or "",
        },
    )


def search_figi(
    query: str,
    *,
    market_sector: str = "All",
    exch_code: str | None = None,
    security_type: str | None = None,
    security_type_2: str | None = None,
    include_unlisted_equities: bool = False,
    api_key: str | None = None,
    api_url: str | None = None,
    safety_buffer: int = 2,
) -> list[dict[str, Any]]:
    """Search OpenFIGI and return normalized response rows."""

    headers = _openfigi_headers(api_key=api_key)
    payload: dict[str, Any] = {
        "query": query,
        "marketSecDes": market_sector,
        "includeUnlistedEquities": include_unlisted_equities,
    }
    if exch_code:
        payload["exchCode"] = exch_code
    if security_type:
        payload["securityType"] = security_type
    if security_type_2:
        payload["securityType2"] = security_type_2

    url = api_url or os.getenv(OPENFIGI_API_URL_ENV) or OPENFIGI_SEARCH_URL
    return _paged_openfigi_search(
        url=url,
        headers=headers,
        payload=payload,
        safety_buffer=safety_buffer,
    )


def query_figi(
    tickers: list[str],
    *,
    market_sector: str,
    exch_code: str | None = None,
    security_type: str | None = None,
    security_type_2: str | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
    safety_buffer: int = 2,
) -> list[dict[str, Any]]:
    """Map ticker values through OpenFIGI and return normalized rows."""

    payload_items: list[dict[str, Any]] = []
    for ticker in tickers:
        item = {
            "idType": "TICKER",
            "idValue": ticker,
            "marketSecDes": market_sector,
        }
        if exch_code:
            item["exchCode"] = exch_code
        if security_type:
            item["securityType"] = security_type
        if security_type_2:
            item["securityType2"] = security_type_2
        payload_items.append(item)

    return _openfigi_mapping_batches(
        payload_items,
        api_key=api_key,
        api_url=api_url,
        safety_buffer=safety_buffer,
    )


def query_by_figi(
    figi_code: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Resolve one FIGI through OpenFIGI."""

    rows = _openfigi_mapping_batches(
        [{"idType": "ID_BB_GLOBAL", "idValue": figi_code}],
        api_key=api_key,
        api_url=api_url,
    )
    if len(rows) != 1:
        raise ValueError(f"Expected one OpenFIGI row for FIGI {figi_code!r}, got {len(rows)}.")
    return rows[0]


def register_index_from_figi(
    figi_code: str,
    *,
    index_type: str,
    api_key: str | None = None,
    api_url: str | None = None,
):
    """Resolve an index FIGI and upsert it as `msm.api.indices.Index`."""

    normalized = query_by_figi(
        figi_code,
        api_key=api_key,
        api_url=api_url,
    )
    return upsert_index_from_openfigi_result(normalized, index_type=index_type)


def upsert_index_from_openfigi_result(item: Mapping[str, Any], *, index_type: str):
    """Upsert an index row from a normalized or raw OpenFIGI result."""

    from msm.api.indices import Index

    normalized = _ensure_normalized_openfigi_result(item)
    _require_openfigi_market_sector(
        normalized,
        expected_market_sector=OPENFIGI_INDEX_MARKET_SECTOR,
    )
    unique_identifier = normalized.get("unique_identifier")
    if not unique_identifier:
        raise ValueError("OpenFIGI index result does not include `figi`.")

    return Index.upsert(
        unique_identifier=str(unique_identifier),
        index_type=index_type,
        display_name=(
            normalized.get("name")
            or normalized.get("security_description")
            or str(unique_identifier)
        ),
        description=normalized.get("security_description"),
        provider=OPENFIGI_PROVIDER_NAME,
        metadata_json=_openfigi_reference_metadata(normalized),
    )


def register_index_future_from_figis(
    future_figi: str,
    *,
    underlying_index_figi: str,
    underlying_index_type: str,
    settlement_asset_uid: UUID | str,
    margin_asset_uid: UUID | str,
    kind: str,
    quote_unit: str,
    settlement_model: str,
    settlement_method: str,
    contract_size: Decimal | str | int | float,
    contract_unit: str,
    expires_at: dt.datetime | pd.Timestamp | str | None = None,
    settles_at: dt.datetime | pd.Timestamp | str | None = None,
    metadata: Mapping[str, Any] | None = None,
    api_key: str | None = None,
    api_url: str | None = None,
):
    """Resolve an index FIGI and a future FIGI, then upsert the Future row.

    FIGI supplies canonical identifiers and provider metadata. Index
    classification and contract terms remain explicit inputs because OpenFIGI
    does not provide a stable enough schema for this library to infer index
    type, settlement, margin, size, or expiration rules.
    """

    from msm.api.derivatives import Future

    underlying_index = register_index_from_figi(
        underlying_index_figi,
        index_type=underlying_index_type,
        api_key=api_key,
        api_url=api_url,
    )
    normalized_future = query_by_figi(
        future_figi,
        api_key=api_key,
        api_url=api_url,
    )
    unique_identifier = normalized_future.get("unique_identifier")
    if not unique_identifier:
        raise ValueError("OpenFIGI future result does not include `figi`.")

    return Future.upsert(
        unique_identifier=str(unique_identifier),
        kind=kind,
        underlying_index_uid=underlying_index.uid,
        quote_unit=quote_unit,
        settlement_asset=settlement_asset_uid,
        margin_asset=margin_asset_uid,
        settlement_model=settlement_model,
        settlement_method=settlement_method,
        contract_size=contract_size,
        contract_unit=contract_unit,
        expires_at=expires_at,
        settles_at=settles_at,
        metadata=_future_openfigi_metadata(
            normalized_future=normalized_future,
            underlying_index_figi=underlying_index_figi,
            metadata=metadata,
        ),
    )


def query_by_isin(
    isin_code: str,
    exchange_code: str,
    *,
    api_key: str | None = None,
    api_url: str | None = None,
) -> dict[str, Any]:
    """Resolve one ISIN/exchange pair through OpenFIGI."""

    rows = _openfigi_mapping_batches(
        [
            {
                "idType": "ID_ISIN",
                "idValue": isin_code,
                "exchCode": exchange_code,
            }
        ],
        api_key=api_key,
        api_url=api_url,
    )
    if len(rows) != 1:
        raise ValueError(
            f"Expected one OpenFIGI row for ISIN {isin_code!r}/{exchange_code!r}, got {len(rows)}."
        )
    return rows[0]


def load_openfigi_lists() -> dict[str, list[Any]]:
    """Load packaged OpenFIGI definition lists."""

    base = resources.files(__package__) / "open_figi_lists"
    lists: dict[str, list[Any]] = {}
    for name in ("security_type", "security_type_2", "market_sector"):
        path = base / f"{name}.json"
        with path.open("r", encoding="utf-8") as handle:
            lists[name] = json.load(handle)
    return lists


def get_open_figi_definitions() -> dict[str, list[Any]]:
    return load_openfigi_lists()


def get_openfigi_api_key(
    *,
    secret_name: str = OPENFIGI_API_KEY_SECRET_NAME,
) -> str:
    """Read the OpenFIGI API key from Main Sequence Secrets."""

    try:
        secret = _get_mainsequence_secret(secret_name)
    except Exception as exc:
        if exc.__class__.__name__ == "DoesNotExist":
            message = _missing_openfigi_secret_message(secret_name)
            raise OpenFigiConfigurationError(message) from exc
        raise

    raw_value = getattr(secret, "value", None)
    if hasattr(raw_value, "get_secret_value"):
        raw_value = raw_value.get_secret_value()
    if raw_value is None or not str(raw_value).strip():
        raise OpenFigiConfigurationError(_missing_openfigi_secret_message(secret_name))
    return str(raw_value)


def _openfigi_headers(*, api_key: str | None = None) -> dict[str, str]:
    resolved_api_key = api_key or get_openfigi_api_key()
    return {
        "Content-Type": "application/json",
        "X-OPENFIGI-APIKEY": resolved_api_key,
    }


def _get_mainsequence_secret(secret_name: str) -> Any:
    from mainsequence.client import Secret

    return Secret.get(name=secret_name)


def _missing_openfigi_secret_message(secret_name: str) -> str:
    return f"{secret_name} needs to be set in {OPENFIGI_SECRET_SETUP_URL} before using OpenFIGI."


def _ensure_normalized_openfigi_result(item: Mapping[str, Any]) -> dict[str, Any]:
    if "security_market_sector" in item or "unique_identifier" in item:
        return dict(item)
    return normalize_openfigi_result(dict(item))


def _require_openfigi_market_sector(
    item: Mapping[str, Any],
    *,
    expected_market_sector: str,
) -> None:
    market_sector = item.get("security_market_sector")
    if str(market_sector).strip().casefold() != expected_market_sector.casefold():
        figi = item.get("figi") or item.get("unique_identifier")
        raise ValueError(
            f"OpenFIGI row {figi!r} must have marketSector "
            f"{expected_market_sector!r}, got {market_sector!r}."
        )


def _openfigi_reference_metadata(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "openfigi": {
            "figi": item.get("figi"),
            "composite": item.get("composite"),
            "share_class": item.get("share_class"),
            "ticker": item.get("ticker"),
            "name": item.get("name"),
            "exchange_code": item.get("exchange_code"),
            "security_type": item.get("security_type"),
            "security_type_2": item.get("security_type_2"),
            "security_market_sector": item.get("security_market_sector"),
            "security_description": item.get("security_description"),
            "unique_id": item.get("unique_id"),
            "unique_id_fut_opt": item.get("unique_id_fut_opt"),
            "metadata": item.get("metadata"),
            "raw_payload": item.get("raw_payload"),
        }
    }


def _future_openfigi_metadata(
    *,
    normalized_future: Mapping[str, Any],
    underlying_index_figi: str,
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(metadata or {})
    payload.setdefault("underlying_index_figi", underlying_index_figi)
    payload.setdefault("openfigi", _openfigi_reference_metadata(normalized_future)["openfigi"])
    return payload


def _openfigi_mapping_batches(
    payload_items: list[dict[str, Any]],
    *,
    api_key: str | None = None,
    api_url: str | None = None,
    safety_buffer: int = 2,
) -> list[dict[str, Any]]:
    headers = _openfigi_headers(api_key=api_key)
    url = api_url or os.getenv(OPENFIGI_API_URL_ENV) or OPENFIGI_MAPPING_URL
    min_interval = 6.0 / 25.0
    last_call = 0.0
    rows: list[dict[str, Any]] = []

    for start in range(0, len(payload_items), 100):
        batch = payload_items[start : start + 100]
        elapsed = time.time() - last_call
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        while True:
            response = requests.post(url, headers=headers, json=batch)
            now = time.time()
            if response.status_code == 429:
                time.sleep(_rate_limit_wait(response, default=min_interval) + 0.1)
                continue
            response.raise_for_status()
            last_call = now
            break

        for result in response.json():
            for item in result.get("data", []):
                rows.append(normalize_openfigi_result(item))

        remaining = response.headers.get("X-RateLimit-Remaining") or response.headers.get(
            "ratelimit-remaining"
        )
        if remaining is not None and int(remaining) <= safety_buffer:
            time.sleep(_rate_limit_wait(response, default=min_interval) + 0.1)

    return rows


def _paged_openfigi_search(
    *,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    safety_buffer: int,
) -> list[dict[str, Any]]:
    min_interval = 6.0 / 25.0
    last_call_time = 0.0
    rows: list[dict[str, Any]] = []

    while True:
        elapsed = time.time() - last_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

        response = requests.post(url, headers=headers, json=payload)
        now = time.time()
        if response.status_code == 429:
            time.sleep(_rate_limit_wait(response, default=min_interval) + 0.1)
            continue
        response.raise_for_status()
        last_call_time = now

        response_data = response.json()
        rows.extend(normalize_openfigi_result(item) for item in response_data.get("data", []))

        next_cursor = response_data.get("next")
        if not next_cursor:
            break
        payload["start"] = next_cursor

        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) <= safety_buffer:
            time.sleep(_rate_limit_wait(response, default=min_interval) + 0.1)

    return rows


def _rate_limit_wait(response: requests.Response, *, default: float) -> float:
    reset = response.headers.get("X-RateLimit-Reset") or response.headers.get("ratelimit-reset")
    return float(reset) if reset else default


__all__ = [
    "OPENFIGI_API_KEY_SECRET_NAME",
    "OPENFIGI_API_URL_ENV",
    "OPENFIGI_INDEX_MARKET_SECTOR",
    "OPENFIGI_MAPPING_URL",
    "OPENFIGI_PROVIDER_NAME",
    "OPENFIGI_SEARCH_URL",
    "OPENFIGI_SECRET_SETUP_URL",
    "OpenFigiConfigurationError",
    "OpenFigiAssetRows",
    "build_asset_rows_from_openfigi_result",
    "build_asset_snapshot_frame_from_openfigi_result",
    "get_open_figi_definitions",
    "get_openfigi_api_key",
    "load_openfigi_lists",
    "normalize_openfigi_result",
    "query_by_figi",
    "query_by_isin",
    "query_figi",
    "register_index_from_figi",
    "register_index_future_from_figis",
    "search_figi",
    "upsert_index_from_openfigi_result",
]
