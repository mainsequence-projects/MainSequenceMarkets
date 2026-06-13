"""Portfolio price-source DataNode storage contracts."""

from __future__ import annotations

import datetime
import hashlib
import json
from functools import lru_cache
from typing import ClassVar

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
)
from sqlalchemy.orm import Mapped, mapped_column

from mainsequence.meta_tables import schema_index_name
from msm.base import (
    MARKETS_TABLE_APP,
    MarketsBase,
    MarketsTimeIndexMetaTableMixin,
    markets_table_name,
)
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION

INTERPOLATED_PRICES_SOURCE_TIME_INDEX_META_TABLE_UID_COMPONENT = "source_time_index_meta_table_uid"
INTERPOLATED_PRICES_SOURCE_CADENCE_COMPONENT = "source_cadence"
INTERPOLATED_PRICES_UPSAMPLE_FREQUENCY_COMPONENT = "upsample_frequency_id"
INTERPOLATED_PRICES_INTERPOLATION_RULE_COMPONENT = "intraday_bar_interpolation_rule"


class InterpolatedPricesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Interpolated/upsampled OHLCV price bars keyed by asset unique identifier."""

    __metatable_identifier__ = "InterpolatedPricesTS"
    __metatable_description__ = (
        "Timestamped interpolated-price storage keyed by (time_index, "
        "asset_identifier). Stores OHLCV bars, VWAP, trade count, and interpolation "
        "flags for asset price feeds used by portfolio workflows."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __index_names__: ClassVar[list[str]] = ["time_index", ASSET_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the interpolated price bar.",
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the priced instrument.",
        },
    )
    open_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Open Time",
            "description": "UTC timestamp marking the start of the price bar.",
        },
    )
    open: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Open", "description": "Opening price for the bar."},
    )
    high: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "High", "description": "Highest price during the bar."},
    )
    low: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Low", "description": "Lowest price during the bar."},
    )
    close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Close", "description": "Closing price for the bar."},
    )
    volume: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Volume", "description": "Traded volume during the bar."},
    )
    trade_count: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Trade Count", "description": "Number of trades observed during the bar."},
    )
    vwap: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "VWAP", "description": "Volume-weighted average price for the bar."},
    )
    interpolated: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        info={
            "label": "Interpolated",
            "description": "Whether the bar was synthetically interpolated.",
        },
    )


def interpolated_prices_storage_identity_components(
    *,
    source_time_index_meta_table_uid: str,
    source_cadence: str,
    upsample_frequency_id: str | None,
    intraday_bar_interpolation_rule: str,
) -> dict[str, str]:
    """Return storage-identity components for one interpolated price table."""

    return {
        INTERPOLATED_PRICES_SOURCE_TIME_INDEX_META_TABLE_UID_COMPONENT: str(
            source_time_index_meta_table_uid
        ),
        INTERPOLATED_PRICES_SOURCE_CADENCE_COMPONENT: str(source_cadence),
        INTERPOLATED_PRICES_UPSAMPLE_FREQUENCY_COMPONENT: str(
            upsample_frequency_id or source_cadence
        ),
        INTERPOLATED_PRICES_INTERPOLATION_RULE_COMPONENT: str(intraday_bar_interpolation_rule),
    }


def interpolated_prices_storage_table_name(
    *,
    source_time_index_meta_table_uid: str,
    source_cadence: str,
    upsample_frequency_id: str | None,
    intraday_bar_interpolation_rule: str,
) -> str:
    """Return the configured physical table name for interpolated prices."""

    contract_suffix = _interpolated_prices_storage_identity_suffix(
        interpolated_prices_storage_identity_components(
            source_time_index_meta_table_uid=source_time_index_meta_table_uid,
            source_cadence=source_cadence,
            upsample_frequency_id=upsample_frequency_id,
            intraday_bar_interpolation_rule=intraday_bar_interpolation_rule,
        )
    )
    return markets_table_name(
        MARKETS_TABLE_APP,
        "interpolated_prices",
        suffix=contract_suffix,
    )


@lru_cache(maxsize=256)
def configured_interpolated_prices_storage(
    *,
    source_time_index_meta_table_uid: str,
    source_cadence: str,
    upsample_frequency_id: str | None,
    intraday_bar_interpolation_rule: str,
) -> type[MarketsBase]:
    """Build the storage class for one interpolated-price storage identity."""

    components = interpolated_prices_storage_identity_components(
        source_time_index_meta_table_uid=source_time_index_meta_table_uid,
        source_cadence=source_cadence,
        upsample_frequency_id=upsample_frequency_id,
        intraday_bar_interpolation_rule=intraday_bar_interpolation_rule,
    )
    table_name = interpolated_prices_storage_table_name(
        source_time_index_meta_table_uid=source_time_index_meta_table_uid,
        source_cadence=source_cadence,
        upsample_frequency_id=upsample_frequency_id,
        intraday_bar_interpolation_rule=intraday_bar_interpolation_rule,
    )
    table = _copy_interpolated_prices_table(table_name)
    table_suffix = table_name.rsplit("_", 1)[-1]
    class_name = f"InterpolatedPricesStorage_{table_suffix}"
    return type(
        class_name,
        (MarketsTimeIndexMetaTableMixin, MarketsBase),
        {
            "__module__": __name__,
            "__table__": table,
            "__metatable_identifier__": f"InterpolatedPricesTS.{table_suffix}",
            "__metatable_description__": InterpolatedPricesStorage.__metatable_description__,
            "__metatable_extra_hash_components__": components,
            "__time_index_name__": InterpolatedPricesStorage.__time_index_name__,
            "__cadence__": components[INTERPOLATED_PRICES_UPSAMPLE_FREQUENCY_COMPONENT],
            "__index_names__": list(InterpolatedPricesStorage.__index_names__),
        },
    )


def _interpolated_prices_storage_identity_suffix(components: dict[str, str]) -> str:
    encoded = json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def _copy_interpolated_prices_table(table_name: str) -> Table:
    existing = MarketsBase.metadata.tables.get(table_name)
    if isinstance(existing, Table):
        return existing

    columns = [column._copy() for column in InterpolatedPricesStorage.__table__.columns]
    table = Table(
        table_name,
        MarketsBase.metadata,
        *columns,
        ForeignKeyConstraint(
            [ASSET_IDENTIFIER_DIMENSION],
            [f"{AssetTable.__table__.fullname}.unique_identifier"],
            ondelete="RESTRICT",
        ),
        schema=InterpolatedPricesStorage.__table__.schema,
        info=dict(InterpolatedPricesStorage.__table__.info or {}),
    )
    Index(
        schema_index_name(
            table_name,
            InterpolatedPricesStorage.__index_names__,
            unique=True,
        ),
        *(table.c[column_name] for column_name in InterpolatedPricesStorage.__index_names__),
        unique=True,
    )
    return table


class ExternalPricesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Externally supplied OHLCV price bars keyed by asset unique identifier."""

    __metatable_identifier__ = "ExternalPricesTS"
    __metatable_description__ = (
        "Timestamped externally supplied price bars keyed by (time_index, "
        "asset_identifier). Stores normalized OHLCV bars used as source price "
        "inputs for portfolio interpolation and construction workflows."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __cadence__: ClassVar[str] = "1d"
    __index_names__: ClassVar[list[str]] = ["time_index", ASSET_IDENTIFIER_DIMENSION]

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Time Index",
            "description": "UTC timestamp for the externally supplied price bar.",
        },
    )
    asset_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(
            f"{AssetTable.__table__.fullname}.unique_identifier",
            ondelete="RESTRICT",
        ),
        nullable=False,
        info={
            "label": "Asset Identifier",
            "description": "Asset unique identifier for the priced instrument.",
        },
    )
    open_time: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Open Time",
            "description": "UTC timestamp marking the start of the external price bar.",
        },
    )
    open: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Open", "description": "Opening price for the bar."},
    )
    high: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "High", "description": "Highest price during the bar."},
    )
    low: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Low", "description": "Lowest price during the bar."},
    )
    close: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Close", "description": "Closing price for the bar."},
    )
    volume: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Volume", "description": "Traded volume during the bar."},
    )
    trade_count: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "Trade Count", "description": "Number of trades observed during the bar."},
    )
    vwap: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
        info={"label": "VWAP", "description": "Volume-weighted average price for the bar."},
    )
    interpolated: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        info={
            "label": "Interpolated",
            "description": "Whether this external bar was already interpolated before ingestion.",
        },
    )


__all__ = [
    "ExternalPricesStorage",
    "INTERPOLATED_PRICES_INTERPOLATION_RULE_COMPONENT",
    "INTERPOLATED_PRICES_SOURCE_CADENCE_COMPONENT",
    "INTERPOLATED_PRICES_SOURCE_TIME_INDEX_META_TABLE_UID_COMPONENT",
    "INTERPOLATED_PRICES_UPSAMPLE_FREQUENCY_COMPONENT",
    "InterpolatedPricesStorage",
    "configured_interpolated_prices_storage",
    "interpolated_prices_storage_identity_components",
    "interpolated_prices_storage_table_name",
]
