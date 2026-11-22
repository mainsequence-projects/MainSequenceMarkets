"""The equal-weight example's configuration, and the one table it owns.

The example is a producer: it declares its interpolated-price table on its own base, in its
own namespace, and migrates it with its own provider (`portfolio_equal_weights_migrations`).
The table's key comes from the configuration alone, so the committed revision creates it in
every Environment.
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
from msm.storage_instances import configured_time_index_instance  # noqa: E402
from msm_portfolios.time_index.prices.storage import (  # noqa: E402
    ExternalPricesStorage,
    InterpolatedPricesStorage,
    interpolated_prices_instance_key,
)

NAMESPACE = "mainsequence.examples.portfolios"
PORTFOLIO_UNIQUE_IDENTIFIER = "example-equal-weight-portfolio"
CRYPTO_CALENDAR_UNIQUE_IDENTIFIER = "CRYPTO_24_7"
TIME_INDEX = pd.Timestamp("2026-05-25T00:00:00Z")
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


# Another source, cadence, upsample frequency or rule is another table, and another revision.
INTERPOLATED_PRICES_STORAGE = configured_time_index_instance(
    InterpolatedPricesStorage,
    instance_key=interpolated_prices_instance_key(
        source_table_name=ExternalPricesStorage.__table__.name,
        source_cadence=SOURCE_PRICE_CADENCE,
        upsample_frequency_id=PRICE_UPSAMPLE_FREQUENCY_ID,
        intraday_bar_interpolation_rule=PRICE_INTERPOLATION_RULE,
    ),
    cadence=PRICE_UPSAMPLE_FREQUENCY_ID,
    namespace=PROVIDER_NAMESPACE,
    storage_app=PROVIDER_STORAGE_APP,
    base=ProviderBase,
)

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
    "PortfolioWeightsStorage",
    "SignalWeightsStorage",
    "PortfoliosStorage",
]


__all__ = [
    "ASSET_UNIQUE_IDENTIFIERS",
    "CRYPTO_CALENDAR_UNIQUE_IDENTIFIER",
    "INTERPOLATED_PRICES_STORAGE",
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
    "SOURCE_PRICE_CADENCE",
    "TIME_INDEX",
]
