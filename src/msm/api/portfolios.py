from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from msm.api.base import MarketsMetaTableRow
from msm.models import CalendarTable, IndexTable, PortfolioTable


class Portfolio(MarketsMetaTableRow):
    """Typed portfolio identity and runtime configuration row."""

    __table__: ClassVar[type[PortfolioTable]] = PortfolioTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CalendarTable,
        IndexTable,
        PortfolioTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    calendar_name: str | None = None
    calendar_uid: uuid.UUID | None = None
    portfolio_index_uid: uuid.UUID | None = None
    portfolio_weights_data_node_uid: uuid.UUID | None = None
    signal_weights_data_node_uid: uuid.UUID | None = None
    portfolio_data_node_uid: uuid.UUID | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    calendar_name: str | None = Field(default=None, max_length=255)
    calendar_uid: uuid.UUID | str | None = None
    portfolio_index_uid: uuid.UUID | str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioUpsert(PortfolioCreate):
    """Payload for inserting or updating a portfolio."""


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_name: str | None = Field(default=None, max_length=255)
    calendar_uid: uuid.UUID | str | None = None
    portfolio_index_uid: uuid.UUID | str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str | None = None


__all__ = [
    "Portfolio",
    "PortfolioCreate",
    "PortfolioUpdate",
    "PortfolioUpsert",
]
