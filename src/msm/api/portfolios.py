from __future__ import annotations

import uuid
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, model_validator

from msm.api.base import MarketsMetaTableRow
from msm.models import (
    CalendarTable,
    IndexTable,
    IndexTypeTable,
    PortfolioTable,
    SignalMetadataTable,
)


class Portfolio(MarketsMetaTableRow):
    """Typed portfolio identity and runtime configuration row."""

    __table__: ClassVar[type[PortfolioTable]] = PortfolioTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        CalendarTable,
        IndexTypeTable,
        IndexTable,
        SignalMetadataTable,
        PortfolioTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    calendar_uid: uuid.UUID
    published_index_uid: uuid.UUID | None = None
    portfolio_weights_data_node_uid: uuid.UUID | None = None
    signal_weights_data_node_uid: uuid.UUID | None = None
    signal_uid: str | None = None
    portfolio_data_node_uid: uuid.UUID | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    calendar_uid: uuid.UUID | str
    published_index_uid: uuid.UUID | str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    signal_uid: str | None = Field(default=None, max_length=255)
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str = "close"


class PortfolioUpsert(PortfolioCreate):
    """Payload for inserting or updating a portfolio."""


class PortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    calendar_uid: uuid.UUID | str | None = None
    published_index_uid: uuid.UUID | str | None = None
    portfolio_weights_data_node_uid: uuid.UUID | str | None = None
    signal_weights_data_node_uid: uuid.UUID | str | None = None
    signal_uid: str | None = Field(default=None, max_length=255)
    portfolio_data_node_uid: uuid.UUID | str | None = None
    backtest_table_price_column_name: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null_calendar_uid(cls, value: Any) -> Any:
        if isinstance(value, dict) and "calendar_uid" in value and value["calendar_uid"] is None:
            raise ValueError("calendar_uid cannot be null for Portfolio rows.")
        return value


__all__ = [
    "Portfolio",
    "PortfolioCreate",
    "PortfolioUpdate",
    "PortfolioUpsert",
]
