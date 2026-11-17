"""Dates and sessions computed from a calendar's rules and exceptions (ADR 0055).

They are not rows: nothing is stored per date, so they have no uid.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict

from msm.services.calendars.computation import ComputedDate, ComputedSession


class ComputedCalendarSession(BaseModel):
    """One session of one local date, with its UTC open and close."""

    model_config = ConfigDict(frozen=True)

    local_date: dt.date
    session_label: str
    opens_at: dt.datetime | None = None
    closes_at: dt.datetime | None = None
    timezone: str = "UTC"
    is_primary: bool = True
    is_early_close: bool = False
    is_late_open: bool = False

    @classmethod
    def from_computed(cls, session: ComputedSession) -> ComputedCalendarSession:
        return cls(
            local_date=session.local_date,
            session_label=session.session_label,
            opens_at=session.opens_at,
            closes_at=session.closes_at,
            timezone=session.timezone,
            is_primary=session.is_primary,
            is_early_close=session.is_early_close,
            is_late_open=session.is_late_open,
        )


class ComputedCalendarDate(BaseModel):
    """The business-day facts of one local date."""

    model_config = ConfigDict(frozen=True)

    local_date: dt.date
    is_business_day: bool
    is_holiday: bool
    is_weekend: bool
    is_early_close: bool
    holiday_name: str | None = None

    @classmethod
    def from_computed(cls, date: ComputedDate) -> ComputedCalendarDate:
        return cls(
            local_date=date.local_date,
            is_business_day=date.is_business_day,
            is_holiday=date.is_holiday,
            is_weekend=date.is_weekend,
            is_early_close=date.is_early_close,
            holiday_name=date.holiday_name,
        )


__all__ = ["ComputedCalendarDate", "ComputedCalendarSession"]
