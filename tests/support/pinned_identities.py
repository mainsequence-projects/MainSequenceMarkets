"""Updaters, signals and portfolio configurations built for identity tests.

`tests/identity/test_pinned_identities.py` pins the identities derived from them; other
tests build the same objects. ms-markets' signals are in `LIBRARY_SIGNALS`. A signal an
application declares stays in the pinned test module, because its uid hashes its class
path there.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pandas as pd

from metatables import TimeIndexMetaTable, TimeIndexTableUpdater
from msm.time_index.assets import AssetSnapshot
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
from msm_portfolios.contrib.signals.application_weights import (
    ApplicationWeights,
    ApplicationWeightsConfig,
)
from msm_portfolios.contrib.signals.fixed_weights import (
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.time_index import SignalWeights
from msm_portfolios.time_index.prices.storage import configured_interpolated_prices_storage
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    LiquidityConstrained,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)

PINNED_PRE_RENAME_UPDATE_HASHES = {
    "asset_snapshot": "assetsnapshot_4d4316ca465e3c695835bc75d3af6f26",
    "interpolated_prices": "interpolatedprices_c4d16a20ee4ebf061f3581472e2e5f80",
}

SOURCE_TABLE_UID = "0f2d6c1e-7a3b-4c5d-9e8f-1a2b3c4d5e6f"
PRICES_TABLE_UID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"
DATA_SOURCE_UID = "7c8d9e0f-1a2b-4c3d-8e9f-0a1b2c3d4e5f"


class _Source(TimeIndexTableUpdater):
    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}


def _source(update_hash: str) -> _Source:
    source = object.__new__(_Source)
    source.update_hash = update_hash
    source._output_table = SimpleNamespace(
        get_time_index_meta_table=lambda: TimeIndexMetaTable.model_construct(
            uid=f"{update_hash}-table",
            data_source_uid="source",
        ),
        get_data_source_uid=lambda: "source",
    )
    return source


def _signal(signal_class: type[SignalWeights], configuration: Any) -> SignalWeights:
    signal = object.__new__(signal_class)
    signal.signal_configuration = configuration
    return signal


LIBRARY_SIGNALS: dict[str, Callable[[], SignalWeights]] = {
    "library_signal_weights": lambda: _signal(SignalWeights, {"kind": "pinned-identity"}),
    "library_fixed_weights": lambda: _signal(
        FixedWeights,
        FixedWeightsConfig(
            asset_unique_identifier_weights=[
                AUIDWeight(unique_identifier="ASSET_A", weight=0.6),
                AUIDWeight(unique_identifier="ASSET_B", weight=0.4),
            ]
        ),
    ),
    "library_application_weights": lambda: _signal(
        ApplicationWeights,
        ApplicationWeightsConfig(provider="pinned-provider", key="pinned-key"),
    ),
}


def _immediate_signal() -> ImmediateSignal:
    return ImmediateSignal(
        calendar_events_instance=_source("calendar-events"),
        calendar_identifier="XNYS",
    )


def _portfolio_configuration(
    signal: SignalWeights,
    *,
    valuation_source: TimeIndexTableUpdater | None = None,
    rebalance_strategy: Any | None = None,
) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=valuation_source or _source("valuation"),
            valuation_asset_identifier="USD",
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.0),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal,
                rebalance_strategy_instance=rebalance_strategy or _immediate_signal(),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name="pinned-identity"),
    )


@contextmanager
def _bound(storage: type, uid: str, **metadata: Any) -> Iterator[type]:
    """Bind fake backend metadata to a storage class and restore the class afterwards."""

    before = dict(vars(storage))
    storage._bind_meta_table(
        TimeIndexMetaTable.model_construct(
            uid=uid,
            data_source_uid=DATA_SOURCE_UID,
            identifier=storage.__metatable_identifier__,
            **metadata,
        )
    )
    try:
        yield storage
    finally:
        for name in set(vars(storage)) - set(before):
            delattr(storage, name)
        for name, value in before.items():
            if vars(storage).get(name) is not value:
                setattr(storage, name, value)


def _interpolated_prices_storage() -> type:
    return configured_interpolated_prices_storage(
        source_time_index_meta_table_uid=SOURCE_TABLE_UID,
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )


@contextmanager
def _built_updaters() -> Iterator[dict[str, TimeIndexTableUpdater]]:
    """Build real updaters through their constructors against fake bound tables."""

    with (
        _bound(AssetSnapshotsStorage, SOURCE_TABLE_UID, cadence="1d"),
        _bound(_interpolated_prices_storage(), PRICES_TABLE_UID),
    ):
        asset_snapshot = AssetSnapshot()
        interpolated_prices = InterpolatedPrices(
            InterpolatedPricesConfig(
                source_price_instance=asset_snapshot,
                intraday_bar_interpolation_rule="ffill",
                upsample_frequency_id="1d",
                asset_list=["ASSET_A", "ASSET_B"],
            )
        )
        yield {"asset_snapshot": asset_snapshot, "interpolated_prices": interpolated_prices}


STRATEGIES: dict[str, Callable[[dict[str, Any]], Any]] = {
    "immediate_signal": lambda updaters: _immediate_signal(),
    "liquidity_constrained_on_asset_snapshot": lambda updaters: LiquidityConstrained(
        liquidity_source_instance=updaters["asset_snapshot"]
    ),
    "time_weighted_on_interpolated_prices": lambda updaters: TimeWeighted(
        execution_bars_instance=updaters["interpolated_prices"]
    ),
    "volume_participation_on_interpolated_prices": lambda updaters: VolumeParticipation(
        execution_bars_instance=updaters["interpolated_prices"]
    ),
    "trailing_average_daily_volume_on_asset_snapshot": lambda updaters: (
        TrailingAverageDailyVolumeParticipation(
            daily_liquidity_instance=updaters["asset_snapshot"],
            execution_bars_instance=updaters["interpolated_prices"],
        )
    ),
}
NESTED_PORTFOLIOS: dict[str, Callable[[dict[str, Any]], PortfolioConfiguration]] = {
    "interpolated_prices_valuation": lambda updaters: _portfolio_configuration(
        LIBRARY_SIGNALS["library_fixed_weights"](),
        valuation_source=updaters["interpolated_prices"],
        rebalance_strategy=STRATEGIES["liquidity_constrained_on_asset_snapshot"](updaters),
    ),
    "time_weighted_rebalance": lambda updaters: _portfolio_configuration(
        LIBRARY_SIGNALS["library_fixed_weights"](),
        rebalance_strategy=STRATEGIES["time_weighted_on_interpolated_prices"](updaters),
    ),
    "volume_participation_rebalance": lambda updaters: _portfolio_configuration(
        LIBRARY_SIGNALS["library_fixed_weights"](),
        rebalance_strategy=STRATEGIES["volume_participation_on_interpolated_prices"](updaters),
    ),
    "trailing_average_daily_volume_rebalance": lambda updaters: _portfolio_configuration(
        LIBRARY_SIGNALS["library_fixed_weights"](),
        rebalance_strategy=STRATEGIES["trailing_average_daily_volume_on_asset_snapshot"](updaters),
    ),
}
