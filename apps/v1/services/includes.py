"""Core-first `include` hydration of provider sidecars (ADR 0047, decision 4).

A sidecar is a provider-owned table keyed one-to-one by a core registry uid,
with a physical foreign key to the core table's stable ``uid`` column. A
provider that wants Markets to hydrate its sidecar on registry reads grants
the Markets workload ``data_viewer`` on that table. The by-uid lookups accept
``include=<sidecar MetaTable uid>``; Markets resolves the sidecar from the
MetaTables catalog, proves the foreign key, reads the sidecar rows for the
returned core uids in one statement per sidecar and attaches them under
``includes[<meta_table_uid>]``. Markets never writes a sidecar and never
decrypts a provider column; values come back as stored.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy import column, select, table

from msm.api.base import operation_result_rows
from msm.repositories.base import compile_markets_statement, execute_markets_operation

MAX_INCLUDES = 10
MetaTableLookup = Callable[[Sequence[str]], Sequence[Any]]
IncludedRows = dict[str, dict[str, dict[str, Any] | None]]
"""``{core uid: {sidecar meta_table_uid: sidecar row or None}}``."""


class SidecarReadError(RuntimeError):
    """A sidecar is a valid include but Markets could not read it, for example without a grant."""


@dataclass(frozen=True)
class SidecarInclude:
    """One sidecar table resolved from the catalog for one core registry."""

    meta_table_uid: str
    identifier: str
    namespace: str | None
    physical_table_name: str
    physical_schema: str | None
    join_column: str
    columns: tuple[str, ...]


def default_meta_table_lookup(uids: Sequence[str]) -> Sequence[Any]:
    """Return the visible catalog rows for ``uids`` through the MetaTables API."""

    from metatables import MetaTable

    values = [str(item) for item in uids if str(item)]
    if not values:
        return ()
    return MetaTable.filter_by_body(uid__in=values, limit=len(values), offset=0)


def normalize_includes(values: Iterable[str] | None) -> list[str]:
    """Parse ``include`` values: repeated parameters and comma-separated lists, at most ten."""

    parsed: list[str] = []
    for raw in values or ():
        for part in str(raw).split(","):
            text = part.strip()
            if text and text not in parsed:
                parsed.append(text)
    if len(parsed) > MAX_INCLUDES:
        raise ValueError(f"include accepts at most {MAX_INCLUDES} sidecar tables.")
    return parsed


def resolve_sidecar_includes(
    includes: Iterable[str] | None,
    *,
    core_model: type[Any],
    meta_table_lookup: MetaTableLookup | None = None,
) -> list[SidecarInclude]:
    """Resolve ``include`` uids to sidecars of ``core_model`` from the MetaTables catalog.

    Raises ``LookupError`` for a uid that is not a visible MetaTable and
    ``ValueError`` for a table without a single-column foreign key to the core
    table's ``uid``.
    """

    requested = normalize_includes(includes)
    if not requested:
        return []
    lookup = meta_table_lookup or default_meta_table_lookup
    visible = {str(getattr(item, "uid", "")): item for item in lookup(requested)}
    core_table_name = str(core_model.__table__.name)
    core_table_uid = _bound_uid(core_model)
    resolved: list[SidecarInclude] = []
    for meta_table_uid in requested:
        meta_table = visible.get(meta_table_uid)
        if meta_table is None:
            raise LookupError(f"include {meta_table_uid!r} is not a visible MetaTable")
        join_column = _sidecar_join_column(
            meta_table,
            core_table_name=core_table_name,
            core_table_uid=core_table_uid,
        )
        if join_column is None:
            raise ValueError(
                f"include {meta_table_uid!r} ({getattr(meta_table, 'identifier', '')}) has no "
                f"single-column foreign key to {core_table_name}.uid and is not a sidecar of it"
            )
        physical = str(getattr(meta_table, "physical_table_name", "") or "")
        if not physical:
            raise ValueError(f"include {meta_table_uid!r} has no physical table name")
        schema = getattr(meta_table, "physical_schema", None)
        resolved.append(
            SidecarInclude(
                meta_table_uid=meta_table_uid,
                identifier=str(getattr(meta_table, "identifier", "") or ""),
                namespace=getattr(meta_table, "namespace", None),
                physical_table_name=physical,
                physical_schema=None if schema in (None, "", "public") else str(schema),
                join_column=join_column,
                columns=_column_names(meta_table),
            )
        )
    return resolved


def read_sidecar_rows(
    context: Any,
    *,
    core_uids: Sequence[uuid.UUID | str],
    includes: Sequence[SidecarInclude],
) -> IncludedRows:
    """Read every included sidecar once for the given core uids.

    Raises ``SidecarReadError`` when a sidecar cannot be read; the Markets
    workload needs ``data_viewer`` on the provider's table.
    """

    uids = [str(item) for item in core_uids]
    hydrated: IncludedRows = {uid: {include.meta_table_uid: None for include in includes} for uid in uids}
    if not uids or not includes:
        return hydrated
    for include in includes:
        sidecar = table(
            include.physical_table_name,
            *(column(name) for name in include.columns),
            schema=include.physical_schema,
        )
        join = sidecar.c[include.join_column]
        statement = select(sidecar).where(join.in_([uuid.UUID(uid) for uid in uids]))
        try:
            rows = operation_result_rows(
                execute_markets_operation(
                    compile_markets_statement(statement, context=context, operation="select"),
                    context=context,
                )
            )
        except Exception as exc:
            raise SidecarReadError(
                f"sidecar {include.identifier or include.meta_table_uid!r} could not be read: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        for row in rows:
            key = _uid_key(row.get(include.join_column))
            if key in hydrated:
                hydrated[key][include.meta_table_uid] = {
                    name: _json_value(value) for name, value in row.items()
                }
    return hydrated


def with_includes(
    model_cls: type[BaseModel],
    items: Iterable[BaseModel | Mapping[str, Any]],
    hydrated: IncludedRows | None,
) -> list[BaseModel]:
    """Return ``items`` as ``model_cls`` rows carrying their ``includes`` mapping."""

    result: list[BaseModel] = []
    for item in items:
        payload = dict(item) if isinstance(item, Mapping) else item.model_dump()
        key = _uid_key(payload.get("uid"))
        payload["includes"] = dict((hydrated or {}).get(key, {}))
        result.append(model_cls.model_validate(payload))
    return result


def hydrate(
    context: Any,
    *,
    model_cls: type[BaseModel],
    core_model: type[Any],
    items: Sequence[BaseModel | Mapping[str, Any]],
    include: Iterable[str] | None,
    meta_table_lookup: MetaTableLookup | None = None,
) -> list[BaseModel]:
    """Resolve, read and attach the requested sidecars to ``items`` in one call."""

    includes = resolve_sidecar_includes(
        include, core_model=core_model, meta_table_lookup=meta_table_lookup
    )
    hydrated = None
    if includes:
        uids = [
            (dict(item) if isinstance(item, Mapping) else item.model_dump()).get("uid")
            for item in items
        ]
        hydrated = read_sidecar_rows(context, core_uids=[uid for uid in uids if uid], includes=includes)
    return with_includes(model_cls, items, hydrated)


def _sidecar_join_column(
    meta_table: Any,
    *,
    core_table_name: str,
    core_table_uid: str | None,
) -> str | None:
    for foreign_key in getattr(meta_table, "foreign_keys", None) or ():
        source = tuple(_get(foreign_key, "source_columns") or ())
        target = tuple(_get(foreign_key, "target_columns") or ())
        if len(source) != 1 or target != ("uid",):
            continue
        target_physical = str(_get(foreign_key, "target_table_physical_table_name") or "")
        target_uid = str(_get(foreign_key, "target_table_uid") or "")
        if target_physical == core_table_name or (core_table_uid and target_uid == core_table_uid):
            return str(source[0])
    return None


def _bound_uid(model: type[Any]) -> str | None:
    get_uid = getattr(model, "get_meta_table_uid", None)
    if not callable(get_uid):
        return None
    try:
        value = get_uid()
    except Exception:
        return None
    return str(value) if value not in (None, "") else None


def _column_names(meta_table: Any) -> tuple[str, ...]:
    names: list[str] = []
    for item in getattr(meta_table, "columns", None) or ():
        name = _get(item, "name")
        if name not in (None, ""):
            names.append(str(name))
    if not names:
        raise ValueError(
            f"include {getattr(meta_table, 'uid', '')!s} declares no columns in the catalog"
        )
    return tuple(names)


def _get(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def _uid_key(value: Any) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return str(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


__all__ = [
    "IncludedRows",
    "MAX_INCLUDES",
    "MetaTableLookup",
    "SidecarInclude",
    "SidecarReadError",
    "default_meta_table_lookup",
    "hydrate",
    "normalize_includes",
    "read_sidecar_rows",
    "resolve_sidecar_includes",
    "with_includes",
]
