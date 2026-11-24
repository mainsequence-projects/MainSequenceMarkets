"""Accounting configurations built for tests, on the example's always-open calendar."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd

from metatables import TimeIndexMetaTable, TimeIndexTableUpdater
from msm_portfolios.accounting import (
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
)
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
)
from msm_portfolios.time_index import SignalWeights
from msm_portfolios.rebalance_strategy import ImmediateSignal

from examples.msm_portfolios.portfolio_cashflows_and_fx_valuation_example import (
    CALENDAR_EVENTS_TABLE,
)

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


def always_open_strategy(**kwargs) -> ImmediateSignal:
    """An ImmediateSignal on CRYPTO_24_7: every rebalance is at its signal's time."""
    return ImmediateSignal(
        calendar_events_instance=CALENDAR_EVENTS_TABLE,
        calendar_identifier="CRYPTO_24_7",
        **kwargs,
    )


def ledger(**overrides) -> PortfolioAccountingConfiguration:
    """A ledger of 1,000 USD from 2026-01-01, priced at market."""
    values = {
        "initial_nav": 1_000.0,
        "initial_state_time_index": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "position_valuation_model_instance": MarketPriceValuationModel(),
        **overrides,
    }
    return PortfolioAccountingConfiguration(**values)


def build_configuration(**overrides) -> PortfolioBuildConfiguration:
    """A build configuration with its ledger (ADR 0065), on the always-open calendar."""
    signal = object.__new__(SignalWeights)
    signal.update_hash = "signal"
    signal._output_table = _source("signal")._output_table
    signal.signal_configuration = {"kind": "test-signal"}
    values = {
        "valuation_source_instance": _source("valuation"),
        "valuation_asset_identifier": "USD",
        "backtesting_weights_configuration": BacktestingWeightsConfig(
            signal_weights_instance=signal,
            rebalance_strategy_instance=always_open_strategy(),
        ),
        "accounting_configuration": ledger(),
        **overrides,
    }
    return PortfolioBuildConfiguration(**values)
