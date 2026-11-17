"""Write a calendar from what an adapter read from its library (ADR 0055).

A write replaces the adapter's own rows and keeps every ``user`` row. It
changes exceptions by difference, so a row that did not change is not written,
and it reports what it added and removed.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from msm.api.base import operation_result_rows
from msm.base import new_markets_uid
from msm.models import CalendarTable
from msm.repositories import MarketsRepositoryContext
from msm.repositories.calendars import (
    read_calendar_exceptions,
    search_calendar_session_rules,
    search_calendars,
    write_calendar_definition,
)
from msm.repositories.crud import get_model_by_unique_identifier

from .computation import DEFAULT_SESSION_LABEL, format_local_time
from .pandas_market import (
    DEFAULT_VALID_FROM,
    PANDAS_MARKET_CALENDARS_SOURCE,
    CalendarSourceDefinition,
    build_pandas_market_calendar_definition,
)
from .validation import coerce_local_date

SOURCE_VERSION_KEY = "source_version"
"""Key of ``Calendar.metadata_json`` that records the library version that wrote it."""

DEFAULT_CALENDAR_TYPE = "TRADING"

_RESYNC_CALENDAR_LIMIT = 1000

_RULE_FIELDS = (
    "session_label",
    "effective_from",
    "effective_to",
    "weekdays",
    "opens_at_local",
    "closes_at_local",
    "open_day_offset",
    "close_day_offset",
    "is_primary",
)


@dataclass(frozen=True)
class CalendarSyncResult:
    """What one adapter write did, or would do when ``dry_run`` is set."""

    calendar: dict[str, Any]
    created: bool
    dry_run: bool
    changed: bool
    source_version: str
    previous_source_version: str | None = None
    previous_valid_from: dt.date | None = None
    previous_valid_to: dt.date | None = None
    rules_changed: bool = False
    exceptions_added: list[dict[str, Any]] = field(default_factory=list)
    exceptions_removed: list[dict[str, Any]] = field(default_factory=list)


def sync_pandas_market_calendar(
    context: MarketsRepositoryContext,
    *,
    source_identifier: str,
    unique_identifier: str | None = None,
    display_name: str | None = None,
    calendar_type: str | None = None,
    timezone: str | None = None,
    session_label: str | None = None,
    valid_from: dt.date | dt.datetime | str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    dry_run: bool = False,
) -> CalendarSyncResult:
    """Create a calendar from pandas_market_calendars, or write an existing one again.

    ``unique_identifier`` names the stored calendar and defaults to the
    library's name. Several stored calendars can come from one library
    calendar; each keeps its own ``user`` rows.
    """

    identifier = str(unique_identifier or source_identifier).strip()
    if not identifier:
        raise ValueError("unique_identifier must be a non-empty string.")
    existing = _existing_calendar(context, identifier)
    existing_rules = (
        operation_result_rows(search_calendar_session_rules(context, calendar_uid=existing["uid"]))
        if existing is not None
        else []
    )
    definition = build_pandas_market_calendar_definition(
        source_identifier=source_identifier,
        valid_from=_first_date(valid_from, existing),
        timezone=timezone or (str(existing["timezone"]) if existing is not None else None),
        session_label=session_label or _single_label(existing_rules) or DEFAULT_SESSION_LABEL,
    )
    return apply_calendar_source_definition(
        context,
        definition=definition,
        unique_identifier=identifier,
        display_name=display_name,
        calendar_type=calendar_type,
        metadata_json=metadata_json,
        dry_run=dry_run,
        existing=existing,
        existing_rules=existing_rules,
    )


def apply_calendar_source_definition(
    context: MarketsRepositoryContext,
    *,
    definition: CalendarSourceDefinition,
    unique_identifier: str,
    display_name: str | None = None,
    calendar_type: str | None = None,
    metadata_json: Mapping[str, Any] | None = None,
    dry_run: bool = False,
    existing: Mapping[str, Any] | None = None,
    existing_rules: list[dict[str, Any]] | None = None,
) -> CalendarSyncResult:
    """Write ``definition`` as the stored calendar ``unique_identifier``.

    The header, the rules and the exceptions change in one transaction. Rows of
    another ``source``, a user's among them, are not read and not written.
    """

    if existing is None:
        existing = _existing_calendar(context, unique_identifier)
    if existing is not None:
        _require_same_source(existing, definition, unique_identifier)
    if existing is not None and existing_rules is None:
        existing_rules = operation_result_rows(
            search_calendar_session_rules(context, calendar_uid=existing["uid"])
        )
    stored_exceptions = (
        read_calendar_exceptions(context, calendar_uid=existing["uid"], source=definition.source)
        if existing is not None
        else []
    )

    stored_by_key = {_exception_key(row): row for row in stored_exceptions}
    wanted_by_key = {_exception_key(row): row for row in definition.exceptions}
    removed = [
        row
        for key, row in stored_by_key.items()
        if key not in wanted_by_key or _exception_value(wanted_by_key[key]) != _exception_value(row)
    ]
    added = [
        row
        for key, row in wanted_by_key.items()
        if key not in stored_by_key or _exception_value(stored_by_key[key]) != _exception_value(row)
    ]
    rules_changed = sorted(_rule_value(rule) for rule in existing_rules or []) != sorted(
        _rule_value(rule) for rule in definition.rules
    )

    previous_metadata = dict((existing or {}).get("metadata_json") or {})
    header = {
        "unique_identifier": unique_identifier,
        "display_name": display_name or (existing or {}).get("display_name") or unique_identifier,
        "calendar_type": str(
            calendar_type or (existing or {}).get("calendar_type") or DEFAULT_CALENDAR_TYPE
        ),
        "timezone": definition.timezone,
        "source": definition.source,
        "source_identifier": definition.source_identifier,
        "valid_from": definition.valid_from,
        "valid_to": definition.valid_to,
        "metadata_json": {
            **previous_metadata,
            **dict(metadata_json or {}),
            SOURCE_VERSION_KEY: definition.source_version,
        },
    }
    header_changed = existing is None or any(
        _header_value(key, existing.get(key)) != _header_value(key, value)
        for key, value in header.items()
    )
    calendar_uid = existing["uid"] if existing is not None else new_markets_uid()
    changed = header_changed or rules_changed or bool(added) or bool(removed)
    if changed and not dry_run:
        write_calendar_definition(
            context,
            calendar_uid=calendar_uid,
            calendar_values=header,
            calendar_exists=existing is not None,
            rules=definition.rules if rules_changed else None,
            delete_exception_uids=[row["uid"] for row in removed],
            insert_exceptions=added,
        )
    return CalendarSyncResult(
        calendar={"uid": calendar_uid, **header},
        created=existing is None,
        dry_run=dry_run,
        changed=changed,
        source_version=definition.source_version,
        previous_source_version=previous_metadata.get(SOURCE_VERSION_KEY),
        previous_valid_from=_date_or_none((existing or {}).get("valid_from")),
        previous_valid_to=_date_or_none((existing or {}).get("valid_to")),
        rules_changed=rules_changed,
        exceptions_added=sorted(added, key=_exception_key),
        exceptions_removed=sorted(removed, key=_exception_key),
    )


def resync_adapter_calendars(
    context: MarketsRepositoryContext,
    *,
    unique_identifiers: Sequence[str] = (),
    valid_from: dt.date | dt.datetime | str | None = None,
    dry_run: bool = False,
) -> list[CalendarSyncResult]:
    """Write stored calendars again from the library version installed here.

    ``unique_identifiers`` names the calendars; none means every calendar the
    pandas_market_calendars adapter wrote. A named calendar that does not exist,
    or that the adapter did not write, is an error before anything is written.

    This is what ``jobs/resync_calendars.py`` runs. Nothing else calls it: a
    stored calendar takes a library's new answers only when a person asks.
    """

    if unique_identifiers:
        calendars = []
        for identifier in unique_identifiers:
            calendar = _existing_calendar(context, str(identifier).strip())
            if calendar is None:
                raise LookupError(f"Calendar {identifier!r} was not found.")
            if calendar.get("source") != PANDAS_MARKET_CALENDARS_SOURCE:
                raise ValueError(
                    f"Calendar {identifier!r} was not written from "
                    f"{PANDAS_MARKET_CALENDARS_SOURCE}; there is nothing to write again."
                )
            calendars.append(calendar)
    else:
        calendars = list_adapter_calendars(context)
    return [
        sync_pandas_market_calendar(
            context,
            source_identifier=str(calendar["source_identifier"]),
            unique_identifier=str(calendar["unique_identifier"]),
            valid_from=valid_from,
            dry_run=dry_run,
        )
        for calendar in calendars
    ]


def list_adapter_calendars(context: MarketsRepositoryContext) -> list[dict[str, Any]]:
    """Every stored calendar the pandas_market_calendars adapter wrote, by unique_identifier."""

    calendars = operation_result_rows(
        search_calendars(
            context,
            source=PANDAS_MARKET_CALENDARS_SOURCE,
            limit=_RESYNC_CALENDAR_LIMIT,
        )
    )
    return sorted(calendars, key=lambda row: str(row["unique_identifier"]))


def describe_calendar_sync(result: CalendarSyncResult, *, list_limit: int | None = 20) -> list[str]:
    """Lines that say what one calendar write did, for a job log.

    ``list_limit`` caps the exceptions listed on each side; None lists them all.
    """

    calendar = result.calendar
    name = f"{calendar['unique_identifier']} ({calendar['source']} {calendar['source_identifier']})"
    if not result.changed:
        return [f"{name}: unchanged, library {result.source_version}"]

    verb = "would be written" if result.dry_run else "written"
    lines = [f"{name}: {'created' if result.created else verb}"]
    lines.append(
        f"  library: {result.previous_source_version or 'not recorded'} -> {result.source_version}"
    )
    before = _range_text(result.previous_valid_from, result.previous_valid_to)
    after = _range_text(calendar["valid_from"], calendar["valid_to"])
    if not result.created and before != after:
        lines.append(f"  range: {before} -> {after}")
    else:
        lines.append(f"  range: {after}")
    lines.append(f"  session rules: {'changed' if result.rules_changed else 'unchanged'}")
    for sign, label, rows in (
        ("+", "added", result.exceptions_added),
        ("-", "removed", result.exceptions_removed),
    ):
        lines.append(f"  exceptions {label}: {len(rows)}")
        shown = rows if list_limit is None else rows[:list_limit]
        lines.extend(f"    {sign} {_exception_text(row)}" for row in shown)
        if len(rows) > len(shown):
            lines.append(f"    ... and {len(rows) - len(shown)} more")
    return lines


def _range_text(valid_from: dt.date | None, valid_to: dt.date | None) -> str:
    first = "the beginning" if valid_from is None else coerce_local_date(valid_from).isoformat()
    last = "no end" if valid_to is None else coerce_local_date(valid_to).isoformat()
    return f"{first} to {last}"


def _exception_text(row: Mapping[str, Any]) -> str:
    parts = [coerce_local_date(row["local_date"]).isoformat(), str(row["exception_type"])]
    if row.get("session_label"):
        parts.append(str(row["session_label"]))
    opens, closes = _exception_value(row)[:2]
    if opens:
        parts.append(f"opens {opens}")
    if closes:
        parts.append(f"closes {closes}")
    if row.get("name"):
        parts.append(f"({row['name']})")
    return " ".join(parts)


def _existing_calendar(
    context: MarketsRepositoryContext,
    unique_identifier: str,
) -> dict[str, Any] | None:
    rows = operation_result_rows(
        get_model_by_unique_identifier(
            context,
            model=CalendarTable,
            unique_identifier=unique_identifier,
        )
    )
    return rows[0] if rows else None


def _require_same_source(
    existing: Mapping[str, Any],
    definition: CalendarSourceDefinition,
    unique_identifier: str,
) -> None:
    stored = (existing.get("source"), existing.get("source_identifier"))
    if stored == (definition.source, definition.source_identifier):
        return
    written_from = (
        "by hand" if stored[0] in (None, "") else f"from {stored[0]} calendar {stored[1]!r}"
    )
    raise ValueError(
        f"Calendar {unique_identifier!r} was written {written_from}, not from "
        f"{definition.source} calendar {definition.source_identifier!r}. "
        "Writing it from another source would replace its rules; use another unique_identifier."
    )


def _first_date(
    valid_from: dt.date | dt.datetime | str | None,
    existing: Mapping[str, Any] | None,
) -> dt.date:
    """The first date to write: the caller's, else the earlier of the stored one and the default."""

    if valid_from not in (None, ""):
        return coerce_local_date(valid_from)
    stored = _date_or_none((existing or {}).get("valid_from"))
    return DEFAULT_VALID_FROM if stored is None else min(stored, DEFAULT_VALID_FROM)


def _single_label(rules: list[dict[str, Any]]) -> str | None:
    labels = {str(rule.get("session_label") or "") for rule in rules}
    return labels.pop() if len(labels) == 1 else None


def _exception_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        coerce_local_date(row["local_date"]).isoformat(),
        str(row.get("session_label") or ""),
        str(row["exception_type"]),
    )


def _exception_value(row: Mapping[str, Any]) -> tuple[str | None, str | None, str | None]:
    return (
        format_local_time(row.get("opens_at_local")),
        format_local_time(row.get("closes_at_local")),
        row.get("name") or None,
    )


def _rule_value(rule: Mapping[str, Any]) -> tuple[str, ...]:
    values = {
        "session_label": str(rule.get("session_label") or ""),
        "effective_from": coerce_local_date(rule["effective_from"]).isoformat(),
        "effective_to": ""
        if rule.get("effective_to") in (None, "")
        else coerce_local_date(rule["effective_to"]).isoformat(),
        "weekdays": str(rule["weekdays"]),
        "opens_at_local": format_local_time(rule.get("opens_at_local")) or "",
        "closes_at_local": format_local_time(rule.get("closes_at_local")) or "",
        "open_day_offset": str(int(rule.get("open_day_offset") or 0)),
        "close_day_offset": str(int(rule.get("close_day_offset") or 0)),
        "is_primary": str(bool(rule.get("is_primary", True))),
    }
    return tuple(values[key] for key in _RULE_FIELDS)


def _header_value(key: str, value: Any) -> Any:
    if key in ("valid_from", "valid_to"):
        parsed = _date_or_none(value)
        return None if parsed is None else parsed.isoformat()
    if key == "metadata_json":
        return dict(value or {})
    return None if value in (None, "") else str(value)


def _date_or_none(value: Any) -> dt.date | None:
    return None if value in (None, "") else coerce_local_date(value)


__all__ = [
    "DEFAULT_CALENDAR_TYPE",
    "PANDAS_MARKET_CALENDARS_SOURCE",
    "SOURCE_VERSION_KEY",
    "CalendarSyncResult",
    "apply_calendar_source_definition",
    "describe_calendar_sync",
    "list_adapter_calendars",
    "resync_adapter_calendars",
    "sync_pandas_market_calendar",
]
