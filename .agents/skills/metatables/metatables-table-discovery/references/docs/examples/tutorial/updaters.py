"""Three connected producers; the library owns dependency execution and run states."""

from datetime import datetime
from random import random
from typing import ClassVar, Literal

from pydantic import Field

from metatables import PlatformTimeIndexMetaTable, TimeIndexTableUpdateConfig, TimeIndexTableUpdater

from .frames import (
    FIXTURE_NAME,
    START,
    SYMBOLS,
    VOLATILITY_WINDOW,
    daily_returns,
    recorded_prices,
    rolling_volatility,
)
from .tables import DailyClose, DailyReturn
from .tables import RollingVolatility as VolatilityTable


class PriceConfig(TimeIndexTableUpdateConfig):
    symbols: tuple[Literal["SPY", "QQQ", "IWM"], ...] = Field(
        default=SYMBOLS,
        min_length=1,
        description="Recorded instruments included in this producer's scope.",
        examples=[["SPY", "QQQ", "IWM"]],
    )
    offset_start: datetime = Field(
        default=START,
        description="First recorded UTC trading day included in the backfill.",
        examples=["2026-06-15T00:00:00Z"],
    )
    fixture: Literal[FIXTURE_NAME] = Field(
        default=FIXTURE_NAME,
        description="Immutable sample version included in producer identity.",
    )


class RecordedPrices(TimeIndexTableUpdater):
    def dependencies(self):
        return {}

    def update(self):
        return recorded_prices(
            symbols=self.config.symbols,
            start=self.config.offset_start,
            after=self.update_statistics.get_max_time_in_update_statistics(),
        )


class ReturnConfig(PriceConfig):
    price_table: type[PlatformTimeIndexMetaTable] = Field(
        description="Migrated price table consumed by this producer.",
    )


class DailyReturns(TimeIndexTableUpdater):
    FAILURE_PROBABILITY: ClassVar[float] = 0.5

    def __init__(
        self,
        config: ReturnConfig,
        output_table: type[PlatformTimeIndexMetaTable],
        *,
        hash_namespace: str | None = None,
    ):
        self.prices = RecordedPrices(
            config=PriceConfig(
                symbols=config.symbols,
                offset_start=config.offset_start,
                fixture=config.fixture,
            ),
            output_table=config.price_table,
            hash_namespace=hash_namespace,
        )
        super().__init__(config=config, output_table=output_table, hash_namespace=hash_namespace)

    def dependencies(self):
        return {"prices": self.prices}

    def update(self):
        # Execution behavior only: this draw does not change producer or data identity.
        if random() < self.FAILURE_PROBABILITY:
            raise RuntimeError("Simulated DailyReturns failure (50% probability per attempt).")
        # This finite sample is small; retain history so the next return has its prior close.
        prices = self.prices.get_df_between_dates(
            start_date=self.config.offset_start,
            dimension_filters={"symbol": list(self.config.symbols)},
        )
        return daily_returns(
            prices,
            after=self.update_statistics.get_max_time_in_update_statistics(),
        )


class VolatilityConfig(ReturnConfig):
    return_table: type[PlatformTimeIndexMetaTable] = Field(
        description="Migrated return table consumed by this producer.",
    )
    window_sessions: int = Field(
        default=VOLATILITY_WINDOW,
        ge=2,
        description="Number of trading-session returns in each rolling volatility window.",
        examples=[5],
    )


class RollingVolatility(TimeIndexTableUpdater):
    def __init__(
        self,
        config: VolatilityConfig,
        output_table: type[PlatformTimeIndexMetaTable],
        *,
        hash_namespace: str | None = None,
    ):
        self.returns = DailyReturns(
            config=ReturnConfig(
                price_table=config.price_table,
                symbols=config.symbols,
                offset_start=config.offset_start,
                fixture=config.fixture,
            ),
            output_table=config.return_table,
            hash_namespace=hash_namespace,
        )
        super().__init__(config=config, output_table=output_table, hash_namespace=hash_namespace)

    def dependencies(self):
        return {"returns": self.returns}

    def update(self):
        # Read the preceding sessions too so incremental results retain a full window.
        returns = self.returns.get_df_between_dates(
            start_date=self.config.offset_start,
            dimension_filters={"symbol": list(self.config.symbols)},
        )
        return rolling_volatility(
            returns,
            window_sessions=self.config.window_sessions,
            after=self.update_statistics.get_max_time_in_update_statistics(),
        )


def build_pipeline(root: Literal["returns", "volatility"] = "returns"):
    if root == "returns":
        return DailyReturns(
            config=ReturnConfig(price_table=DailyClose),
            output_table=DailyReturn,
            hash_namespace="market-tutorial",
        )
    if root == "volatility":
        return RollingVolatility(
            config=VolatilityConfig(price_table=DailyClose, return_table=DailyReturn),
            output_table=VolatilityTable,
            hash_namespace="market-tutorial",
        )
    raise ValueError(f"Unknown tutorial root: {root!r}")


def run_pipeline(root: Literal["returns", "volatility"] = "returns"):
    updater = build_pipeline(root)
    print(f"Tutorial root: {type(updater).__name__}", flush=True)
    # Invoke only the selected root. The library executes its declared dependencies.
    failed, _ = updater.run()
    if failed:
        raise RuntimeError(
            "The update cycle reported a failure; inspect the updater logs before retrying."
        )
    return {"root": type(updater).__name__, "update_hash": updater.update_hash, "completed": True}
