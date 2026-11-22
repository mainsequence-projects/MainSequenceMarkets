"""A write's input rows as one CTE, whatever their number (#112).

On PostgreSQL the rows are one JSONB parameter, read back as a typed recordset: a value
bound for each column of each row passed MetaTables' 1,000,000 characters of SQL at a few
thousand rows, and PostgreSQL's 65,535 parameters after it. On SQLite they are a
``VALUES`` list, bound without casts: SQLite casts ``DATETIME`` and ``JSON`` to numbers.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    SmallInteger,
    Uuid,
    bindparam,
    cast,
    column,
    func,
    select,
    values,
)
from sqlalchemy.dialects.postgresql import JSONB

InputColumns = Sequence[tuple[str, Any]]
"""``(name, kind)`` of each input column. A kind is ``String``, ``Float``, ``SmallInteger``,
``Uuid``, ``DateTime`` (with a time zone) or ``None`` for a JSON object."""


def input_rows(
    name: str,
    columns: InputColumns,
    rows: Sequence[Mapping[str, Any]],
    *,
    postgresql: bool,
) -> Any:
    """The ``rows`` as a CTE named ``name`` with ``columns``; a missing value is null.

    A JSON column's missing value is an empty object, and an empty uid is null.
    """

    json_type = JSONB if postgresql else JSON

    def type_of(kind: Any) -> Any:
        if kind is None:
            return json_type()
        if kind is Uuid:
            return Uuid(as_uuid=True)
        if kind is DateTime:
            return DateTime(timezone=True)
        return kind()

    def value(key: str, kind: Any, row: Mapping[str, Any]) -> Any:
        raw = row.get(key)
        if kind is None:
            return dict(raw or {})
        if raw is None:
            return None
        if kind is Uuid:
            if raw == "":
                return None
            raw = uuid.UUID(str(raw))
            return str(raw) if postgresql else raw
        if kind is Float:
            return float(raw)
        if kind is SmallInteger:
            return int(raw)
        if kind is DateTime:
            return raw.isoformat() if postgresql and isinstance(raw, dt.datetime) else raw
        return str(raw)

    typed = [column(key, type_of(kind)) for key, kind in columns]
    if postgresql:
        payload = [{key: value(key, kind, row) for key, kind in columns} for row in rows]
        parameter = cast(bindparam(f"{name}_rows", value=payload, type_=JSONB()), JSONB())
        recordset = (
            func.jsonb_to_recordset(parameter)
            .table_valued(*typed)
            .render_derived(name=f"{name}_recordset", with_types=True)
        )
        return select(*recordset.c).cte(name)

    return (
        values(*typed, name=name)
        .data(
            [
                tuple(
                    bindparam(
                        f"{name}_{key}_{index}", value=value(key, kind, row), type_=type_of(kind)
                    )
                    for key, kind in columns
                )
                for index, row in enumerate(rows)
            ]
        )
        .cte(name)
    )


__all__ = ["InputColumns", "input_rows"]
