"""Calendar services (ADR 0055).

Exports load on first use. ``msm.api.calendars`` imports the pure computation
from here, and the record services import the row payloads from there.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "CalendarDefinition": ".computation",
    "CalendarExceptionEntry": ".computation",
    "CalendarInUseConflictError": ".records",
    "CalendarRangeError": ".computation",
    "CalendarSourceDefinition": ".pandas_market",
    "CalendarSyncResult": ".sync",
    "ComputedDate": ".computation",
    "ComputedSession": ".computation",
    "DEFAULT_CALENDAR_TYPE": ".sync",
    "DEFAULT_SESSION_LABEL": ".computation",
    "DEFAULT_VALID_FROM": ".pandas_market",
    "EXCEPTION_CLOSED": ".computation",
    "EXCEPTION_EARLY_CLOSE": ".computation",
    "EXCEPTION_LATE_OPEN": ".computation",
    "EXCEPTION_OPEN": ".computation",
    "EXCEPTION_TYPES": ".computation",
    "PANDAS_MARKET_CALENDARS_SOURCE": ".pandas_market",
    "SOURCE_VERSION_KEY": ".sync",
    "SessionRule": ".computation",
    "USER_SOURCE": ".computation",
    "WHOLE_DAY": ".computation",
    "apply_calendar_source_definition": ".sync",
    "build_pandas_market_calendar_definition": ".pandas_market",
    "bulk_upsert_calendar_exception_records": ".records",
    "bulk_upsert_calendar_session_rule_records": ".records",
    "coerce_local_date": ".validation",
    "compute_dates": ".computation",
    "compute_sessions": ".computation",
    "create_calendar_exception_record": ".records",
    "create_calendar_record": ".records",
    "create_calendar_session_rule_record": ".records",
    "delete_calendar_exception_record": ".records",
    "delete_calendar_record": ".records",
    "delete_calendar_session_rule_record": ".records",
    "ensure_date_range": ".validation",
    "ensure_within_range": ".computation",
    "format_local_time": ".computation",
    "get_calendar_exception_record": ".records",
    "get_calendar_frontend_detail_summary": ".records",
    "get_calendar_record": ".records",
    "get_calendar_session_rule_record": ".records",
    "is_business_day": ".computation",
    "iter_local_dates": ".validation",
    "list_calendar_date_records_page": ".records",
    "list_calendar_exception_records_page": ".records",
    "list_calendar_records": ".records",
    "list_calendar_records_page": ".records",
    "list_calendar_session_records_page": ".records",
    "list_calendar_session_rule_records_page": ".records",
    "read_calendar_session_records": ".records",
    "refuse_delete_of_calendar_in_use": ".records",
    "load_calendar_definition": ".definitions",
    "normalize_weekdays": ".computation",
    "pandas_market_calendar_timezone": ".pandas_market",
    "parse_local_time": ".computation",
    "describe_calendar_sync": ".sync",
    "list_adapter_calendars": ".sync",
    "resync_adapter_calendars": ".sync",
    "sync_pandas_market_calendar": ".sync",
    "update_calendar_exception_record": ".records",
    "update_calendar_record": ".records",
    "update_calendar_session_rule_record": ".records",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted(_EXPORTS)
