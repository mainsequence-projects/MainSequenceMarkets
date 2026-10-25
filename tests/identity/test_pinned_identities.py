"""Identities that a rename or a module move must not change by accident.

Several persisted identities are derived from where code lives and what it is
called:

- MetaTables hashes each updater's and each configuration class's
  ``{module, qualname}`` into the producer's ``update_hash``.
- ``signal_uid`` and the portfolio configuration hash include the signal's
  class path and its serialized configuration.
- Physical table names and MetaTable identifiers come from each model's
  authored identifier.

Changing a value pinned here rotates that identity in every Environment: new
``TimeIndexTableUpdate`` records, a new ``signal_uid`` whose rows do not include
the old ones, or a different table. Change a pinned value only on purpose and
record the rotation in ``CHANGELOG.md``.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from pydantic import Field

from metatables import TimeIndexMetaTable, TimeIndexTableUpdateConfig, TimeIndexTableUpdater
from msm.settings import markets_auto_register_namespace
from msm_migrations.registry import metatable_provider_models
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfigBaseModel,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.contrib.signals.fixed_weights import (
    AUIDWeight,
    FixedWeights,
    FixedWeightsConfig,
)
from msm_portfolios.data_nodes import (
    SignalWeights,
    compute_portfolio_configuration_hash,
    compute_signal_uid,
)
from msm_portfolios.rebalance_strategy import ImmediateSignal

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
    "msm.data_nodes.accounts.virtual_funds:VirtualFundHoldings",
    "msm.data_nodes.accounts:AccountHoldings",
    "msm.data_nodes.accounts:HoldingsDataNode",
    "msm.data_nodes.accounts:TargetPositions",
    "msm.data_nodes.assets.asset_indexed:AssetIndexedDataNode",
    "msm.data_nodes.assets.snapshots:AssetSnapshot",
    "msm.data_nodes.assets.snapshots:AssetTimestampedDataNode",
    "msm.data_nodes.execution:ExecutionDataNode",
    "msm.data_nodes.execution:OrderEvents",
    "msm.data_nodes.execution:Orders",
    "msm.data_nodes.execution:Trades",
    "msm.data_nodes.indices.formula:FormulaIndexDataNode",
    "msm.data_nodes.indices.timestamped:IndexTimestampedDataNode",
    "msm.data_nodes.indices.values:IndexValuesDataNode",
    "msm.data_nodes.utils.stamped:StampedDataNode",
    "msm_portfolios.contrib.prices.data_nodes:InterpolatedPrices",
    "msm_portfolios.contrib.signals.external_weights:ExternalWeights",
    "msm_portfolios.contrib.signals.fixed_weights:FixedWeights",
    "msm_portfolios.contrib.signals.intraday_trend:IntradayTrend",
    "msm_portfolios.contrib.signals.market_cap:MarketCap",
    "msm_portfolios.contrib.signals.portfolio_replicator:ETFReplicator",
    "msm_portfolios.data_nodes.base:AssetScopedPortfolioCanonicalDataNode",
    "msm_portfolios.data_nodes.base:PortfolioCanonicalDataNode",
    "msm_portfolios.data_nodes.portfolios.accounting:PortfolioEngine",
    "msm_portfolios.data_nodes.portfolios.analytics:PortfolioAnalytics",
    "msm_portfolios.data_nodes.portfolios.calendar_events:PortfolioCalendarEvents",
    "msm_portfolios.data_nodes.portfolios.rebalance:PortfolioRebalance",
    "msm_portfolios.data_nodes.portfolios.weights:PortfolioWeights",
    "msm_portfolios.data_nodes.portfolios:PortfoliosDataNode",
    "msm_portfolios.data_nodes.signals.weights:SignalWeights",
    "msm_pricing.data_nodes.curves:CurveTimestampedDataNode",
    "msm_pricing.data_nodes.curves:DiscountCurvesNode",
    "msm_pricing.data_nodes.index_fixings:FixingRatesNode",
    "msm_pricing.data_nodes.pricing_details:AssetPricingDetail",
)

PINNED_CONFIGURATION_PATHS = (
    "msm.data_nodes.accounts:HoldingsDataNodeConfiguration",
    "msm.data_nodes.accounts:TargetPositionsDataNodeConfiguration",
    "msm.data_nodes.assets.asset_indexed:AssetIndexedDataNodeConfiguration",
    "msm.data_nodes.assets.snapshots:AssetDataNodeConfiguration",
    "msm.data_nodes.assets.snapshots:AssetSnapshotConfiguration",
    "msm.data_nodes.execution:ExecutionDataNodeConfiguration",
    "msm.data_nodes.indices.formula:FormulaIndexDataNodeConfiguration",
    "msm.data_nodes.indices.timestamped:IndexDataNodeConfiguration",
    "msm.data_nodes.utils.stamped:StampedDataNodeConfiguration",
    "msm_portfolios.contrib.prices.data_nodes:InterpolatedPricesConfig",
    "msm_portfolios.data_nodes.base:PortfolioCanonicalDataNodeConfiguration",
    "msm_portfolios.data_nodes.base:SignalWeightsConfiguration",
    "msm_portfolios.data_nodes.portfolios.accounting:PortfolioEngineConfiguration",
    "msm_portfolios.data_nodes.portfolios.analytics:PortfolioAnalyticsConfiguration",
    "msm_portfolios.data_nodes.portfolios.calendar_events:PortfolioCalendarEventsConfiguration",
    "msm_pricing.data_nodes.curves:CurveConfig",
    "msm_pricing.data_nodes.curves:CurveDataNodeConfiguration",
    "msm_pricing.data_nodes.index_fixings:IndexFixingConfiguration",
    "msm_pricing.data_nodes.pricing_details:AssetPricingDetailConfiguration",
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


def _portfolio_configuration(signal: SignalWeights) -> PortfolioConfiguration:
    return PortfolioConfiguration(
        portfolio_build_configuration=PortfolioBuildConfiguration(
            valuation_source_instance=_source("valuation"),
            execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.0),
            backtesting_weights_configuration=BacktestingWeightsConfig(
                signal_weights_instance=signal,
                rebalance_strategy_instance=ImmediateSignal(),
            ),
        ),
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name="pinned-identity"),
    )


def _import_markets_modules() -> None:
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
