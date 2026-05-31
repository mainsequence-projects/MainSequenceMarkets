from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict

from msm.base import MarketsBase
from msm.repositories.crud import (
    create_model,
    delete_model,
    get_model_by_uid,
    get_model_by_unique_identifier,
    search_model,
    update_model,
    upsert_model,
)

RowT = TypeVar("RowT", bound="MarketsRow")
Payload = BaseModel | Mapping[str, Any] | None


class MarketsRow(BaseModel):
    """Base class for user-facing Pydantic rows backed by markets MetaTables."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[MarketsBase]]
    __required_tables__: ClassVar[Sequence[type[MarketsBase]]]
    __upsert_keys__: ClassVar[Sequence[str]] = ()

    uid: uuid.UUID

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Create the MetaTable schemas required by this row API."""

        from msm.bootstrap import start_engine

        requested_models = kwargs.pop("models", None)
        models = _dedupe_models([*cls.__required_tables__, *(requested_models or [])])
        return start_engine(models=models, **kwargs)

    @classmethod
    def create(cls: type[RowT], payload: Payload = None, **kwargs: Any) -> RowT:
        """Insert one row through the active markets runtime."""

        result = create_model(
            cls._active_context(),
            model=cls.__table__,
            values=_payload_values(payload, kwargs),
        )
        return cls._from_operation_result(result)

    @classmethod
    def upsert(cls: type[RowT], payload: Payload = None, **kwargs: Any) -> RowT:
        """Upsert one row through the active markets runtime."""

        if not cls.__upsert_keys__:
            raise NotImplementedError(f"{cls.__name__} does not define upsert keys.")
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=_payload_values(payload, kwargs),
            conflict_columns=cls.__upsert_keys__,
        )
        return cls._from_operation_result(result)

    @classmethod
    def update(
        cls: type[RowT],
        uid: uuid.UUID | str,
        payload: Payload = None,
        **kwargs: Any,
    ) -> RowT:
        """Update one row by UID through the active markets runtime."""

        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=_payload_values(payload, kwargs),
        )
        return cls._from_operation_result(result)

    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        """Delete one row by UID through the active markets runtime."""

        return delete_model(cls._active_context(), model=cls.__table__, uid=uid)

    @classmethod
    def get_by_uid(cls: type[RowT], uid: uuid.UUID | str) -> RowT | None:
        """Return one row by UID from the active markets runtime."""

        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_unique_identifier(cls: type[RowT], unique_identifier: str) -> RowT | None:
        """Return one row by `unique_identifier` when the table has that column."""

        cls._require_column("unique_identifier")
        result = get_model_by_unique_identifier(
            cls._active_context(),
            model=cls.__table__,
            unique_identifier=unique_identifier,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def filter(cls: type[RowT], *, limit: int = 500, **filters: Any) -> list[RowT]:
        """Filter rows through the active markets runtime.

        Keyword arguments ending in `_contains` compile to SQL `contains`
        filters. Other keyword arguments compile to equality filters.
        """

        exact_filters: dict[str, Any] = {}
        contains_filters: dict[str, str] = {}
        for key, value in filters.items():
            if value in (None, ""):
                continue
            if key.endswith("_contains"):
                field_name = key.removesuffix("_contains")
                cls._require_column(field_name)
                contains_filters[field_name] = str(value)
                continue
            cls._require_column(key)
            exact_filters[key] = value

        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters=exact_filters,
            contains_filters=contains_filters,
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def _active_context(cls):
        from msm.bootstrap import resolve_runtime

        runtime = resolve_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context

    @classmethod
    def _from_operation_result(
        cls: type[RowT],
        result: Mapping[str, Any],
        *,
        required: bool = True,
    ) -> RowT | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(f"MetaTable operation result did not include a {cls.__name__} row.")
        return None

    @classmethod
    def _require_column(cls, field_name: str) -> None:
        if field_name not in cls.__table__.__table__.c:
            raise ValueError(f"{cls.__name__} cannot filter on unknown column {field_name!r}.")


def operation_result_rows(result: Mapping[str, Any] | list[Any] | None) -> list[dict[str, Any]]:
    """Normalize common MetaTable operation result envelopes to row dictionaries."""

    if result is None:
        return []
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if not isinstance(result, Mapping):
        return []

    for key in ("rows", "results"):
        rows = result.get(key)
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]

    for key in ("row", "data"):
        value = result.get(key)
        if isinstance(value, Mapping):
            nested_rows = operation_result_rows(value)
            if nested_rows:
                return nested_rows
            if key == "row":
                return [dict(value)]
            if "uid" in value:
                return [dict(value)]
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]

    if "uid" in result:
        return [dict(result)]
    return []


def _payload_values(payload: Payload, kwargs: Mapping[str, Any]) -> dict[str, Any]:
    if payload is None:
        return dict(kwargs)
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, BaseModel):
        return payload.model_dump(exclude_unset=True)
    if isinstance(payload, Mapping):
        return dict(payload)
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


def _dedupe_models(models: Sequence[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen: set[Any] = set()
    for model in models:
        key = model if isinstance(model, str) else getattr(model, "__name__", repr(model))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(model)
    return deduped


__all__ = [
    "MarketsRow",
    "operation_result_rows",
]
