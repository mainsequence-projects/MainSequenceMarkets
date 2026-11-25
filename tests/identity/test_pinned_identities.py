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

A computed signal is a MetaTables updater (2026-11-24): its class path is pinned with
the updaters' and with the signals'.

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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from pydantic import Field

from metatables import TimeIndexTableUpdateConfig, TimeIndexTableUpdater
from msm.time_index.assets import AssetSnapshot
from msm.time_index.indices import IndexValues1d
import msm.identity as identity
from msm.identity import pre_rename_update_hash
from msm.settings import DEFAULT_MARKETS_NAMESPACE
from msm_migrations.registry import metatable_provider_models
from msm_portfolios.configuration import (
    PortfolioConfigBaseModel,
    compute_strategy_revision,
)
from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
from msm_portfolios.contrib.signals.intraday_trend import IntradayTrend, IntradayTrendConfig
from msm_portfolios.time_index import (
    SignalWeights,
    SignalWeightsSource,
    compute_portfolio_configuration_hash,
    compute_signal_uid,
)
from msm_portfolios.time_index.contract_instances import PortfolioRebalanceStateInstance
from tests.support.pinned_identities import (
    LIBRARY_SIGNALS,
    NESTED_PORTFOLIOS,
    PINNED_PRE_RENAME_UPDATE_HASHES,
    STRATEGIES,
    PinnedBase,
    PinnedInterpolatedPrices,
    _built_updaters,
    _portfolio_configuration,
    _signal,
)

MARKETS_PACKAGES = ("msm", "msm_portfolios", "msm_pricing")

PINNED_TABLE_NAMES = {
    "AccountAllocationLinesStorage": "ms_markets__accountallocationlinests",
    "AccountAllocationModelTable": "ms_markets__accountallocationmodel",
    "AccountGroupTable": "ms_markets__accountgroup",
    "AccountHoldingsSetTable": "ms_markets__accountholdingsset",
    "AccountHoldingsStorage": "ms_markets__accountholdingsts",
    "AccountTable": "ms_markets__account",
    "AccountTargetAllocationTable": "ms_markets__accounttargetallocation",
    "AssetCalendarTable": "ms_markets__assetcalendar",
    "AssetCategoryMembershipTable": "ms_markets__assetcategorymembership",
    "AssetCategoryTable": "ms_markets__assetcategory",
    "AssetCurrentPricingDetailsTable": "ms_markets__assetcurrentpricingdetails",
    "AssetPricingDetailsStorage": "ms_markets__assetpricingdetailsts",
    "AssetSnapshotsStorage": "ms_markets__assetsnapshotsts",
    "AssetTable": "ms_markets__asset",
    "AssetTypeTable": "ms_markets__assettype",
    "BondAssetDetailsTable": "ms_markets__bondassetdetails",
    "CalendarExceptionTable": "ms_markets__calendarexception",
    "CalendarSessionRuleTable": "ms_markets__calendarsessionrule",
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
    "IndexValues1m": "ms_markets__index_values__t_1m",
    "IndexValues1h": "ms_markets__index_values__t_1h",
    "IndexValues1d": "ms_markets__index_values__t_1d",
    "IssuerTable": "ms_markets__issuer",
    "OpenFigiAssetDetailsTable": "ms_markets__openfigiassetdetails",
    "OrderEventsStorage": "ms_markets__ordereventsts",
    "OrderManagerTable": "ms_markets__ordermanager",
    "OrderTable": "ms_markets__order",
    "OrdersStorage": "ms_markets__ordersts",
    "PortfolioAnalyticsStorage": "ms_markets__portfolioanalyticsts",
    "PortfolioCalendarEventsStorage": "ms_markets__portfoliocalendareventsts",
    "PortfolioCashFlowsStorage": "ms_markets__portfoliocashflowsts",
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
    "AccountAllocationLinesStorage": "AccountAllocationLinesTS",
    "AccountAllocationModelTable": "AccountAllocationModel",
    "AccountGroupTable": "AccountGroup",
    "AccountHoldingsSetTable": "AccountHoldingsSet",
    "AccountHoldingsStorage": "AccountHoldingsTS",
    "AccountTable": "Account",
    "AccountTargetAllocationTable": "AccountTargetAllocation",
    "AssetCalendarTable": "AssetCalendar",
    "AssetCategoryMembershipTable": "AssetCategoryMembership",
    "AssetCategoryTable": "AssetCategory",
    "AssetCurrentPricingDetailsTable": "AssetCurrentPricingDetails",
    "AssetPricingDetailsStorage": "AssetPricingDetailsTS",
    "AssetSnapshotsStorage": "AssetSnapshotsTS",
    "AssetTable": "Asset",
    "AssetTypeTable": "AssetType",
    "BondAssetDetailsTable": "BondAssetDetails",
    "CalendarExceptionTable": "CalendarException",
    "CalendarSessionRuleTable": "CalendarSessionRule",
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
    "IndexValues1m": "IndexValuesTS.1m",
    "IndexValues1h": "IndexValuesTS.1h",
    "IndexValues1d": "IndexValuesTS.1d",
    "IssuerTable": "Issuer",
    "OpenFigiAssetDetailsTable": "OpenFigiAssetDetails",
    "OrderEventsStorage": "OrderEventsTS",
    "OrderManagerTable": "OrderManager",
    "OrderTable": "Order",
    "OrdersStorage": "OrdersTS",
    "PortfolioAnalyticsStorage": "PortfolioAnalyticsTS",
    "PortfolioCalendarEventsStorage": "PortfolioCalendarEventsTS",
    "PortfolioCashFlowsStorage": "PortfolioCashFlowsTS",
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
    "msm.storage_copies:TimeIndexRowsCopy",
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
    # A computed signal is its own node, with its producer's table (2026-11-24).
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
    "msm_portfolios.time_index.signals.weights:SignalWeights",
    "msm_pricing.time_index.curves:CurveTimestampedUpdater",
    "msm_pricing.time_index.curves:DiscountCurvesUpdater",
    "msm_pricing.time_index.index_fixings:FixingRatesUpdater",
    "msm_pricing.time_index.pricing_details:AssetPricingDetail",
)

PINNED_PUBLISHED_NODE_PATHS = (
    # Nodes of the published portfolio series (ADR 0060): no MetaTables update hash.
    "msm_portfolios.time_index.portfolios.weights:PortfolioWeights",
    "msm_portfolios.time_index.portfolios:PortfolioValues",
)

PINNED_SIGNAL_PATHS = (
    # Every signal, computed or published: its class path is hashed into its signal_uid.
    "msm_portfolios.contrib.signals.application_weights:ApplicationWeights",
    "msm_portfolios.contrib.signals.external_weights:ExternalWeights",
    "msm_portfolios.contrib.signals.fixed_weights:FixedWeights",
    "msm_portfolios.contrib.signals.intraday_trend:IntradayTrend",
    "msm_portfolios.contrib.signals.market_cap:MarketCap",
    "msm_portfolios.contrib.signals.portfolio_replicator:ETFReplicator",
    "msm_portfolios.time_index.signals.weights:SignalWeights",
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
    # Rotated when FixedWeightsConfig gained signal_time_index (#134).
    "library_fixed_weights": "f7544fc3893593aafb4bb83d29e56f0d",
    "library_application_weights": "18737141b453a2a42ea24500673fdc29",
    "application_signal": "278f13bd9d683932451e5f4087fec5a7",
}

PINNED_PORTFOLIO_CONFIGURATION_HASHES = {
    # Rotated by the next-observed-price fill rule (issue #89, ADR 0058).
    "library_signal_weights": "7bc09bfb4b3c8d0c7b02dbf5980ee435",
    # Rotated again with the FixedWeights signal_uid (#134).
    "library_fixed_weights": "5949c5708874269eee666ff45a7c68a9",
}

PINNED_UPDATE_HASHES = {
    # Rotated in 3.0.0 when the classes moved to msm.time_index and
    # msm_portfolios.contrib.prices.updaters (ADR 0048).
    "asset_snapshot": "assetsnapshot_6eb60d0a440e8ab0b9794f1f5d3e42eb",
    # Rotated in 5.0.0 for the positional configuration this is built with (MetaTables#130).
    "interpolated_prices": "interpolatedprices_c2d1d020889b41e2644db7b8dae0ef0c",
}


PINNED_NESTED_SIGNAL_UIDS = {
    "intraday_trend_on_interpolated_prices": "c94254b4ab5f0cf1a5faa0c0751c6737",
}

PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES = {
    # Rotated by the next-observed-price fill rule (issue #89, ADR 0058). All four
    # rotated again with their bar strategies' execution_policy (#90), and with the
    # FixedWeights signal_uid they hold (#134).
    "interpolated_prices_valuation": "47b0f796d3b52a0bf0839875c5a0882a",
    # Execution windows are datetime.time values, which hash as ISO strings.
    "time_weighted_rebalance": "34ca96b85ea7a2d559b5beb4b05242e4",
    "volume_participation_rebalance": "27141c729e29e26698159da23facc199",
    "trailing_average_daily_volume_rebalance": "26ef20d2d8004c7237f3ed45decb3cde",
}

PINNED_STRATEGY_REVISIONS = {
    # Every revision rotated with the next-observed-price fill rule (issue #89, ADR 0058).
    # The three on interpolated prices rotated again in 5.0.0, with that updater's hash.
    # The four bar strategies rotated again with their execution_policy (#90).
    "immediate_signal": "4bb1737493f36ab0a848c48692c2308f5cd370e997f18e32636af967d80ce409",
    "liquidity_constrained_on_asset_snapshot": (
        "9dd3eb51d6a50fe2440247bc77998a02d5cc660f28ca27900d1ce100db881058"
    ),
    "time_weighted_on_interpolated_prices": (
        "412e686b88ae429af19b286a090dfaefcb91a8f5c01f91b8944398967a34b622"
    ),
    "volume_participation_on_interpolated_prices": (
        "c91e357c91bb54300d007b947d4e06a75221c98cb353e1f0cc53ba92abefc637"
    ),
    "trailing_average_daily_volume_on_asset_snapshot": (
        "5c8ad355978746656c7e3ac74c829a46662cd61f161ee0adb2a431182e00cf2a"
    ),
}

PINNED_CONFIGURED_STORAGE = {
    "index_values_1d": ("ms_markets__index_values__t_1d", "IndexValuesTS.1d"),
    "interpolated_prices_1d_ffill": (
        # Renamed by #95: the source's table name keys it, in its producer's namespace.
        "pinned_app__interpolatedpricests__t_0597b45ae2d0ae00",
        "pinned-app.InterpolatedPricesTS.0597b45ae2d0ae00",
    ),
    "rebalance_state_contract_instance": (
        "pinned_app__portfoliorebalancestatets__pinned_identity",
        "PortfolioRebalanceStateTS.pinned_identity",
    ),
}


class ApplicationSignalConfiguration(PortfolioConfigBaseModel):
    """A signal configuration declared by an application, outside ms-markets."""

    lookback_days: int = Field(20, description="Days of history the signal reads.")


class ApplicationSignal(SignalWeights):
    """A signal declared by an application, outside ms-markets."""


# The application signal's uid hashes its class path in this module; keep it here.
SIGNALS: dict[str, Callable[[], SignalWeights]] = {
    **LIBRARY_SIGNALS,
    "application_signal": lambda: _signal(
        ApplicationSignal,
        ApplicationSignalConfiguration(lookback_days=20),
    ),
}


@contextmanager
def _renamed(cls: type, name: str) -> Iterator[type]:
    """Rename a class in place; type slots cannot be restored by monkeypatch."""

    original = cls.__name__, cls.__qualname__
    cls.__name__ = cls.__qualname__ = name
    try:
        yield cls
    finally:
        cls.__name__, cls.__qualname__ = original


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
            calendar_identifier="XNAS",
        ),
    ),
}


class PinnedRebalanceState(PortfolioRebalanceStateInstance, PinnedBase):
    __instance_key__ = "pinned_identity"
    __metatable_namespace__ = DEFAULT_MARKETS_NAMESPACE
    __markets_storage_app__ = "pinned_app"


CONFIGURED_STORAGE: dict[str, Callable[[], type]] = {
    "index_values_1d": lambda: IndexValues1d,
    "interpolated_prices_1d_ffill": lambda: PinnedInterpolatedPrices,
    "rebalance_state_contract_instance": lambda: PinnedRebalanceState,
}


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


def test_metatable_models_keep_their_physical_table_names() -> None:
    models = metatable_provider_models()

    assert {model.__name__: model.__table__.name for model in models} == PINNED_TABLE_NAMES


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


def test_published_series_node_class_paths_are_pinned() -> None:
    from msm_portfolios.series_nodes import PublishedSeriesNode

    _assert_paths_pinned(
        _defined_subclass_paths(PublishedSeriesNode),
        PINNED_PUBLISHED_NODE_PATHS,
        "published series node",
    )


def test_signal_class_paths_are_pinned() -> None:
    _assert_paths_pinned(
        _defined_subclass_paths(SignalWeightsSource),
        PINNED_SIGNAL_PATHS,
        "signal",
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


@pytest.mark.parametrize("name", sorted(PINNED_UPDATE_HASHES))
def test_metatables_update_hash_is_pinned(updaters, name: str) -> None:
    assert updaters[name].update_hash == PINNED_UPDATE_HASHES[name]


@pytest.mark.parametrize("name", sorted(PINNED_PRE_RENAME_UPDATE_HASHES))
def test_pre_rename_update_hash_is_pinned(updaters, name: str) -> None:
    assert pre_rename_update_hash(updaters[name]) == PINNED_PRE_RENAME_UPDATE_HASHES[name]


@pytest.mark.parametrize("name", sorted(PINNED_NESTED_SIGNAL_UIDS))
def test_signal_uid_with_nested_updaters_is_pinned(updaters, name: str) -> None:
    assert compute_signal_uid(NESTED_SIGNALS[name](updaters)) == PINNED_NESTED_SIGNAL_UIDS[name]


@pytest.mark.parametrize("name", sorted(PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES))
def test_portfolio_configuration_hash_with_nested_updaters_is_pinned(updaters, name: str) -> None:
    configuration = NESTED_PORTFOLIOS[name](updaters)

    assert (
        compute_portfolio_configuration_hash(configuration)
        == PINNED_NESTED_PORTFOLIO_CONFIGURATION_HASHES[name]
    )


@pytest.mark.parametrize("name", sorted(PINNED_STRATEGY_REVISIONS))
def test_rebalance_strategy_revision_is_pinned(updaters, name: str) -> None:
    assert compute_strategy_revision(STRATEGIES[name](updaters)) == PINNED_STRATEGY_REVISIONS[name]


@pytest.mark.parametrize("name", sorted(PINNED_CONFIGURED_STORAGE))
def test_configured_storage_keeps_its_table_name_and_identifier(name: str) -> None:
    storage = CONFIGURED_STORAGE[name]()

    assert (
        storage.__table__.name,
        storage.__metatable_identifier__,
    ) == PINNED_CONFIGURED_STORAGE[name]


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
