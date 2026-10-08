"""Instruments and three time-index stages: prices, returns, and volatility."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, Float, ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from metatables import (
    PlatformManagedMetaTable,
    PlatformTimeIndexMetaTable,
    schema_table_name,
    sqlalchemy_naming_convention,
)

NAMESPACE = "metatables_market_tutorial"
ASSET_IDENTIFIER = f"{NAMESPACE}.asset"
PRICE_IDENTIFIER = f"{NAMESPACE}.daily_close"
RETURN_IDENTIFIER = f"{NAMESPACE}.daily_return"
VOLATILITY_IDENTIFIER = f"{NAMESPACE}.rolling_volatility"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class Asset(PlatformManagedMetaTable, Base):
    __tablename__ = schema_table_name(NAMESPACE, "asset")
    __metatable_namespace__ = NAMESPACE
    __metatable_identifier__ = ASSET_IDENTIFIER
    __metatable_description__ = "The three instruments observed in the recorded market sample."

    uid: Mapped[UUID] = mapped_column(
        primary_key=True,
        info={"label": "Instrument UID", "description": "Stable identity of the instrument."},
    )
    symbol: Mapped[str] = mapped_column(
        String(16),
        unique=True,
        info={
            "label": "Symbol",
            "description": "Ticker used to join prices and returns to an instrument.",
        },
    )
    name: Mapped[str] = mapped_column(
        String(120),
        info={"label": "Name", "description": "Human-readable name of the instrument."},
    )


class DailyClose(PlatformTimeIndexMetaTable, Base):
    __tablename__ = schema_table_name(NAMESPACE, "daily_close")
    __metatable_namespace__ = NAMESPACE
    __metatable_identifier__ = PRICE_IDENTIFIER
    __metatable_description__ = (
        "One recorded adjusted closing price per UTC trading day and symbol."
    )
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "symbol"]
    __cadence__ = "1d"

    time_index: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Trading day", "description": "Trading date represented as UTC midnight."},
    )
    symbol: Mapped[str] = mapped_column(
        String(16),
        ForeignKey(f"{Asset.__table__.fullname}.symbol", ondelete="RESTRICT"),
        nullable=False,
        info={"label": "Symbol", "description": "Instrument whose price was observed."},
    )
    adjusted_close: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Adjusted close",
            "description": "Recorded USD closing price adjusted for distributions and splits.",
        },
    )


class DailyReturn(PlatformTimeIndexMetaTable, Base):
    __tablename__ = schema_table_name(NAMESPACE, "daily_return")
    __metatable_namespace__ = NAMESPACE
    __metatable_identifier__ = RETURN_IDENTIFIER
    __metatable_description__ = (
        "Change between consecutive recorded adjusted closes for each symbol."
    )
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "symbol"]
    __cadence__ = "1d"

    time_index: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Trading day",
            "description": "Day of the later price in the measured change.",
        },
    )
    symbol: Mapped[str] = mapped_column(
        String(16),
        ForeignKey(f"{Asset.__table__.fullname}.symbol", ondelete="RESTRICT"),
        nullable=False,
        info={"label": "Symbol", "description": "Instrument whose price change was measured."},
    )
    daily_return: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Daily return",
            "description": "Adjusted close divided by the previous session's close, minus one; 0.01 means 1%.",
        },
    )


class RollingVolatility(PlatformTimeIndexMetaTable, Base):
    __tablename__ = schema_table_name(NAMESPACE, "rolling_volatility")
    __metatable_namespace__ = NAMESPACE
    __metatable_identifier__ = VOLATILITY_IDENTIFIER
    __metatable_description__ = (
        "Annualized rolling return volatility per UTC trading day and symbol."
    )
    __time_index_name__ = "time_index"
    __index_names__ = ["time_index", "symbol"]
    __cadence__ = "1d"

    time_index: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={"label": "Trading day", "description": "Last trading day in the return window."},
    )
    symbol: Mapped[str] = mapped_column(
        String(16),
        ForeignKey(f"{Asset.__table__.fullname}.symbol", ondelete="RESTRICT"),
        nullable=False,
        info={"label": "Symbol", "description": "Instrument whose return volatility was measured."},
    )
    annualized_volatility: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        info={
            "label": "Annualized volatility",
            "description": (
                "Sample standard deviation of the configured return window times sqrt(252); "
                "0.20 means 20% annualized volatility."
            ),
        },
    )
