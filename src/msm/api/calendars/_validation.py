from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def validate_payload(
    payload_model: type[BaseModel],
    payload: BaseModel | Mapping[str, Any] | None,
    kwargs: Mapping[str, Any],
) -> BaseModel:
    if payload is None:
        return payload_model(**dict(kwargs))
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, payload_model):
        return payload
    if isinstance(payload, BaseModel):
        return payload_model.model_validate(payload.model_dump(exclude_unset=True))
    if isinstance(payload, Mapping):
        return payload_model.model_validate(dict(payload))
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


def normalize_upper_token(value: str, *, field_name: str) -> str:
    normalized = "_".join(str(value).strip().upper().split())
    if not normalized:
        raise ValueError(f"{field_name} cannot be empty.")
    return normalized


def normalize_blankable_token(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip()


def ensure_utc_datetime(value: dt.datetime | str | None) -> dt.datetime | None:
    if value is None:
        return None
    timestamp = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware.")
    return timestamp.astimezone(dt.UTC)


__all__ = [
    "ensure_utc_datetime",
    "normalize_blankable_token",
    "normalize_upper_token",
    "validate_payload",
]
