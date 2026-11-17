"""Load a stored calendar as a ``CalendarDefinition`` (ADR 0055)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories import MarketsRepositoryContext
from msm.repositories.calendars import read_calendar_exceptions, search_calendar_session_rules

from .computation import CalendarDefinition


def load_calendar_definition(
    context: MarketsRepositoryContext,
    *,
    calendar: Mapping[str, Any],
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> CalendarDefinition:
    """Read a calendar's rules, and its exceptions from ``start_date`` to ``end_date``.

    The rules are a few rows. Only the exceptions of the requested dates are
    read: a date's sessions depend on that date's exceptions alone.
    """

    calendar_uid = calendar["uid"]
    return CalendarDefinition.from_rows(
        timezone=str(calendar.get("timezone") or "UTC"),
        rules=operation_result_rows(
            search_calendar_session_rules(context, calendar_uid=calendar_uid)
        ),
        exceptions=read_calendar_exceptions(
            context,
            calendar_uid=calendar_uid,
            start_date=start_date,
            end_date=end_date,
        ),
        valid_from=calendar.get("valid_from"),
        valid_to=calendar.get("valid_to"),
        unique_identifier=str(calendar.get("unique_identifier") or ""),
    )


__all__ = ["load_calendar_definition"]
