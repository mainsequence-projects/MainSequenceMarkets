from __future__ import annotations

import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index as SqlIndex, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.models.portfolios.core import PortfolioTable


class PortfolioDatasetAvailabilityTable(MarketsMetaTableMixin, MarketsBase):
    """Markets catalog of the time-series instances that hold one portfolio's datasets.

    ADR 0047: ``PortfoliosTS``, ``PortfolioWeightsTS`` and ``SignalWeightsTS`` are
    contracts with any number of instances, each owned and migrated by its
    producer. This row records, per portfolio, the MetaTable uid of the values,
    weights and signal instance that hold its rows, plus the reconciled
    population state of the values instance. The read services resolve the
    table from this row and read it by uid; a portfolio with no row reads the
    Markets-owned core tables.
    """

    __metatable_identifier__ = "PortfolioDatasetAvailability"
    __metatable_description__ = (
        "Per-portfolio catalog of the PortfoliosTS, PortfolioWeightsTS and SignalWeightsTS "
        "instances holding its rows, with the reconciled population state of the values "
        "instance. Catalog metadata only; it does not replace the time-series tables."
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
            name="portfolio_dataset_population_state_coherent",
        ),
        SqlIndex(None, "portfolio_uid", unique=True),
        SqlIndex(None, "values_meta_table_uid", "population_state"),
        SqlIndex(None, "population_state", "portfolio_uid"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for this catalog row.",
        },
    )
    portfolio_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(f"{PortfolioTable.__table__.fullname}.uid", ondelete="CASCADE"),
        nullable=False,
        info={
            "label": "Portfolio UID",
            "description": "Portfolio whose dataset instances this row catalogs.",
        },
    )
    values_meta_table_uid: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Values MetaTable UID",
            "description": "TimeIndexMetaTable uid of the PortfoliosTS instance holding the values.",
        },
    )
    weights_meta_table_uid: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Weights MetaTable UID",
            "description": (
                "TimeIndexMetaTable uid of the PortfolioWeightsTS instance holding the executed "
                "weights; null when the portfolio publishes no weights."
            ),
        },
    )
    signal_meta_table_uid: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        info={
            "label": "Signal MetaTable UID",
            "description": (
                "TimeIndexMetaTable uid of the SignalWeightsTS instance holding the signal "
                "weights; null when the portfolio has no signal."
            ),
        },
    )
    population_state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Population State",
            "description": (
                "Reconciled state of the values instance for this portfolio: populated, "
                "compatible_empty, or unavailable."
            ),
        },
    )
    row_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        info={
            "label": "Row Count",
            "description": (
                "Exact values row count when reconciliation succeeded; null when unavailable."
            ),
        },
    )
    earliest_time_index: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Earliest Time Index",
            "description": "Earliest values observation timestamp when populated.",
        },
    )
    latest_time_index: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Latest Time Index",
            "description": "Latest values observation timestamp when populated.",
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


__all__ = ["PortfolioDatasetAvailabilityTable"]
