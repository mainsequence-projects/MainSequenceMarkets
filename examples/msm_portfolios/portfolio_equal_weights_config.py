"""The equal-weight example's configuration, and the two tables it owns.

The example is a producer: it declares its interpolated-price table and its signal table
with class statements on its own base, in its own namespace, and migrates them with its own
provider (`portfolio_equal_weights_migrations`), which lists the two classes. Each table's
key comes from the configuration alone, so the committed revisions create them in every
Environment. A node Job run imports each class by its address, such as
`examples.msm_portfolios.portfolio_equal_weights_config:EqualWeightInterpolatedPrices`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.assets.utils import EXAMPLE_CRYPTO_ASSETS  # noqa: E402
from metatables import sqlalchemy_naming_convention  # noqa: E402
from msm_portfolios.time_index.prices.storage import (  # noqa: E402
    ExternalPricesStorage,
    InterpolatedPricesInstance,
    interpolated_prices_instance_key,
)
from msm_portfolios.time_index.signals.storage import SignalWeightsInstance  # noqa: E402

NAMESPACE = "mainsequence.examples.portfolios"
PORTFOLIO_UNIQUE_IDENTIFIER = "example-equal-weight-portfolio"
CRYPTO_CALENDAR_UNIQUE_IDENTIFIER = "CRYPTO_24_7"
TIME_INDEX = pd.Timestamp("2026-05-25T00:00:00Z")
# The source bars close daily from 2026-05-23. The weights are stated after the first close,
# so the rebalance sizes them with that close and fills them at the next one (ADR 0058).
SIGNAL_TIME_INDEX = pd.Timestamp("2026-05-23T12:00:00Z")
ASSET_UNIQUE_IDENTIFIERS = [payload["unique_identifier"] for payload in EXAMPLE_CRYPTO_ASSETS]
SOURCE_PRICE_CADENCE = ExternalPricesStorage.__cadence__
PRICE_UPSAMPLE_FREQUENCY_ID = "1d"
PRICE_INTERPOLATION_RULE = "ffill"

PROVIDER_NAMESPACE = "equal-weight-example"
PROVIDER_STORAGE_APP = "equal_weight_example"
MIGRATION_PROVIDER = "examples.msm_portfolios.portfolio_equal_weights_migrations:migration"
MIGRATION_COMMAND = f"metatables --local migrations upgrade --provider {MIGRATION_PROVIDER} head"


class ProviderBase(DeclarativeBase):
    """The example's own base: its migration provider targets this metadata."""

    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class EqualWeightInterpolatedPrices(InterpolatedPricesInstance, ProviderBase):
    """The interpolated prices of the example's configuration.

    Another source, cadence, upsample frequency or rule is another table: another class,
    and another revision.
    """

    __instance_key__ = interpolated_prices_instance_key(
        source_table_name=ExternalPricesStorage.__table__.name,
        source_cadence=SOURCE_PRICE_CADENCE,
        upsample_frequency_id=PRICE_UPSAMPLE_FREQUENCY_ID,
        intraday_bar_interpolation_rule=PRICE_INTERPOLATION_RULE,
    )
    __metatable_namespace__ = PROVIDER_NAMESPACE
    __markets_storage_app__ = PROVIDER_STORAGE_APP
    __cadence__ = PRICE_UPSAMPLE_FREQUENCY_ID


class EqualWeightSignalWeights(SignalWeightsInstance, ProviderBase):
    """The computed signal's own table.

    FixedWeights writes its rows here and publishes the same rows to Markets'
    SignalWeightsTS. Every signal the example computes shares it.
    """

    __instance_key__ = "signals"
    __metatable_namespace__ = PROVIDER_NAMESPACE
    __markets_storage_app__ = PROVIDER_STORAGE_APP

PORTFOLIO_EXAMPLE_RUNTIME_MODELS = [
    "AssetType",
    "Asset",
    "Calendar",
    "CalendarSessionRule",
    "CalendarException",
    "AssetCalendar",
    "IndexType",
    "Portfolio",
    "SignalMetadata",
    "RebalanceStrategyMetadata",
    "ExternalPricesStorage",
    "PortfolioCalendarEventsStorage",
    "PortfolioRebalanceStateStorage",
    "PortfolioEventLedgerStorage",
    "PortfolioWeightsStorage",
    "SignalWeightsStorage",
    "PortfoliosStorage",
]


__all__ = [
    "ASSET_UNIQUE_IDENTIFIERS",
    "CRYPTO_CALENDAR_UNIQUE_IDENTIFIER",
    "EqualWeightInterpolatedPrices",
    "EqualWeightSignalWeights",
    "MIGRATION_COMMAND",
    "MIGRATION_PROVIDER",
    "NAMESPACE",
    "PORTFOLIO_EXAMPLE_RUNTIME_MODELS",
    "PORTFOLIO_UNIQUE_IDENTIFIER",
    "PRICE_INTERPOLATION_RULE",
    "PRICE_UPSAMPLE_FREQUENCY_ID",
    "PROVIDER_NAMESPACE",
    "PROVIDER_STORAGE_APP",
    "ProviderBase",
    "SIGNAL_TIME_INDEX",
    "SOURCE_PRICE_CADENCE",
    "TIME_INDEX",
]
