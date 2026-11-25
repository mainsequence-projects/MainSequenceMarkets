"""Portfolio price-source time-index-table output contracts."""

from __future__ import annotations

import datetime
import hashlib
import json
from typing import ClassVar

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from msm.base import MarketsBase, MarketsTimeIndexMetaTableMixin
from msm.models.assets.core import AssetTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm.storage_instances import TimeIndexInstance, normalized_cadence


class InterpolatedPricesStorage(MarketsTimeIndexMetaTableMixin, MarketsBase):
    """Interpolated/upsampled OHLCV price bars keyed by asset unique identifier.

    The contract of interpolated prices. A producer writes its own instance of it, one
    per interpolation configuration (:func:`interpolated_prices_instance_key`), declared
    on :class:`InterpolatedPricesInstance`.
    """

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


def interpolated_prices_instance_key(
    *,
    source_table_name: str,
    source_cadence: str,
    intraday_bar_interpolation_rule: str,
    upsample_frequency_id: str | None = None,
) -> str:
    """The instance key of the one table that an interpolation configuration writes (#95).

    A producer declares that table with a class statement on
    :class:`InterpolatedPricesInstance` (``__instance_key__`` and ``__cadence__``) and migrates
    it, and ``InterpolatedPrices`` computes the same key when it runs.
    ``source_table_name`` is the source's physical table name: ``__table__.name`` of its
    class, ``physical_table_name`` of its registered table. It is the same in every
    Environment, where the table's UID is not. ``upsample_frequency_id`` is the source
    cadence when absent, and is the table's cadence.

    Rows are keyed only by time and asset, so another value of any of the four is
    another table.
    """

    table_name = str(source_table_name or "").strip()
    rule = str(intraday_bar_interpolation_rule or "").strip()
    if not table_name:
        raise ValueError("source_table_name must be a non-empty string.")
    if not rule:
        raise ValueError("intraday_bar_interpolation_rule must be a non-empty string.")
    cadence = normalized_cadence(source_cadence, argument="source_cadence")
    configuration = {
        "source_table_name": table_name,
        "source_cadence": cadence,
        "upsample_frequency_id": normalized_cadence(
            upsample_frequency_id or cadence, argument="upsample_frequency_id"
        ),
        "intraday_bar_interpolation_rule": rule,
    }
    encoded = json.dumps(configuration, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


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


class ExternalPricesInstance(TimeIndexInstance):
    """The base of an owner's own ``ExternalPricesTS`` table (``msm.storage_instances``)."""

    __abstract__ = True
    __core_storage__ = ExternalPricesStorage


class InterpolatedPricesInstance(TimeIndexInstance):
    """The base of a producer's interpolated-price table, one per configuration.

    Its key is :func:`interpolated_prices_instance_key` of the configuration and its
    ``__cadence__`` the configuration's upsample frequency::

        class DailyInterpolatedPrices(InterpolatedPricesInstance, ProviderBase):
            __instance_key__ = interpolated_prices_instance_key(
                source_table_name=DailyBars.__table__.name,
                source_cadence="1d",
                upsample_frequency_id="1d",
                intraday_bar_interpolation_rule="ffill",
            )
            __metatable_namespace__ = "my-provider"
            __markets_storage_app__ = "my_provider"
            __cadence__ = "1d"

    ``InterpolatedPrices`` refuses any other table for that configuration.
    """

    __abstract__ = True
    __core_storage__ = InterpolatedPricesStorage


__all__ = [
    "ExternalPricesInstance",
    "ExternalPricesStorage",
    "InterpolatedPricesInstance",
    "InterpolatedPricesStorage",
    "interpolated_prices_instance_key",
]
