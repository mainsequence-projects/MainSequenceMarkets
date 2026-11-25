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
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import TimeIndexMetaTable, TimeIndexTableUpdater, sqlalchemy_naming_convention
from msm.time_index.assets import AssetSnapshot
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm_portfolios.accounting import (
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
)
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
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
from msm_portfolios.time_index import SignalWeights, SignalWeightsSource
from msm_portfolios.time_index.prices.storage import (
    InterpolatedPricesInstance,
    interpolated_prices_instance_key,
)
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    LiquidityConstrained,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)

PINNED_PRE_RENAME_UPDATE_HASHES = {
    "asset_snapshot": "assetsnapshot_4d4316ca465e3c695835bc75d3af6f26",
    # Rotated in 5.0.0: MetaTables 0.1.74 hashes a positional configuration as a keyword
    # one (MetaTables#130), so this is also the keyword-constructed updater's hash. Rotated
    # in 6.2.0 when InterpolatedPricesConfig lost source_time_index_meta_table_uid.
    "interpolated_prices": "interpolatedprices_f1066f6ab896c70d453debd3b8df8c66",
}

SOURCE_TABLE_UID = "0f2d6c1e-7a3b-4c5d-9e8f-1a2b3c4d5e6f"
PRICES_TABLE_UID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"
DATA_SOURCE_UID = "7c8d9e0f-1a2b-4c3d-8e9f-0a1b2c3d4e5f"


class PinnedBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class _Source(TimeIndexTableUpdater):
    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}


def _output_table(update_hash: str) -> SimpleNamespace:
    return SimpleNamespace(
        get_time_index_meta_table=lambda: TimeIndexMetaTable.model_construct(
            uid=f"{update_hash}-table",
            data_source_uid="source",
        ),
        get_data_source_uid=lambda: "source",
        get_meta_table_uid=lambda: f"{update_hash}-table",
    )


def _source(update_hash: str) -> _Source:
    source = object.__new__(_Source)
    source.update_hash = update_hash
    source.update_statistics = None
    source._output_table = _output_table(update_hash)
    return source


def _signal(signal_class: type[SignalWeightsSource], configuration: Any) -> SignalWeightsSource:
    """The signal of ``configuration``, built without a table.

    A published signal is built as it is. A computed one stands in for its node, with the
    update hash and table a run gives it: a portfolio's rebalance saves the signal by them
    (ADR 0067, decision 4). The update hash follows the signal's uid.
    """

    if not issubclass(signal_class, TimeIndexTableUpdater):
        return signal_class.from_signal_configuration(configuration)
    signal = object.__new__(signal_class)
    signal.signal_configuration = configuration
    signal.update_hash = f"{signal_class.__name__.lower()}_{signal.signal_uid}"
    signal.update_statistics = None
    signal._output_table = _output_table(signal.update_hash)
    return signal


LIBRARY_SIGNALS: dict[str, Callable[[], SignalWeights]] = {
    "library_signal_weights": lambda: _signal(SignalWeights, {"kind": "pinned-identity"}),
    "library_fixed_weights": lambda: _signal(
        FixedWeights,
        FixedWeightsConfig(
            asset_unique_identifier_weights=[
                AUIDWeight(unique_identifier="ASSET_A", weight=0.6),
                AUIDWeight(unique_identifier="ASSET_B", weight=0.4),
            ],
            signal_time_index=pd.Timestamp("2026-01-02T12:00:00Z").to_pydatetime(),
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


PINNED_ACCOUNTING = PortfolioAccountingConfiguration(
    initial_nav=50_000_000.0,
    initial_state_time_index=pd.Timestamp("2026-01-02T00:00:00Z").to_pydatetime(),
    position_valuation_model_instance=MarketPriceValuationModel(),
)
"""The ledger every pinned portfolio keeps (ADR 0065)."""


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
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal,
                rebalance_strategy_instance=rebalance_strategy or _immediate_signal(),
            ),
            accounting_configuration=PINNED_ACCOUNTING,
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


class PinnedInterpolatedPrices(InterpolatedPricesInstance, PinnedBase):
    """The pinned interpolated-price table: daily bars of AssetSnapshotsTS, forward filled."""

    __instance_key__ = interpolated_prices_instance_key(
        source_table_name=AssetSnapshotsStorage.__table__.name,
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    __metatable_namespace__ = "pinned-app"
    __markets_storage_app__ = "pinned_app"
    __cadence__ = "1d"


@contextmanager
def _built_updaters() -> Iterator[dict[str, TimeIndexTableUpdater]]:
    """Build real updaters through their constructors against fake bound tables."""

    with (
        _bound(
            AssetSnapshotsStorage,
            SOURCE_TABLE_UID,
            cadence="1d",
            physical_table_name=AssetSnapshotsStorage.__table__.name,
        ),
        _bound(PinnedInterpolatedPrices, PRICES_TABLE_UID, cadence="1d"),
    ):
        asset_snapshot = AssetSnapshot()
        interpolated_prices = InterpolatedPrices(
            InterpolatedPricesConfig(
                source_price_instance=asset_snapshot,
                intraday_bar_interpolation_rule="ffill",
                upsample_frequency_id="1d",
                asset_list=["ASSET_A", "ASSET_B"],
            ),
            output_table=PinnedInterpolatedPrices,
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
