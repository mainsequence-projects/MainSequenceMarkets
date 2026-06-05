from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from msm.models import CalendarDateTable
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import bulk_upsert_model


def bulk_upsert_calendar_dates(
    context: MarketsRepositoryContext,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return bulk_upsert_model(
        context,
        model=CalendarDateTable,
        values=rows,
        conflict_columns=("calendar_uid", "local_date"),
    )


__all__ = ["bulk_upsert_calendar_dates"]
