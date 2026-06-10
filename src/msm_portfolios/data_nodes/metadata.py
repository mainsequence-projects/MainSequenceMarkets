from __future__ import annotations

from typing import Any

from .constants import PORTFOLIO_DESCRIPTION, SIGNAL_DESCRIPTION


def emit_portfolio_metadata(
    *,
    unique_identifier: str,
    description: str | None,
    updater: Any | None,
) -> Any | None:
    if updater is None:
        return None
    payload = {
        "unique_identifier": unique_identifier,
        "description": description,
    }
    return _emit_metadata(payload=payload, updater=updater)


def emit_signal_metadata(
    *,
    signal_uid: str,
    signal_description: str | None,
    updater: Any | None,
) -> Any | None:
    if updater is None:
        from msm_portfolios.api.market_metadata import SignalMetadata

        return SignalMetadata.upsert(
            signal_uid=signal_uid,
            signal_description=signal_description,
        )
    payload = {
        "signal_uid": signal_uid,
        "signal_description": signal_description,
    }
    return _emit_metadata(payload=payload, updater=updater)


def extract_portfolio_description(value: Any | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        description = value.get(PORTFOLIO_DESCRIPTION) or value.get("portfolio_description")
        if description is not None:
            return str(description)
        front_end_details = value.get("front_end_details")
        if front_end_details is not None:
            return extract_portfolio_description(front_end_details)
        return extract_portfolio_description(
            value.get("portfolio_markets_configuration") or value.get("portfolio_markets_config")
        )

    for attr_name in (PORTFOLIO_DESCRIPTION, "portfolio_description"):
        description = getattr(value, attr_name, None)
        if description is not None:
            return str(description)

    front_end_details = getattr(value, "front_end_details", None)
    if front_end_details is not None:
        return extract_portfolio_description(front_end_details)

    return extract_portfolio_description(
        getattr(value, "portfolio_markets_configuration", None)
        or getattr(value, "portfolio_markets_config", None)
    )


def extract_signal_description(signal: Any | None) -> str | None:
    if signal is None:
        return None
    if isinstance(signal, dict):
        description = signal.get(SIGNAL_DESCRIPTION) or signal.get("description")
        return None if description is None else str(description)

    for attr_name in (SIGNAL_DESCRIPTION, "description"):
        description = getattr(signal, attr_name, None)
        if description is not None:
            return str(description)

    get_explanation = getattr(signal, "get_explanation", None)
    if callable(get_explanation):
        description = get_explanation()
        return None if description is None else str(description)
    return None


def _emit_metadata(*, payload: dict[str, Any], updater: Any) -> Any:
    if callable(updater):
        return updater(**payload)
    upsert = getattr(updater, "upsert", None)
    if callable(upsert):
        return upsert(payload)
    raise TypeError("metadata updater must be callable or expose upsert(...).")


__all__ = [
    "emit_portfolio_metadata",
    "emit_signal_metadata",
    "extract_portfolio_description",
    "extract_signal_description",
]
