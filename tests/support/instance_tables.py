"""Instance tables declared with class statements, one per contract (ADR 0066).

Each class has the settings an instance factory was called with before ADR 0066
removed the factories. ``tests/identity/factory_tables.json`` holds what those
factories built at 48dda3dc: table names, identifiers, DDL and registration
requests. ``tests/identity/test_instance_tables.py`` checks that these classes build
the same tables, and that each one imports back by its ``module:qualname``.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm.settings import DEFAULT_MARKETS_NAMESPACE
from msm.time_index.accounts.storage import AccountHoldingsInstance, TargetPositionsInstance
from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsInstance
from msm.time_index.assets.storage import AssetSnapshotsStorage
from msm.time_index.execution.storage import OrderEventsInstance, OrdersInstance, TradesInstance
from msm.time_index.indices.storage import IndexValuesInstance
from msm_portfolios.time_index.contract_instances import (
    PortfolioCalendarEventsInstance,
    PortfolioEventLedgerInstance,
    PortfolioRebalanceStateInstance,
)
from msm_portfolios.time_index.prices.storage import (
    ExternalPricesInstance,
    ExternalPricesStorage,
    InterpolatedPricesInstance,
    interpolated_prices_instance_key,
)
from msm_portfolios.time_index.signals.storage import SignalWeightsInstance
from msm_pricing.time_index.curves.storage import DiscountCurvesInstance
from msm_pricing.time_index.index_fixings.storage import IndexFixingsInstance
from msm_pricing.time_index.pricing_details.storage import AssetPricingDetailsInstance


class PinnedOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class ExampleOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class ProviderOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class CurvesOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class AppOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class CadenceOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class IndexOwnerBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class PinnedOwner:
    __metatable_namespace__ = "pinned-app"
    __markets_storage_app__ = "pinned_app"


class EqualWeightsExampleOwner:
    __metatable_namespace__ = "equal-weight-example"
    __markets_storage_app__ = "equal_weight_example"


class Provider:
    __metatable_namespace__ = "my-provider"
    __markets_storage_app__ = "my_provider"


class App:
    __metatable_namespace__ = "my-app"
    __markets_storage_app__ = "my_app"


class IndexProvider:
    __metatable_namespace__ = "index-values-example"
    __markets_storage_app__ = "index_values_example"


class PinnedInterpolatedPrices(InterpolatedPricesInstance, PinnedOwner, PinnedOwnerBase):
    __instance_key__ = interpolated_prices_instance_key(
        source_table_name=AssetSnapshotsStorage.__table__.name,
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    __cadence__ = "1d"


class PinnedRebalanceState(PortfolioRebalanceStateInstance, PinnedOwnerBase):
    __instance_key__ = "pinned_identity"
    __metatable_namespace__ = DEFAULT_MARKETS_NAMESPACE
    __markets_storage_app__ = "pinned_app"


class EqualWeightsInterpolatedPrices(
    InterpolatedPricesInstance, EqualWeightsExampleOwner, ExampleOwnerBase
):
    __instance_key__ = interpolated_prices_instance_key(
        source_table_name=ExternalPricesStorage.__table__.name,
        source_cadence=ExternalPricesStorage.__cadence__,
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    __cadence__ = "1d"


class EqualWeightsSignalWeights(SignalWeightsInstance, EqualWeightsExampleOwner, ExampleOwnerBase):
    __instance_key__ = "signals"


class ProviderDiscountCurves(DiscountCurvesInstance, Provider, ProviderOwnerBase):
    __instance_key__ = "main"


class ProviderIndexFixings(IndexFixingsInstance, Provider, ProviderOwnerBase):
    __instance_key__ = "main"


class ProviderAssetPricingDetails(AssetPricingDetailsInstance, Provider, ProviderOwnerBase):
    __instance_key__ = "main"


class ExampleProviderDiscountCurves(DiscountCurvesInstance, CurvesOwnerBase):
    __instance_key__ = "main"
    __metatable_namespace__ = "example-provider"
    __markets_storage_app__ = "example_provider"


class AppOrders(OrdersInstance, App, AppOwnerBase):
    __instance_key__ = "main"


class AppOrderEvents(OrderEventsInstance, App, AppOwnerBase):
    __instance_key__ = "main"


class AppTrades(TradesInstance, App, AppOwnerBase):
    __instance_key__ = "main"


class KeptExternalPrices(ExternalPricesInstance, CadenceOwnerBase):
    __instance_key__ = "kept"
    __metatable_namespace__ = "ns-cadence"
    __markets_storage_app__ = "ns_cadence"


class ProviderRebalanceState(PortfolioRebalanceStateInstance, Provider, ProviderOwnerBase):
    __instance_key__ = "main"


class ProviderCalendarEvents(PortfolioCalendarEventsInstance, Provider, ProviderOwnerBase):
    __instance_key__ = "main"


class ProviderEventLedger(PortfolioEventLedgerInstance, Provider, ProviderOwnerBase):
    __instance_key__ = "main"


class ProviderOneMinuteIndexValues(IndexValuesInstance, IndexProvider, IndexOwnerBase):
    __cadence__ = "1m"


class ProviderDailyIndexValues(IndexValuesInstance, IndexProvider, IndexOwnerBase):
    __cadence__ = "1d"


class MyProviderDailyIndexValues(IndexValuesInstance, Provider, ProviderOwnerBase):
    __cadence__ = "1d"



class AppAccountHoldings(AccountHoldingsInstance, App, AppOwnerBase):
    __instance_key__ = "main"


class AppTargetPositions(TargetPositionsInstance, App, AppOwnerBase):
    __instance_key__ = "main"


class AppVirtualFundHoldings(VirtualFundHoldingsInstance, App, AppOwnerBase):
    __instance_key__ = "main"

DECLARED_TABLES: dict[str, type] = {
    "interpolated_prices_pinned": PinnedInterpolatedPrices,
    "interpolated_prices_equal_weights_example": EqualWeightsInterpolatedPrices,
    "signal_weights_equal_weights_example": EqualWeightsSignalWeights,
    "discount_curves": ProviderDiscountCurves,
    "index_fixings": ProviderIndexFixings,
    "asset_pricing_details": ProviderAssetPricingDetails,
    "discount_curves_example_provider": ExampleProviderDiscountCurves,
    "orders": AppOrders,
    "order_events": AppOrderEvents,
    "trades": AppTrades,
    "external_prices": KeptExternalPrices,
    "portfolio_rebalance_state": ProviderRebalanceState,
    "portfolio_calendar_events": ProviderCalendarEvents,
    "portfolio_event_ledger": ProviderEventLedger,
    "portfolio_rebalance_state_pinned": PinnedRebalanceState,
    "provider_index_values_1m": ProviderOneMinuteIndexValues,
    "provider_index_values_1d": ProviderDailyIndexValues,
    "my_provider_index_values_1d": MyProviderDailyIndexValues,
    "account_holdings": AppAccountHoldings,
    "target_positions": AppTargetPositions,
    "virtual_fund_holdings": AppVirtualFundHoldings,
}
"""Each class by the name of its factory-built table in ``factory_tables.json``."""
