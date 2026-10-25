from __future__ import annotations

import uuid
import warnings
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, TypeVar

from pydantic import BaseModel, ConfigDict

from msm.base import MarketsBase

RowT = TypeVar("RowT", bound="MarketsMetaTableRow")
Payload = BaseModel | Mapping[str, Any] | None


class MarketsMetaTableRow(BaseModel):
    """Base class for user-facing Pydantic rows backed by markets MetaTables."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[MarketsBase]]
    __required_tables__: ClassVar[Sequence[type[MarketsBase]]]
    __upsert_keys__: ClassVar[Sequence[str]] = ()

    uid: uuid.UUID

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs: Any) -> None:
        """Let the subclass's public class methods run on the remote backend (ADR 0047)."""

        super().__pydantic_init_subclass__(**kwargs)
        from msm.api.remote import install_remote_dispatch

        install_remote_dispatch(cls)

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
            values=_payload_values(payload, kwargs),
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

        from msm.repositories.crud import update_model

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
    def filter(
        cls: type[RowT],
        *,
        limit: int = 500,
        offset: int = 0,
        order_by: str | Sequence[str] | None = None,
        **filters: Any,
    ) -> list[RowT]:
        """Filter rows through the active markets runtime.

        Keyword arguments ending in `_contains` compile to SQL `contains`
        filters, arguments ending in `__in` to `IN` filters, arguments ending
        in `__gte`, `__gt`, `__lte` or `__lt` to range filters, and the others
        to equality filters. `order_by` names columns, `-column` for descending.
        """

        from msm.repositories.crud import search_model

        exact_filters, in_filters, contains_filters, range_filters = cls._split_filters(filters)
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters=exact_filters,
            in_filters=in_filters,
            contains_filters=contains_filters,
            range_filters=range_filters,
            limit=limit,
            offset=offset,
            order_by=_order_by(cls, order_by),
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def count(cls, **filters: Any) -> int:
        """Count rows matching the same filters as :meth:`filter`."""

        from msm.repositories.crud import count_model

        exact_filters, in_filters, contains_filters, range_filters = cls._split_filters(filters)
        result = count_model(
            cls._active_context(),
            model=cls.__table__,
            filters=exact_filters,
            in_filters=in_filters,
            contains_filters=contains_filters,
            range_filters=range_filters,
        )
        rows = operation_result_rows(result)
        if not rows:
            return 0
        row = rows[0]
        for key in ("count", "count_1"):
            if key in row:
                return int(row[key] or 0)
        return int(next(iter(row.values()), 0) or 0)

    @classmethod
    def upsert_many(
        cls: type[RowT],
        payloads: Sequence[BaseModel | Mapping[str, Any]],
    ) -> list[RowT]:
        """Upsert many rows on ``__upsert_keys__`` in one statement.

        Each payload is validated through the row module's ``<Row>Upsert`` model
        when it defines one, as :meth:`upsert` does.
        """

        from msm.repositories.crud import bulk_upsert_model

        if not cls.__upsert_keys__:
            raise NotImplementedError(f"{cls.__name__} does not define upsert keys.")
        if not payloads:
            return []
        values = [_upsert_values(cls, payload) for payload in payloads]
        result = bulk_upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=values,
            conflict_columns=cls.__upsert_keys__,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def _split_filters(
        cls, filters: Mapping[str, Any]
    ) -> tuple[dict[str, Any], dict[str, list[Any]], dict[str, str], dict[str, dict[str, Any]]]:
        exact_filters: dict[str, Any] = {}
        in_filters: dict[str, list[Any]] = {}
        contains_filters: dict[str, str] = {}
        range_filters: dict[str, dict[str, Any]] = {}
        for key, value in filters.items():
            if value in (None, ""):
                continue
            if key.endswith("_contains"):
                field_name = key.removesuffix("_contains")
                cls._require_column(field_name)
                contains_filters[field_name] = str(value)
                continue
            if key.endswith("__in"):
                field_name = key.removesuffix("__in")
                cls._require_column(field_name)
                in_filters[field_name] = list(value)
                continue
            field_name, lookup = range_lookup(key)
            if lookup is not None:
                cls._require_column(field_name)
                range_filters.setdefault(field_name, {})[lookup] = value
                continue
            cls._require_column(key)
            exact_filters[key] = value
        return exact_filters, in_filters, contains_filters, range_filters

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


RANGE_LOOKUP_SUFFIXES = ("__gte", "__gt", "__lte", "__lt")


def range_lookup(key: str) -> tuple[str, str | None]:
    """Split a filter key such as ``local_date__gte`` into ``("local_date", "gte")``.

    Keys without a range suffix return ``(key, None)``.
    """

    for suffix in RANGE_LOOKUP_SUFFIXES:
        if key.endswith(suffix):
            return key.removesuffix(suffix), suffix.removeprefix("__")
    return key, None


def _order_by(row: type[Any], order_by: str | Sequence[str] | None) -> list[str]:
    if order_by in (None, ""):
        return []
    names = [order_by] if isinstance(order_by, str) else list(order_by)
    for name in names:
        row._require_column(str(name).removeprefix("-"))
    return [str(name) for name in names]


def _upsert_values(row: type[Any], payload: BaseModel | Mapping[str, Any]) -> dict[str, Any]:
    import sys

    module = sys.modules.get(row.__module__)
    payload_model = getattr(module, f"{row.__name__}Upsert", None) if module is not None else None
    if isinstance(payload_model, type) and issubclass(payload_model, BaseModel):
        if not isinstance(payload, payload_model):
            data = payload.model_dump(exclude_unset=True) if isinstance(payload, BaseModel) else payload
            payload = payload_model.model_validate(data)
        return _payload_values(payload, {})
    return _payload_values(payload, {})


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


def _install_base_dispatch() -> None:
    from msm.api.remote import install_remote_dispatch

    install_remote_dispatch(MarketsMetaTableRow, register=False)


_install_base_dispatch()

MarketsRow = MarketsMetaTableRow


__all__ = [
    "MarketsMetaTableRow",
    "MarketsRow",
    "operation_result_rows",
]
