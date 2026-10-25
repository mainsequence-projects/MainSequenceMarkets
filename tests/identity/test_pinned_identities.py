"""Identities that a rename or a module move must not change by accident.

Several persisted identities are derived from where code lives and what it is
called:

- MetaTables hashes each updater's and each configuration class's
  ``{module, qualname}`` into the producer's ``update_hash``, and refers to a
  nested updater by that nested updater's ``update_hash``.
- ``signal_uid``, the portfolio configuration hash and the rebalance strategy
  revision include class paths and nested updater hashes. ``msm.identity`` maps
  moved paths and nested hashes back to their pre-rename values before hashing.
- Physical table names and MetaTable identifiers come from each model's
  authored identifier.

Changing a value pinned here rotates that identity in every Environment: new
``TimeIndexTableUpdate`` records, a new ``signal_uid`` whose rows do not include
the old ones, a different strategy revision on ledger events, or a different
table. ``PINNED_UPDATE_HASHES`` are MetaTables' own hashes and change whenever a
pinned class path changes; no other pinned value may. Change a pinned value only
on purpose and record the rotation in ``CHANGELOG.md``.
"""

from __future__ import annotations

import importlib
import pkgutil
import warnings
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pydantic import Field

from metatables import TimeIndexMetaTable, TimeIndexTableUpdateConfig, TimeIndexTableUpdater
from msm.time_index.assets import AssetSnapshot
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm.time_index.indices import configured_index_values_storage
import msm.identity as identity
from msm.identity import pre_rename_update_hash
from msm.settings import markets_auto_register_namespace
from msm_migrations.registry import metatable_provider_models
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfigBaseModel,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
    compute_strategy_revision,
)
from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
from msm_portfolios.contrib.signals.fixed_weights import (
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.contrib.signals.intraday_trend import IntradayTrend, IntradayTrendConfig
from msm_portfolios.time_index import (
    SignalWeights,
    compute_portfolio_configuration_hash,
    compute_signal_uid,
)
from msm_portfolios.time_index.contract_instances import configured_portfolios_storage
from msm_portfolios.time_index.prices.storage import configured_interpolated_prices_storage
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    LiquidityConstrained,
    TimeWeighted,
    TrailingAverageDailyVolumeParticipation,
    VolumeParticipation,
)

MARKETS_PACKAGES = ("msm", "msm_portfolios", "msm_pricing")

PINNED_TABLE_NAMES = {
    "AccountAllocationModelTable": "ms_markets__accountallocationmodel",
    "AccountGroupTable": "ms_markets__accountgroup",
    "AccountHoldingsSetTable": "ms_markets__accountholdingsset",
    "AccountHoldingsStorage": "ms_markets__accountholdingsts",
    "AccountTable": "ms_markets__account",
    "AccountTargetAllocationTable": "ms_markets__accounttargetallocation",
    "AssetCategoryMembershipTable": "ms_markets__assetcategorymembership",
    "AssetCategoryTable": "ms_markets__assetcategory",
    "AssetCurrentPricingDetailsTable": "ms_markets__assetcurrentpricingdetails",
    "AssetPricingDetailsStorage": "ms_markets__assetpricingdetailsts",
    "AssetSnapshotsStorage": "ms_markets__assetsnapshotsts",
    "AssetTable": "ms_markets__asset",
    "AssetTypeTable": "ms_markets__assettype",
    "BondAssetDetailsTable": "ms_markets__bondassetdetails",
    "CalendarDateTable": "ms_markets__calendardate",
    "CalendarEventTable": "ms_markets__calendarevent",
    "CalendarSessionTable": "ms_markets__calendarsession",
    "CalendarTable": "ms_markets__calendar",
    "CurrencySpotAssetDetailsTable": "ms_markets__currencyspotassetdetails",
    "CurveBuildingDetailsTable": "ms_markets__curvebuildingdetails",
    "CurveTable": "ms_markets__curve",
    "DiscountCurvesStorage": "ms_markets__discountcurvests",
    "ExternalPricesStorage": "ms_markets__externalpricests",
    "FutureAssetDetailsTable": "ms_markets__futureassetdetails",
    "IndexConventionDetailsTable": "ms_markets__indexconventiondetails",
    "IndexDatasetAvailabilityTable": "ms_markets__indexdatasetavailability",
    "IndexFixingsStorage": "ms_markets__indexfixingsts",
    "IndexFormulaDefinitionTable": "ms_markets__indexformuladefinition",
    "IndexFormulaInputTable": "ms_markets__indexformulainput",
    "IndexTable": "ms_markets__index",
    "IndexTypeTable": "ms_markets__indextype",
    "IndexValuesStorage": "ms_markets__indexvaluests",
    "IssuerTable": "ms_markets__issuer",
    "OpenFigiAssetDetailsTable": "ms_markets__openfigiassetdetails",
    "OrderEventsStorage": "ms_markets__ordereventsts",
    "OrderManagerTable": "ms_markets__ordermanager",
    "OrdersStorage": "ms_markets__ordersts",
    "PortfolioAnalyticsStorage": "ms_markets__portfolioanalyticsts",
    "PortfolioCalendarEventsStorage": "ms_markets__portfoliocalendareventsts",
    "PortfolioCashFlowsStorage": "ms_markets__portfoliocashflowsts",
    "PortfolioDatasetAvailabilityTable": "ms_markets__portfoliodatasetavailability",
    "PortfolioEventLedgerStorage": "ms_markets__portfolioeventledgerts",
    "PortfolioGroupMembershipTable": "ms_markets__portfoliogroupmembership",
    "PortfolioGroupTable": "ms_markets__portfoliogroup",
    "PortfolioMetadataTable": "ms_markets__portfoliometadata",
    "PortfolioRebalanceStateStorage": "ms_markets__portfoliorebalancestatets",
    "PortfolioStateStorage": "ms_markets__portfoliostatets",
    "PortfolioTable": "ms_markets__portfolio",
    "PortfolioWeightsStorage": "ms_markets__portfolioweightsts",
    "PortfoliosStorage": "ms_markets__portfoliosts",
    "PositionSetTable": "ms_markets__positionset",
    "PricingMarketDataSetBindingTable": "ms_markets__pricingmarketdatasetbinding",
    "PricingMarketDataSetCurveBindingTable": "ms_markets__pricingmarketdatasetcurvebinding",
    "PricingMarketDataSetTable": "ms_markets__pricingmarketdataset",
    "RebalanceStrategyMetadataTable": "ms_markets__rebalancestrategymetadata",
    "SignalMetadataTable": "ms_markets__signalmetadata",
    "SignalWeightsStorage": "ms_markets__signalweightsts",
    "TargetPositionsStorage": "ms_markets__targetpositionsts",
    "TradesStorage": "ms_markets__tradests",
    "VirtualFundHoldingsSetTable": "ms_markets__virtualfundholdingsset",
    "VirtualFundHoldingsStorage": "ms_markets__virtualfundholdingsts",
    "VirtualFundTable": "ms_markets__virtualfund",
}

PINNED_METATABLE_IDENTIFIERS = {
    "AccountAllocationModelTable": "AccountAllocationModel",
    "AccountGroupTable": "AccountGroup",
    "AccountHoldingsSetTable": "AccountHoldingsSet",
    "AccountHoldingsStorage": "AccountHoldingsTS",
    "AccountTable": "Account",
    "AccountTargetAllocationTable": "AccountTargetAllocation",
    "AssetCategoryMembershipTable": "AssetCategoryMembership",
    "AssetCategoryTable": "AssetCategory",
    "AssetCurrentPricingDetailsTable": "AssetCurrentPricingDetails",
    "AssetPricingDetailsStorage": "AssetPricingDetailsTS",
    "AssetSnapshotsStorage": "AssetSnapshotsTS",
    "AssetTable": "Asset",
    "AssetTypeTable": "AssetType",
    "BondAssetDetailsTable": "BondAssetDetails",
    "CalendarDateTable": "CalendarDate",
    "CalendarEventTable": "CalendarEvent",
    "CalendarSessionTable": "CalendarSession",
    "CalendarTable": "Calendar",
    "CurrencySpotAssetDetailsTable": "CurrencySpotAssetDetails",
    "CurveBuildingDetailsTable": "CurveBuildingDetails",
    "CurveTable": "Curve",
    "DiscountCurvesStorage": "DiscountCurvesTS",
    "ExternalPricesStorage": "ExternalPricesTS",
    "FutureAssetDetailsTable": "FutureAssetDetails",
    "IndexConventionDetailsTable": "IndexConventionDetails",
    "IndexDatasetAvailabilityTable": "IndexDatasetAvailability",
    "IndexFixingsStorage": "IndexFixingsTS",
    "IndexFormulaDefinitionTable": "IndexFormulaDefinition",
    "IndexFormulaInputTable": "IndexFormulaInput",
    "IndexTable": "Index",
    "IndexTypeTable": "IndexType",
    "IndexValuesStorage": "IndexValuesTS",
    "IssuerTable": "Issuer",
    "OpenFigiAssetDetailsTable": "OpenFigiAssetDetails",
    "OrderEventsStorage": "OrderEventsTS",
    "OrderManagerTable": "OrderManager",
    "OrdersStorage": "OrdersTS",
    "PortfolioAnalyticsStorage": "PortfolioAnalyticsTS",
    "PortfolioCalendarEventsStorage": "PortfolioCalendarEventsTS",
    "PortfolioCashFlowsStorage": "PortfolioCashFlowsTS",
    "PortfolioDatasetAvailabilityTable": "PortfolioDatasetAvailability",
    "PortfolioEventLedgerStorage": "PortfolioEventLedgerTS",
    "PortfolioGroupMembershipTable": "PortfolioGroupMembership",
    "PortfolioGroupTable": "PortfolioGroup",
    "PortfolioMetadataTable": "PortfolioMetadata",
    "PortfolioRebalanceStateStorage": "PortfolioRebalanceStateTS",
    "PortfolioStateStorage": "PortfolioStateTS",
    "PortfolioTable": "Portfolio",
    "PortfolioWeightsStorage": "PortfolioWeightsTS",
    "PortfoliosStorage": "PortfoliosTS",
    "PositionSetTable": "PositionSet",
    "PricingMarketDataSetBindingTable": "PricingMarketDataSetBinding",
    "PricingMarketDataSetCurveBindingTable": "PricingMarketDataSetCurveBinding",
    "PricingMarketDataSetTable": "PricingMarketDataSet",
    "RebalanceStrategyMetadataTable": "RebalanceStrategyMetadata",
    "SignalMetadataTable": "SignalMetadata",
    "SignalWeightsStorage": "SignalWeightsTS",
    "TargetPositionsStorage": "TargetPositionsTS",
    "TradesStorage": "TradesTS",
    "VirtualFundHoldingsSetTable": "VirtualFundHoldingsSet",
    "VirtualFundHoldingsStorage": "VirtualFundHoldingsTS",
    "VirtualFundTable": "VirtualFund",
}

PINNED_UPDATER_PATHS = (
    "msm.time_index.accounts.virtual_funds:VirtualFundHoldings",
    "msm.time_index.accounts:AccountHoldings",
    "msm.time_index.accounts:HoldingsUpdater",
    "msm.time_index.accounts:TargetPositions",
    "msm.time_index.assets.asset_indexed:AssetIndexedUpdater",
    "msm.time_index.assets.snapshots:AssetSnapshot",
    "msm.time_index.assets.snapshots:AssetTimestampedUpdater",
    "msm.time_index.execution:ExecutionUpdater",
    "msm.time_index.execution:OrderEvents",
    "msm.time_index.execution:Orders",
    "msm.time_index.execution:Trades",
    "msm.time_index.indices.formula:FormulaIndexUpdater",
    "msm.time_index.indices.timestamped:IndexTimestampedUpdater",
    "msm.time_index.indices.values:IndexValuesUpdater",
    "msm.time_index.utils.stamped:StampedUpdater",
    "msm_portfolios.contrib.prices.updaters:InterpolatedPrices",
    "msm_portfolios.contrib.signals.external_weights:ExternalWeights",
    "msm_portfolios.contrib.signals.fixed_weights:FixedWeights",
    "msm_portfolios.contrib.signals.intraday_trend:IntradayTrend",
    "msm_portfolios.contrib.signals.market_cap:MarketCap",
    "msm_portfolios.contrib.signals.portfolio_replicator:ETFReplicator",
    "msm_portfolios.time_index.base:AssetScopedPortfolioCanonicalUpdater",
    "msm_portfolios.time_index.base:PortfolioCanonicalUpdater",
    "msm_portfolios.time_index.portfolios.accounting:PortfolioEngine",
    "msm_portfolios.time_index.portfolios.analytics:PortfolioAnalytics",
    "msm_portfolios.time_index.portfolios.calendar_events:PortfolioCalendarEvents",
    "msm_portfolios.time_index.portfolios.rebalance:PortfolioRebalance",
    "msm_portfolios.time_index.portfolios.weights:PortfolioWeights",
    "msm_portfolios.time_index.portfolios:PortfoliosUpdater",
    "msm_portfolios.time_index.signals.weights:SignalWeights",
    "msm_pricing.time_index.curves:CurveTimestampedUpdater",
    "msm_pricing.time_index.curves:DiscountCurvesUpdater",
    "msm_pricing.time_index.index_fixings:FixingRatesUpdater",
    "msm_pricing.time_index.pricing_details:AssetPricingDetail",
)

PINNED_CONFIGURATION_PATHS = (
    "msm.time_index.accounts:HoldingsUpdaterConfiguration",
    "msm.time_index.accounts:TargetPositionsConfiguration",
    "msm.time_index.assets.asset_indexed:AssetIndexedUpdaterConfiguration",
    "msm.time_index.assets.snapshots:AssetUpdaterConfiguration",
    "msm.time_index.assets.snapshots:AssetSnapshotConfiguration",
    "msm.time_index.execution:ExecutionUpdaterConfiguration",
    "msm.time_index.indices.formula:FormulaIndexUpdaterConfiguration",
    "msm.time_index.indices.timestamped:IndexUpdaterConfiguration",
    "msm.time_index.utils.stamped:StampedUpdaterConfiguration",
    "msm_portfolios.contrib.prices.updaters:InterpolatedPricesConfig",
    "msm_portfolios.time_index.base:PortfolioCanonicalUpdaterConfiguration",
    "msm_portfolios.time_index.base:SignalWeightsConfiguration",
    "msm_portfolios.time_index.portfolios.accounting:PortfolioEngineConfiguration",
    "msm_portfolios.time_index.portfolios.analytics:PortfolioAnalyticsConfiguration",
    "msm_portfolios.time_index.portfolios.calendar_events:PortfolioCalendarEventsConfiguration",
    "msm_pricing.time_index.curves:CurveConfig",
    "msm_pricing.time_index.curves:CurveUpdaterConfiguration",
    "msm_pricing.time_index.index_fixings:IndexFixingConfiguration",
    "msm_pricing.time_index.pricing_details:AssetPricingDetailConfiguration",
)

PINNED_SIGNAL_UIDS = {
    "library_signal_weights": "bae957552a8ef090996db67ef64e846a",
    "library_fixed_weights": "2874b08647b5f015f339f08210f117ea",
    "application_signal": "278f13bd9d683932451e5f4087fec5a7",
}

PINNED_PORTFOLIO_CONFIGURATION_HASHES = {
    "library_signal_weights": "f952e2a6b3cfd73fd350f747d9b28eaa",
    "library_fixed_weights": "da0cf7e91fbdd7a6225c823c992e34c3",
}

PINNED_UPDATE_HASHES = {
    # Rotated in 3.0.0 when the classes moved to msm.time_index and
    # msm_portfolios.contrib.prices.updaters (ADR 0048).
    "asset_snapshot": "assetsnapshot_6eb60d0a440e8ab0b9794f1f5d3e42eb",
    "interpolated_prices": "interpolatedprices_946a6bc2b70ac3aa0e4a71cd0a1f1e32",
}

PINNED_PRE_RENAME_UPDATE_HASHES = {
    "asset_snapshot": "assetsnapshot_4d4316ca465e3c695835bc75d3af6f26",
    "interpolated_prices": "interpolatedprices_c4d16a20ee4ebf061f3581472e2e5f80",
}

PINNED_NESTED_SIGNAL_UIDS = {
    "intraday_trend_on_interpolated_prices": "1df893e892fe2788729ca2b73ade357c",
}

PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES = {
    "interpolated_prices_valuation": "4ea19e0e2eb0aa504cf795b79524e2c6",
    # Execution windows are datetime.time values, which hash as ISO strings.
    "time_weighted_rebalance": "878f466cbb3c0d7c7cd807769eea0ea1",
    "volume_participation_rebalance": "6c81dcd53cd19338933140ba6543375a",
    "trailing_average_daily_volume_rebalance": "134b49b83d79333d73c8ef6772627017",
}

PINNED_STRATEGY_REVISIONS = {
    "immediate_signal": "7b25ad849fae481a6d9eadb127b6ec3c53c6717a0ff527d9242ca371823a34ac",
    "liquidity_constrained_on_asset_snapshot": (
        "5fb439bc64593e44e5ea399a8903f0fc4de4fa71e80897d6a84864d125cddb67"
    ),
    "time_weighted_on_interpolated_prices": (
        "bdfd05cd41f40a138e77888ec15342eb22f2cfcb0a149539c51f05ef80e47325"
    ),
    "volume_participation_on_interpolated_prices": (
        "0af1d91c0620b9fd4105b091105c0cc164306412a6ac3a13d9ec309ce7b439a9"
    ),
    "trailing_average_daily_volume_on_asset_snapshot": (
        "e3eda5bb7990340e97aab0ad1d232cc9a93f717a041a5eeabd666904c9c90488"
    ),
}

PINNED_CONFIGURED_STORAGE = {
    "index_values_1d": ("ms_markets__index_values__t_1d", "IndexValuesTS.1d"),
    "interpolated_prices_1d_ffill": (
        "ms_markets__interpolated_prices__eeb2539c105f51d0",
        "InterpolatedPricesTS.eeb2539c105f51d0",
    ),
    "portfolios_contract_instance": (
        "pinned_app__portfoliosts__pinned_identity",
        "PortfoliosTS.pinned_identity",
    ),
}

SOURCE_TABLE_UID = "0f2d6c1e-7a3b-4c5d-9e8f-1a2b3c4d5e6f"
PRICES_TABLE_UID = "5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d"
DATA_SOURCE_UID = "7c8d9e0f-1a2b-4c3d-8e9f-0a1b2c3d4e5f"


class _Source(TimeIndexTableUpdater):
    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}


class ApplicationSignalConfiguration(PortfolioConfigBaseModel):
    """A signal configuration declared by an application, outside ms-markets."""

    lookback_days: int = Field(20, description="Days of history the signal reads.")


class ApplicationSignal(SignalWeights):
    """A signal declared by an application, outside ms-markets."""


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
    signal.update_hash = "signal"
    signal._output_table = _source("signal")._output_table
    signal.signal_configuration = configuration
    return signal


SIGNALS: dict[str, Callable[[], SignalWeights]] = {
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
    "application_signal": lambda: _signal(
        ApplicationSignal,
        ApplicationSignalConfiguration(lookback_days=20),
    ),
}


def _portfolio_configuration(
    signal: SignalWeights,
    *,
    valuation_source: TimeIndexTableUpdater | None = None,
    rebalance_strategy: Any | None = None,
) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=valuation_source or _source("valuation"),
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.0),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal,
                rebalance_strategy_instance=rebalance_strategy or ImmediateSignal(),
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
def _renamed(cls: type, name: str) -> Iterator[type]:
    """Rename a class in place; type slots cannot be restored by monkeypatch."""

    original = cls.__name__, cls.__qualname__
    cls.__name__ = cls.__qualname__ = name
    try:
        yield cls
    finally:
        cls.__name__, cls.__qualname__ = original


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


@pytest.fixture
def updaters() -> Iterator[dict[str, TimeIndexTableUpdater]]:
    with _built_updaters() as built:
        yield built


NESTED_SIGNALS: dict[str, Callable[[dict[str, Any]], SignalWeights]] = {
    "intraday_trend_on_interpolated_prices": lambda updaters: _signal(
        IntradayTrend,
        IntradayTrendConfig(
            price_source_instance=updaters["interpolated_prices"],
            asset_symbols_by_exchange={"XNAS": ["ASSET_A", "ASSET_B"]},
            calendar="XNAS",
        ),
    ),
}

STRATEGIES: dict[str, Callable[[dict[str, Any]], Any]] = {
    "immediate_signal": lambda updaters: ImmediateSignal(),
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
        SIGNALS["library_fixed_weights"](),
        valuation_source=updaters["interpolated_prices"],
        rebalance_strategy=STRATEGIES["liquidity_constrained_on_asset_snapshot"](updaters),
    ),
    "time_weighted_rebalance": lambda updaters: _portfolio_configuration(
        SIGNALS["library_fixed_weights"](),
        rebalance_strategy=STRATEGIES["time_weighted_on_interpolated_prices"](updaters),
    ),
    "volume_participation_rebalance": lambda updaters: _portfolio_configuration(
        SIGNALS["library_fixed_weights"](),
        rebalance_strategy=STRATEGIES["volume_participation_on_interpolated_prices"](updaters),
    ),
    "trailing_average_daily_volume_rebalance": lambda updaters: _portfolio_configuration(
        SIGNALS["library_fixed_weights"](),
        rebalance_strategy=STRATEGIES["trailing_average_daily_volume_on_asset_snapshot"](updaters),
    ),
}

CONFIGURED_STORAGE: dict[str, Callable[[], type]] = {
    "index_values_1d": lambda: configured_index_values_storage(cadence="1d"),
    "interpolated_prices_1d_ffill": _interpolated_prices_storage,
    "portfolios_contract_instance": lambda: configured_portfolios_storage(
        instance_key="pinned_identity",
        storage_app="pinned_app",
    ),
}


def _import_markets_modules() -> None:
    with warnings.catch_warnings():
        # The pre-3.0 import paths are deprecated aliases (ADR 0048).
        warnings.simplefilter("ignore", DeprecationWarning)
        for package_name in MARKETS_PACKAGES:
            package = importlib.import_module(package_name)
            for module in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
                importlib.import_module(module.name)


def _defined_subclass_paths(base: type) -> set[str]:
    """Return ``module:qualname`` for every ms-markets class importable at its own path."""

    _import_markets_modules()
    paths: set[str] = set()
    seen: set[type] = set()
    pending = [base]
    while pending:
        for subclass in pending.pop().__subclasses__():
            if subclass in seen:
                continue
            seen.add(subclass)
            pending.append(subclass)
            if subclass.__module__.split(".")[0] not in MARKETS_PACKAGES:
                continue
            try:
                module = importlib.import_module(subclass.__module__)
            except ImportError:
                continue
            if getattr(module, subclass.__qualname__, None) is subclass:
                paths.add(f"{subclass.__module__}:{subclass.__qualname__}")
    return paths


def _assert_paths_pinned(found: set[str], pinned: tuple[str, ...], kind: str) -> None:
    moved = sorted(set(pinned) - found)
    added = sorted(found - set(pinned))
    assert not moved, (
        f"These {kind} classes are no longer defined at their pinned path. MetaTables "
        f"hashes that path, so every producer built from them gets a new update_hash: "
        f"{moved}"
    )
    assert not added, (
        f"New {kind} classes are not pinned yet. Add their paths so a later move is "
        f"caught: {added}"
    )


namespace_is_default = pytest.mark.skipif(
    markets_auto_register_namespace() is not None,
    reason="Table names and identifiers are pinned for the default markets namespace.",
)


@namespace_is_default
def test_metatable_models_keep_their_physical_table_names() -> None:
    models = metatable_provider_models()

    assert {model.__name__: model.__table__.name for model in models} == PINNED_TABLE_NAMES


@namespace_is_default
def test_metatable_models_keep_their_metatable_identifiers() -> None:
    models = metatable_provider_models()

    assert {
        model.__name__: model.__metatable_identifier__ for model in models
    } == PINNED_METATABLE_IDENTIFIERS


def test_updater_class_paths_are_pinned() -> None:
    _assert_paths_pinned(
        _defined_subclass_paths(TimeIndexTableUpdater),
        PINNED_UPDATER_PATHS,
        "updater",
    )


def test_updater_configuration_class_paths_are_pinned() -> None:
    _assert_paths_pinned(
        _defined_subclass_paths(TimeIndexTableUpdateConfig),
        PINNED_CONFIGURATION_PATHS,
        "configuration",
    )


@pytest.mark.parametrize("signal_name", sorted(PINNED_SIGNAL_UIDS))
def test_signal_uid_is_pinned(signal_name: str) -> None:
    assert compute_signal_uid(SIGNALS[signal_name]()) == PINNED_SIGNAL_UIDS[signal_name]


@pytest.mark.parametrize("signal_name", sorted(PINNED_PORTFOLIO_CONFIGURATION_HASHES))
def test_portfolio_configuration_hash_is_pinned(signal_name: str) -> None:
    configuration = _portfolio_configuration(SIGNALS[signal_name]())

    assert (
        compute_portfolio_configuration_hash(configuration)
        == PINNED_PORTFOLIO_CONFIGURATION_HASHES[signal_name]
    )


@namespace_is_default
@pytest.mark.parametrize("name", sorted(PINNED_UPDATE_HASHES))
def test_metatables_update_hash_is_pinned(updaters, name: str) -> None:
    assert updaters[name].update_hash == PINNED_UPDATE_HASHES[name]


@namespace_is_default
@pytest.mark.parametrize("name", sorted(PINNED_PRE_RENAME_UPDATE_HASHES))
def test_pre_rename_update_hash_is_pinned(updaters, name: str) -> None:
    assert pre_rename_update_hash(updaters[name]) == PINNED_PRE_RENAME_UPDATE_HASHES[name]


@namespace_is_default
@pytest.mark.parametrize("name", sorted(PINNED_NESTED_SIGNAL_UIDS))
def test_signal_uid_with_nested_updaters_is_pinned(updaters, name: str) -> None:
    assert compute_signal_uid(NESTED_SIGNALS[name](updaters)) == PINNED_NESTED_SIGNAL_UIDS[name]


@namespace_is_default
@pytest.mark.parametrize("name", sorted(PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES))
def test_portfolio_configuration_hash_with_nested_updaters_is_pinned(updaters, name: str) -> None:
    configuration = NESTED_PORTFOLIOS[name](updaters)

    assert (
        compute_portfolio_configuration_hash(configuration)
        == PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES[name]
    )


@namespace_is_default
@pytest.mark.parametrize("name", sorted(PINNED_STRATEGY_REVISIONS))
def test_rebalance_strategy_revision_is_pinned(updaters, name: str) -> None:
    assert compute_strategy_revision(STRATEGIES[name](updaters)) == PINNED_STRATEGY_REVISIONS[name]


@namespace_is_default
@pytest.mark.parametrize("name", sorted(PINNED_CONFIGURED_STORAGE))
def test_configured_storage_keeps_its_table_name_and_identifier(name: str) -> None:
    storage = CONFIGURED_STORAGE[name]()

    assert (
        storage.__table__.name,
        storage.__metatable_identifier__,
    ) == PINNED_CONFIGURED_STORAGE[name]


@namespace_is_default
def test_simulated_class_moves_keep_ms_markets_identities(monkeypatch) -> None:
    """Move and rename pinned classes, as a package rename would, and re-derive every identity."""

    monkeypatch.setattr(
        identity,
        "PRE_RENAME_MODULES",
        (
            ("msm.relocated", "msm.data_nodes"),
            ("msm_portfolios.relocated_prices", "msm_portfolios.contrib.prices.data_nodes"),
            ("msm_portfolios.relocated_signals", "msm_portfolios.data_nodes.signals.weights"),
        ),
    )
    monkeypatch.setattr(identity, "PRE_RENAME_CLASS_NAMES", {"RelocatedSnapshot": "AssetSnapshot"})
    for cls, module in (
        (AssetSnapshot, "msm.relocated.assets.snapshots"),
        (InterpolatedPrices, "msm_portfolios.relocated_prices"),
        (InterpolatedPricesConfig, "msm_portfolios.relocated_prices"),
        (SignalWeights, "msm_portfolios.relocated_signals"),
    ):
        monkeypatch.setattr(cls, "__module__", module)

    with _renamed(AssetSnapshot, "RelocatedSnapshot"), _built_updaters() as moved:
        for name in PINNED_UPDATE_HASHES:
            assert moved[name].update_hash != PINNED_UPDATE_HASHES[name]
            assert pre_rename_update_hash(moved[name]) == PINNED_PRE_RENAME_UPDATE_HASHES[name]
        for name, build in NESTED_SIGNALS.items():
            assert compute_signal_uid(build(moved)) == PINNED_NESTED_SIGNAL_UIDS[name]
        for name, build in NESTED_PORTFOLIOS.items():
            assert (
                compute_portfolio_configuration_hash(build(moved))
                == PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES[name]
            )
        for name, build in STRATEGIES.items():
            assert compute_strategy_revision(build(moved)) == PINNED_STRATEGY_REVISIONS[name]

    signal = SIGNALS["library_signal_weights"]()
    assert compute_signal_uid(signal) == PINNED_SIGNAL_UIDS["library_signal_weights"]
    assert (
        compute_portfolio_configuration_hash(_portfolio_configuration(signal))
        == PINNED_PORTFOLIO_CONFIGURATION_HASHES["library_signal_weights"]
    )
