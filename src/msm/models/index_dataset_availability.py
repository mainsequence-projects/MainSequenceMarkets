from __future__ import annotations

import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index as SqlIndex, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.models.indices import IndexTable


class IndexDatasetAvailabilityTable(MarketsMetaTableMixin, MarketsBase):
    """Rebuildable per-Index population state for canonical value datasets."""

    __metatable_identifier__ = "IndexDatasetAvailability"
    __metatable_description__ = (
        "Current reconciliation state for one Index in one canonical Index-values "
        "MetaTable. This catalog metadata supports bounded availability filters and "
        "does not replace the canonical value table."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        CheckConstraint(
            "(population_state = 'populated' AND row_count > 0 "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(population_state = 'compatible_empty' AND row_count = 0 "
            "AND earliest_time_index IS NULL AND latest_time_index IS NULL "
            "AND error_code IS NULL AND error_message IS NULL) OR "
            "(population_state = 'unavailable' AND row_count IS NULL "
            "AND earliest_time_index IS NULL AND latest_time_index IS NULL)",
            name="dataset_population_state_coherent",
        ),
        SqlIndex(None, "index_uid", "meta_table_uid", unique=True),
        SqlIndex(None, "index_uid", "population_state", "cadence"),
        SqlIndex(None, "population_state", "cadence", "index_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this availability row.",
        },
    )
    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Index UID",
            "description": "Index whose canonical dataset availability was reconciled.",
        },
    )
    meta_table_uid: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "MetaTable UID",
            "description": "Canonical Index-values MetaTable contract identifier.",
        },
    )
    cadence: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Cadence",
            "description": "Cadence declared by the canonical dataset contract.",
        },
    )
    population_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Population State",
            "description": (
                "Reconciled dataset state: populated, compatible_empty, or unavailable."
            ),
        },
    )
    row_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        info={
            "label": "Row Count",
            "description": (
                "Exact canonical row count when reconciliation succeeded; null when unavailable."
            ),
        },
    )
    earliest_time_index: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Earliest Time Index",
            "description": "Earliest canonical observation timestamp when populated.",
        },
    )
    latest_time_index: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Latest Time Index",
            "description": "Latest canonical observation timestamp when populated.",
        },
    )
    reconciled_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC),
        info={
            "label": "Reconciled At",
            "description": "UTC timestamp of the latest availability reconciliation.",
        },
    )
    error_code: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
        info={
            "label": "Error Code",
            "description": "Stable reconciliation error code when the dataset is unavailable.",
        },
    )
    error_message: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        info={
            "label": "Error Message",
            "description": "Diagnostic reconciliation message when the dataset is unavailable.",
        },
    )


__all__ = ["IndexDatasetAvailabilityTable"]
