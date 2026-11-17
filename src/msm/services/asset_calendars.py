"""Link assets to their trading calendars in bulk (ADR 0057).

An asset's trading calendar is its ``AssetCalendar`` row (ADR 0056). These
services link many assets in one transaction, naming assets by
``unique_identifier`` and the calendar by uid or ``unique_identifier``.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from msm.api.base import operation_result_rows
from msm.models import CalendarTable
from msm.repositories import MarketsRepositoryContext
from msm.repositories.asset_calendars import (
    link_assets,
    read_asset_link_state,
    read_unlinked_assets,
)
from msm.repositories.crud import get_model_by_uid, search_model

_CALENDAR_READ_SIZE = 500


def resolve_calendar_uid(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: uuid.UUID | str | None = None,
    calendar_identifier: str | None = None,
) -> uuid.UUID:
    """The uid of one stored calendar, named by uid or by ``unique_identifier``.

    Exactly one of the two names is given. Raises ``LookupError`` when the
    calendar does not exist.
    """

    if (calendar_uid in (None, "")) == (calendar_identifier in (None, "")):
        raise ValueError("Name the calendar with calendar_uid or calendar_identifier, not both.")
    if calendar_uid not in (None, ""):
        rows = operation_result_rows(
            get_model_by_uid(context, model=CalendarTable, uid=str(calendar_uid))
        )
        if not rows:
            raise LookupError(f"Calendar {calendar_uid} was not found.")
        return uuid.UUID(str(rows[0]["uid"]))
    return resolve_calendar_identifiers(context, [str(calendar_identifier)])[
        str(calendar_identifier).strip()
    ]


def resolve_calendar_identifiers(
    context: MarketsRepositoryContext,
    calendar_identifiers: Iterable[str],
) -> dict[str, uuid.UUID]:
    """The uid of each named stored calendar, by ``unique_identifier``.

    Raises ``LookupError`` naming every calendar that does not exist, so a write
    that names an unknown calendar writes nothing.
    """

    names = list(dict.fromkeys(str(name).strip() for name in calendar_identifiers))
    if any(not name for name in names):
        raise ValueError("calendar_identifier cannot be empty.")
    found: dict[str, uuid.UUID] = {}
    for index in range(0, len(names), _CALENDAR_READ_SIZE):
        chunk = names[index : index + _CALENDAR_READ_SIZE]
        result = search_model(
            context,
            model=CalendarTable,
            in_filters={"unique_identifier": chunk},
            limit=len(chunk),
        )
        for row in operation_result_rows(result):
            found[str(row["unique_identifier"])] = uuid.UUID(str(row["uid"]))
    missing = [name for name in names if name not in found]
    if missing:
        listed = ", ".join(repr(name) for name in missing)
        raise LookupError(
            f"Calendar {listed} was not found."
            if len(missing) == 1
            else f"Calendars {listed} were not found."
        )
    return found


def link_assets_to_calendar(
    context: MarketsRepositoryContext,
    *,
    asset_identifiers: Sequence[str],
    calendar_uid: uuid.UUID | str | None = None,
    calendar_identifier: str | None = None,
    relink: bool = True,
) -> dict[str, Any]:
    """Link the named assets to one stored calendar, in one transaction.

    Returns the calendar's uid and what happened to each identifier:

    - ``linked``: the asset had no trading calendar and now has this one;
    - ``moved``: the asset was on another calendar and is now on this one;
    - ``unchanged``: the asset was already on this calendar;
    - ``kept``: the asset is on another calendar and ``relink`` is false;
    - ``unknown``: no asset has that identifier. Nothing is written for it.

    The links are read first and written after, so the lists describe the state
    the call found.
    """

    names = list(dict.fromkeys(str(identifier).strip() for identifier in asset_identifiers))
    if not names or any(not name for name in names):
        raise ValueError("asset_identifiers names at least one asset, and none is empty.")
    calendar = resolve_calendar_uid(
        context, calendar_uid=calendar_uid, calendar_identifier=calendar_identifier
    )
    state = read_asset_link_state(context, asset_identifiers=names)

    outcome: dict[str, list[str]] = defaultdict(list)
    for name in names:
        row = state.get(name)
        if row is None:
            outcome["unknown"].append(name)
        elif row.get("calendar_uid") in (None, ""):
            outcome["linked"].append(name)
        elif uuid.UUID(str(row["calendar_uid"])) == calendar:
            outcome["unchanged"].append(name)
        else:
            outcome["moved" if relink else "kept"].append(name)

    to_write = [*outcome["linked"], *outcome["moved"]]
    if to_write:
        link_assets(context, links={calendar: to_write}, relink=relink)
    return {
        "calendar_uid": calendar,
        **{key: outcome[key] for key in ("linked", "moved", "unchanged", "kept", "unknown")},
    }


def link_registered_assets(
    context: MarketsRepositoryContext,
    links: Iterable[tuple[str, Mapping[str, Any]]],
    *,
    relink: bool = True,
) -> None:
    """Link assets that a registration just wrote, each to the calendar its payload names.

    ``links`` yields ``(asset_identifier, payload)``. A payload names its
    calendar with ``calendar_uid`` or ``calendar_identifier``; one that names
    none is skipped. Every named calendar is resolved before anything is
    written, and all links go in one transaction.
    """

    by_uid: dict[uuid.UUID, list[str]] = defaultdict(list)
    by_identifier: dict[str, list[str]] = defaultdict(list)
    for asset_identifier, payload in links:
        calendar_uid = payload.get("calendar_uid")
        calendar_identifier = payload.get("calendar_identifier")
        if calendar_uid not in (None, ""):
            by_uid[uuid.UUID(str(calendar_uid))].append(asset_identifier)
        elif calendar_identifier not in (None, ""):
            by_identifier[str(calendar_identifier).strip()].append(asset_identifier)
    if not by_uid and not by_identifier:
        return

    resolved = resolve_calendar_identifiers(context, by_identifier) if by_identifier else {}
    for name, assets in by_identifier.items():
        by_uid[resolved[name]].extend(assets)
    for calendar_uid in by_uid:
        if calendar_uid not in resolved.values():
            resolve_calendar_uid(context, calendar_uid=calendar_uid)
    link_assets(context, links=by_uid, relink=relink)


def calendar_reference(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a registration payload that names the asset's trading calendar."""

    return {
        key: payload[key]
        for key in ("calendar_uid", "calendar_identifier")
        if payload.get(key) not in (None, "")
    }


def list_unlinked_assets(
    context: MarketsRepositoryContext,
    *,
    asset_type: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Assets that have no trading calendar, by ``unique_identifier``."""

    return operation_result_rows(
        read_unlinked_assets(context, asset_type=asset_type, limit=limit, offset=offset)
    )


__all__ = [
    "calendar_reference",
    "link_assets_to_calendar",
    "link_registered_assets",
    "list_unlinked_assets",
    "resolve_calendar_identifiers",
    "resolve_calendar_uid",
]
