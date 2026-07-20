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
        Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
    )
    index_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{IndexTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
    )
    meta_table_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    cadence: Mapped[str] = mapped_column(String(32), nullable=False)
    population_state: Mapped[str] = mapped_column(String(32), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    earliest_time_index: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latest_time_index: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reconciled_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.datetime.now(datetime.UTC),
    )
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)


__all__ = ["IndexDatasetAvailabilityTable"]
