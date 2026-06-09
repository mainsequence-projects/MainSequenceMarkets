from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, func, insert, inspect, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from mainsequence.client.metatables import MetaTableCompiledSQLOperation

from msm.base import MarketsBase

from .base import (
    MarketsOperationContext,
    compile_markets_statement,
    execute_markets_operation,
)

_MISSING = object()


def build_create_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    returning: bool = True,
) -> MetaTableCompiledSQLOperation:
    """Build an insert operation for a markets MetaTable SQLAlchemy model."""

    statement = insert(model).values(
        _model_value_mapping(model, _model_insert_payload(model, values))
    )
    if returning:
        statement = statement.returning(model)
    return compile_markets_statement(
        statement,
        context=context,
        operation="insert",
        models=[model],
        access="write",
    )


def build_upsert_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    conflict_columns: Sequence[str],
) -> MetaTableCompiledSQLOperation:
    """Build a PostgreSQL upsert operation for a markets MetaTable model."""

    if not conflict_columns:
        raise ValueError("Upsert operations require at least one conflict column.")

    payload = dict(values)
    insert_payload = _model_insert_payload(model, payload)
    update_payload = _model_update_payload(model, payload)
    statement = postgresql_insert(model).values(_model_value_mapping(model, insert_payload))
    conflict_property_keys = {
        _model_column_property(model, conflict_column).key for conflict_column in conflict_columns
    }
    primary_key_property_keys = _model_primary_key_property_keys(model)
    update_values = {
        _model_attribute(model, key): value
        for key, value in update_payload.items()
        if _model_column_property(model, key).key
        not in {*conflict_property_keys, *primary_key_property_keys}
    }
    if not update_values:
        first_conflict_column = conflict_columns[0]
        first_conflict_property = _model_column_property(model, first_conflict_column)
        first_conflict_physical_name = first_conflict_property.columns[0].name
        update_values = {
            _model_attribute(model, first_conflict_column): statement.excluded[
                first_conflict_physical_name
            ]
        }
    statement = statement.on_conflict_do_update(
        index_elements=[
            _model_attribute(model, conflict_column) for conflict_column in conflict_columns
        ],
        set_=update_values,
    ).returning(model)
    return compile_markets_statement(
        statement,
        context=context,
        operation="upsert",
        models=[model],
        access="write",
    )


def build_bulk_upsert_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
) -> MetaTableCompiledSQLOperation:
    """Build one PostgreSQL upsert operation for multiple rows."""

    if not conflict_columns:
        raise ValueError("Bulk upsert operations require at least one conflict column.")
    if not values:
        raise ValueError("Bulk upsert operations require at least one values row.")

    insert_payloads = [_model_insert_payload(model, row) for row in values]
    statement = postgresql_insert(model).values(
        [_model_value_mapping(model, payload) for payload in insert_payloads]
    )
    conflict_property_keys = {
        _model_column_property(model, conflict_column).key for conflict_column in conflict_columns
    }
    primary_key_property_keys = _model_primary_key_property_keys(model)
    update_payload = _model_update_payload(model, values[0])
    update_values = {}
    for key, value in update_payload.items():
        column_property = _model_column_property(model, key)
        if column_property.key in {*conflict_property_keys, *primary_key_property_keys}:
            continue
        physical_name = column_property.columns[0].name
        if key in insert_payloads[0]:
            update_values[_model_attribute(model, key)] = statement.excluded[physical_name]
        else:
            update_values[_model_attribute(model, key)] = value

    if not update_values:
        first_conflict_column = conflict_columns[0]
        first_conflict_property = _model_column_property(model, first_conflict_column)
        first_conflict_physical_name = first_conflict_property.columns[0].name
        update_values = {
            _model_attribute(model, first_conflict_column): statement.excluded[
                first_conflict_physical_name
            ]
        }

    statement = statement.on_conflict_do_update(
        index_elements=[
            _model_attribute(model, conflict_column) for conflict_column in conflict_columns
        ],
        set_=update_values,
    ).returning(model)
    return compile_markets_statement(
        statement,
        context=context,
        operation="upsert",
        models=[model],
        access="write",
    )


def bulk_upsert_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Sequence[Mapping[str, Any]],
    conflict_columns: Sequence[str],
) -> dict[str, Any]:
    return execute_markets_operation(
        build_bulk_upsert_model_operation(
            context,
            model=model,
            values=values,
            conflict_columns=conflict_columns,
        ),
        context=context,
    )


def upsert_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    conflict_columns: Sequence[str],
) -> dict[str, Any]:
    return execute_markets_operation(
        build_upsert_model_operation(
            context,
            model=model,
            values=values,
            conflict_columns=conflict_columns,
        ),
        context=context,
    )


def create_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    values: Mapping[str, Any],
    returning: bool = True,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_model_operation(
            context,
            model=model,
            values=values,
            returning=returning,
        ),
        context=context,
    )


def build_get_model_by_uid_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = select(model).where(_model_identity_attribute(model) == uid).limit(1)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[model],
        access="read",
    )


def get_model_by_uid(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_model_by_uid_operation(context, model=model, uid=uid),
        context=context,
    )


def build_get_model_by_unique_identifier_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    unique_identifier: str,
) -> MetaTableCompiledSQLOperation:
    statement = (
        select(model)
        .where(_model_attribute(model, "unique_identifier") == unique_identifier)
        .limit(1)
    )
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[model],
        access="read",
    )


def get_model_by_unique_identifier(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    unique_identifier: str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_get_model_by_unique_identifier_operation(
            context,
            model=model,
            unique_identifier=unique_identifier,
        ),
        context=context,
    )


def build_search_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> MetaTableCompiledSQLOperation:
    statement = _filtered_model_select(
        model,
        filters=filters,
        in_filters=in_filters,
        contains_filters=contains_filters,
    )
    statement = statement.limit(limit)
    if offset:
        statement = statement.offset(offset)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[model],
        access="read",
    )


def search_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_model_operation(
            context,
            model=model,
            filters=filters,
            in_filters=in_filters,
            contains_filters=contains_filters,
            limit=limit,
            offset=offset,
        ),
        context=context,
    )


def build_count_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
) -> MetaTableCompiledSQLOperation:
    filtered = _filtered_model_select(
        model,
        filters=filters,
        in_filters=in_filters,
        contains_filters=contains_filters,
    ).subquery()
    statement = select(func.count().label("count")).select_from(filtered)
    return compile_markets_statement(
        statement,
        context=context,
        operation="select",
        models=[model],
        access="read",
    )


def count_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_count_model_operation(
            context,
            model=model,
            filters=filters,
            in_filters=in_filters,
            contains_filters=contains_filters,
        ),
        context=context,
    )


def build_update_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
    values: Mapping[str, Any],
    returning: bool = True,
) -> MetaTableCompiledSQLOperation:
    statement = (
        update(model)
        .where(_model_identity_attribute(model) == uid)
        .values(
            _model_value_mapping(
                model,
                values,
                include_none=False,
            )
        )
    )
    if returning:
        statement = statement.returning(model)
    return compile_markets_statement(
        statement,
        context=context,
        operation="update",
        models=[model],
        access="write",
    )


def update_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
    values: Mapping[str, Any],
    returning: bool = True,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_model_operation(
            context,
            model=model,
            uid=uid,
            values=values,
            returning=returning,
        ),
        context=context,
    )


def build_delete_model_operation(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    statement = delete(model).where(_model_identity_attribute(model) == uid)
    return compile_markets_statement(
        statement,
        context=context,
        operation="delete",
        models=[model],
        access="write",
    )


def delete_model(
    context: MarketsOperationContext,
    *,
    model: type[MarketsBase],
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_model_operation(context, model=model, uid=uid),
        context=context,
    )


def _model_value_mapping(
    model: type[MarketsBase],
    values: Mapping[str, Any],
    *,
    include_none: bool = True,
) -> dict[Any, Any]:
    return {
        _model_attribute(model, key): value
        for key, value in values.items()
        if include_none or value is not None
    }


def _filtered_model_select(
    model: type[MarketsBase],
    *,
    filters: Mapping[str, Any] | None = None,
    in_filters: Mapping[str, Sequence[Any]] | None = None,
    contains_filters: Mapping[str, str] | None = None,
):
    statement = select(model)

    for field_name, value in (filters or {}).items():
        if value is not None:
            statement = statement.where(_model_attribute(model, field_name) == value)

    for field_name, values in (in_filters or {}).items():
        if values:
            statement = statement.where(_model_attribute(model, field_name).in_(list(values)))

    for field_name, value in (contains_filters or {}).items():
        if value not in (None, ""):
            statement = statement.where(
                func.lower(_model_attribute(model, field_name)).contains(str(value).lower())
            )

    return statement


def _model_insert_payload(
    model: type[MarketsBase],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(values)
    for column_property in inspect(model).column_attrs:
        column = column_property.columns[0]
        if column_property.key in payload and payload[column_property.key] is not None:
            continue
        default_value = _column_default_value(column.default)
        if default_value is not _MISSING:
            payload[column_property.key] = default_value
    return payload


def _model_update_payload(
    model: type[MarketsBase],
    values: Mapping[str, Any],
) -> dict[str, Any]:
    payload = dict(values)
    for column_property in inspect(model).column_attrs:
        column = column_property.columns[0]
        if column_property.key in payload and payload[column_property.key] is not None:
            continue
        default_value = _column_default_value(column.onupdate)
        if default_value is not _MISSING:
            payload[column_property.key] = default_value
    return payload


def _column_default_value(default: Any) -> Any:
    if default is None or getattr(default, "is_clause_element", False):
        return _MISSING

    value = getattr(default, "arg", default)
    if callable(value):
        try:
            return value(None)
        except TypeError:
            return value()
    return value


def _model_primary_key_property_keys(model: type[MarketsBase]) -> set[str]:
    primary_key_columns = set(model.__table__.primary_key.columns)
    return {
        column_property.key
        for column_property in inspect(model).column_attrs
        if column_property.columns[0] in primary_key_columns
    }


def _model_identity_attribute(model: type[MarketsBase]) -> Any:
    if "uid" in model.__table__.c:
        return _model_attribute(model, "uid")

    primary_key_columns = list(model.__table__.primary_key.columns)
    if len(primary_key_columns) != 1:
        raise ValueError(
            f"{model.__name__} must define a `uid` column or exactly one primary key column."
        )
    primary_key_property = inspect(model).get_property_by_column(primary_key_columns[0])
    return _model_attribute(model, primary_key_property.key)


def _model_column_property(model: type[MarketsBase], field_name: str) -> Any:
    matches = []
    for column_property in inspect(model).column_attrs:
        names = {column_property.key}
        for column in column_property.columns:
            names.add(str(column.key))
            names.add(str(column.name))
        if field_name in names:
            matches.append(column_property)

    if not matches:
        raise ValueError(f"{model.__name__} has no SQLAlchemy column {field_name!r}.")
    if len(matches) > 1:
        raise ValueError(f"{model.__name__} column reference {field_name!r} is ambiguous.")
    return matches[0]


def _model_attribute(model: type[MarketsBase], field_name: str) -> Any:
    return getattr(model, _model_column_property(model, field_name).key)


__all__ = [
    "build_bulk_upsert_model_operation",
    "build_count_model_operation",
    "build_create_model_operation",
    "build_delete_model_operation",
    "build_get_model_by_uid_operation",
    "build_get_model_by_unique_identifier_operation",
    "build_search_model_operation",
    "build_upsert_model_operation",
    "build_update_model_operation",
    "bulk_upsert_model",
    "count_model",
    "create_model",
    "delete_model",
    "get_model_by_uid",
    "get_model_by_unique_identifier",
    "search_model",
    "upsert_model",
    "update_model",
]
