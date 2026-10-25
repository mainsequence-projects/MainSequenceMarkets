from __future__ import annotations

import uuid
import warnings
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from msm.base import MarketsBase

RowT = TypeVar("RowT", bound="MarketsMetaTableRow")
Payload = BaseModel | Mapping[str, Any] | None


def reconcile_renamed_columns(table: type[MarketsBase] | None, data: Any) -> Any:
    """Give row data both names of each renamed UID column (ADR 0048).

    Rows read from a table hold the current and the pre-3.0 column; the value is
    taken from the column ``READ_PRE_3_0_COLUMNS`` selects. Rows built from one
    name get the same value under the other.
    """

    renamed = getattr(table, "__renamed_columns__", None)
    if not renamed or not isinstance(data, Mapping):
        return data
    from msm.repositories.crud import renamed_column_value

    reconciled = dict(data)
    for current, previous in renamed.items():
        if current in reconciled or previous in reconciled:
            value = renamed_column_value(table, reconciled, current)
            reconciled[current] = reconciled[previous] = value
    return reconciled


def pre_3_0_field(current: str) -> Any:
    """Declare the deprecated pre-3.0 name of renamed UID field ``current``."""

    return Field(
        default=None,
        deprecated=f"Use {current}; the pre-3.0 name is removed in ms-markets 4.0 (ADR 0048).",
    )


def accept_renamed_fields(model: type[BaseModel], data: Any) -> Any:
    """Move pre-3.0 input names to their current names, with a warning (ADR 0048)."""

    renamed = getattr(model, "__renamed_fields__", None)
    if not renamed or not isinstance(data, Mapping):
        return data
    from msm._deprecated_imports import warn_renamed
    from msm.repositories.crud import _same_value

    accepted = dict(data)
    for current, previous in renamed.items():
        if previous not in accepted:
            continue
        warn_renamed(f"{model.__name__}.{previous}", f"{model.__name__}.{current}")
        value = accepted.pop(previous)
        if current in accepted and not _same_value(accepted[current], value):
            raise ValueError(
                f"{model.__name__} received different values for {current} and its "
                f"pre-3.0 name {previous}."
            )
        accepted.setdefault(current, value)
    return accepted


class PayloadWithRenamedFields(BaseModel):
    """Payload that accepts the pre-3.0 name of each renamed UID field (ADR 0048).

    ``__renamed_fields__`` maps each current field to its pre-3.0 name; ms-markets
    4.0 stops accepting the pre-3.0 names.
    """

    __renamed_fields__: ClassVar[Mapping[str, str]] = {}

    @model_validator(mode="before")
    @classmethod
    def _accept_pre_3_0_field_names(cls, data: Any) -> Any:
        return accept_renamed_fields(cls, data)


class MarketsMetaTableRow(BaseModel):
    """Base class for user-facing Pydantic rows backed by markets MetaTables."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[MarketsBase]]
    __required_tables__: ClassVar[Sequence[type[MarketsBase]]]
    __upsert_keys__: ClassVar[Sequence[str]] = ()

    uid: uuid.UUID

    @model_validator(mode="before")
    @classmethod
    def _reconcile_renamed_columns(cls, data: Any) -> Any:
        return reconcile_renamed_columns(getattr(cls, "__table__", None), data)

    @classmethod
    def start_engine(cls, **kwargs: Any):
        """Attach the runtime tables required by this row API."""

        from msm.bootstrap import start_engine

        requested_models = kwargs.pop("models", None)
        models = _dedupe_models([*cls.__required_tables__, *(requested_models or [])])
        return start_engine(models=models, **kwargs)

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        """Deprecated compatibility alias for :meth:`start_engine`."""

        _warn_deprecated_create_schemas(cls.__name__)
        return cls.start_engine(**kwargs)

    @classmethod
    def create(cls: type[RowT], payload: Payload = None, **kwargs: Any) -> RowT:
        """Insert one row through the active markets runtime."""

        from msm.repositories.crud import create_model

        result = create_model(
            cls._active_context(),
            model=cls.__table__,
            values=_row_values(cls, payload, kwargs),
        )
        return cls._from_operation_result(result)

    @classmethod
    def upsert(cls: type[RowT], payload: Payload = None, **kwargs: Any) -> RowT:
        """Upsert one row through the active markets runtime."""

        from msm.repositories.crud import upsert_model

        if not cls.__upsert_keys__:
            raise NotImplementedError(f"{cls.__name__} does not define upsert keys.")
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=_row_values(cls, payload, kwargs),
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

        from msm.repositories.crud import update_model

        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=_row_values(cls, payload, kwargs),
        )
        return cls._from_operation_result(result)

    @classmethod
    def delete(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        """Delete one row by UID through the active markets runtime."""

        from msm.repositories.crud import delete_model

        return delete_model(cls._active_context(), model=cls.__table__, uid=uid)

    @classmethod
    def get_by_uid(cls: type[RowT], uid: uuid.UUID | str) -> RowT | None:
        """Return one row by UID from the active markets runtime."""

        from msm.repositories.crud import get_model_by_uid

        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_unique_identifier(cls: type[RowT], unique_identifier: str) -> RowT | None:
        """Return one row by `unique_identifier` when the table has that column."""

        from msm.repositories.crud import get_model_by_unique_identifier

        cls._require_column("unique_identifier")
        result = get_model_by_unique_identifier(
            cls._active_context(),
            model=cls.__table__,
            unique_identifier=unique_identifier,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_many_by_unique_identifier(
        cls: type[RowT],
        unique_identifiers: Sequence[str],
    ) -> dict[str, RowT]:
        """Return rows keyed by `unique_identifier` for the requested identifiers."""

        from msm.repositories.crud import search_model

        cls._require_column("unique_identifier")
        identifiers = _unique_non_empty_strings(unique_identifiers)
        if not identifiers:
            return {}

        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            in_filters={"unique_identifier": identifiers},
            limit=len(identifiers),
        )
        rows = [cls.model_validate(row) for row in operation_result_rows(result)]
        return {str(getattr(row, "unique_identifier")): row for row in rows}

    @classmethod
    def filter(cls: type[RowT], *, limit: int = 500, **filters: Any) -> list[RowT]:
        """Filter rows through the active markets runtime.

        Keyword arguments ending in `_contains` compile to SQL `contains`
        filters. Other keyword arguments compile to equality filters.
        """

        from msm.repositories.crud import search_model

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


def _row_values(
    row: type[BaseModel], payload: Payload, kwargs: Mapping[str, Any]
) -> dict[str, Any]:
    values = _payload_values(payload, kwargs)
    table = getattr(row, "__table__", None)
    for current, previous in getattr(table, "__renamed_columns__", {}).items():
        if previous in values and current not in values:
            from msm._deprecated_imports import warn_renamed

            warn_renamed(f"{row.__name__}.{previous}", f"{row.__name__}.{current}")
    return values


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


def _unique_non_empty_strings(values: Sequence[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in (None, ""):
            continue
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


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


def _warn_deprecated_create_schemas(row_model_name: str) -> None:
    warnings.warn(
        f"{row_model_name}.create_schemas(...) is deprecated; use "
        f"{row_model_name}.start_engine(...) or msm.start_engine(models=[...]) instead.",
        DeprecationWarning,
        stacklevel=3,
    )


MarketsRow = MarketsMetaTableRow


__all__ = [
    "MarketsMetaTableRow",
    "MarketsRow",
    "operation_result_rows",
]
