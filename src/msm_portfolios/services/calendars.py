from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from msm.api.assets import Asset, AssetCalendar
from msm.api.calendars import Calendar
from msm.services.calendars import ensure_date_range

# One governed read returns at most 1,000 rows; stay well inside it.
_IN_FILTER_ROWS = 500


@dataclass(frozen=True)
class PersistedCalendarSchedule:
    """Pandas-like schedule adapter over a stored calendar.

    Sessions are computed by ``Calendar.sessions`` from the calendar's session
    rules and exceptions (ADR 0055), so the schedule works under the remote row
    backend as well as on a Markets runtime. A window outside the calendar's
    ``valid_from``..``valid_to`` raises ``CalendarRangeError``.
    """

    calendar: Calendar
    session_label: str = "regular"

    @property
    def name(self) -> str:
        return self.calendar.unique_identifier

    def schedule(
        self,
        start_date: dt.date | dt.datetime | str,
        end_date: dt.date | dt.datetime | str,
    ) -> pd.DataFrame:
        start, end = ensure_date_range(start_date, end_date)
        sessions = Calendar.sessions(
            self.calendar.uid,
            start,
            end,
            session_label=self.session_label,
        )
        if not sessions:
            return pd.DataFrame(columns=["market_open", "market_close"])

        frame = pd.DataFrame(
            {
                "local_date": [session.local_date for session in sessions],
                "market_open": pd.to_datetime([session.opens_at for session in sessions], utc=True),
                "market_close": pd.to_datetime(
                    [session.closes_at for session in sessions], utc=True
                ),
            }
        )
        return frame.set_index("local_date")[["market_open", "market_close"]]


def resolve_rebalance_calendar(calendar_key: str) -> Any:
    """Resolve a stored calendar for an economic rebalance contract.

    Calendar-relative execution must remain reproducible from the governed
    calendar rows. Missing calendars and backend lookup failures are therefore
    errors; callers never silently switch to a local calendar implementation.

    A calendar is found by its ``unique_identifier`` only. Several stored
    calendars can come from one library calendar, so a ``source_identifier``
    does not name one (ADR 0055).
    """

    identifier = str(calendar_key).strip()
    if not identifier:
        raise ValueError("calendar_identifier must be a non-empty string.")

    calendar = Calendar.get_by_unique_identifier(identifier)
    if calendar is None:
        raise ValueError(
            f"Stored rebalance calendar {identifier!r} was not found. "
            "Create the Calendar with its session rules and exceptions before "
            "publishing PortfolioCalendarEvents."
        )
    return PersistedCalendarSchedule(calendar=calendar)


class AssetCalendarMissingError(ValueError):
    """Assets in a price scope that have no trading calendar (ADR 0056)."""

    def __init__(self, *, unlinked: Sequence[str], unknown: Sequence[str]) -> None:
        self.unlinked = list(unlinked)
        self.unknown = list(unknown)
        parts = []
        if self.unlinked:
            parts.append(
                "No trading calendar is linked to: "
                + ", ".join(self.unlinked)
                + ". Link each asset with AssetCalendar.upsert(asset_uid=..., calendar_uid=...)."
            )
        if self.unknown:
            parts.append(
                "Not an Asset row, so it has no trading calendar: " + ", ".join(self.unknown) + "."
            )
        super().__init__(" ".join(parts))


def resolve_asset_schedules(
    asset_identifiers: Iterable[str],
) -> dict[str, PersistedCalendarSchedule]:
    """The stored trading calendar of each asset, as a schedule.

    Reads the ``Asset`` rows by ``unique_identifier``, their ``AssetCalendar``
    links, and each distinct ``Calendar`` once. There is no default calendar: when
    any asset has no link, or is not an ``Asset`` row, nothing is returned and
    ``AssetCalendarMissingError`` names every such asset.
    """

    identifiers = list(dict.fromkeys(str(identifier) for identifier in asset_identifiers))
    if not identifiers:
        return {}

    assets = _filter_in(Asset, "unique_identifier", identifiers)
    asset_uid_by_identifier = {asset.unique_identifier: asset.uid for asset in assets}
    links = _filter_in(AssetCalendar, "asset_uid", list(asset_uid_by_identifier.values()))
    calendar_uid_by_asset_uid = {link.asset_uid: link.calendar_uid for link in links}

    unknown = [i for i in identifiers if i not in asset_uid_by_identifier]
    unlinked = [
        i
        for i in identifiers
        if i in asset_uid_by_identifier
        and asset_uid_by_identifier[i] not in calendar_uid_by_asset_uid
    ]
    if unknown or unlinked:
        raise AssetCalendarMissingError(unlinked=unlinked, unknown=unknown)

    calendar_uids = list(dict.fromkeys(calendar_uid_by_asset_uid.values()))
    schedules = {
        calendar.uid: PersistedCalendarSchedule(calendar=calendar)
        for calendar in _filter_in(Calendar, "uid", calendar_uids)
    }
    return {
        identifier: schedules[calendar_uid_by_asset_uid[asset_uid_by_identifier[identifier]]]
        for identifier in identifiers
    }


def _filter_in(row_model: Any, column: str, values: Sequence[Any]) -> list[Any]:
    rows: list[Any] = []
    for start in range(0, len(values), _IN_FILTER_ROWS):
        chunk = list(values[start : start + _IN_FILTER_ROWS])
        rows.extend(row_model.filter(**{f"{column}__in": chunk}, limit=len(chunk)))
    return rows


__all__ = [
    "AssetCalendarMissingError",
    "PersistedCalendarSchedule",
    "resolve_asset_schedules",
    "resolve_rebalance_calendar",
]
