from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from msm.models import CalendarEventTable
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import bulk_upsert_model


def bulk_upsert_calendar_events(
    context: MarketsRepositoryContext,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return bulk_upsert_model(
        context,
        model=CalendarEventTable,
        values=rows,
        conflict_columns=(
            "calendar_uid",
            "event_date",
            "event_type",
            "event_label",
            "target_type",
            "target_identifier",
        ),
    )


__all__ = ["bulk_upsert_calendar_events"]
