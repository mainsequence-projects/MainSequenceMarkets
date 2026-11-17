from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from msm.models import CalendarSessionRuleTable
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import bulk_upsert_model, search_model

SESSION_RULE_KEYS = ("calendar_uid", "session_label", "effective_from")

_RULE_READ_LIMIT = 1000


def bulk_upsert_calendar_session_rules(
    context: MarketsRepositoryContext,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return bulk_upsert_model(
        context,
        model=CalendarSessionRuleTable,
        values=rows,
        conflict_columns=SESSION_RULE_KEYS,
    )


def search_calendar_session_rules(
    context: MarketsRepositoryContext,
    *,
    calendar_uid: uuid.UUID | str,
) -> dict[str, Any]:
    """Every session rule of one calendar: a few rows."""

    return search_model(
        context,
        model=CalendarSessionRuleTable,
        filters={"calendar_uid": calendar_uid},
        order_by=("session_label", "effective_from"),
        limit=_RULE_READ_LIMIT,
    )


__all__ = [
    "SESSION_RULE_KEYS",
    "bulk_upsert_calendar_session_rules",
    "search_calendar_session_rules",
]
