from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import MetaData

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import (  # noqa: E402
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

from mainsequence.meta_tables import sqlalchemy_naming_convention  # noqa: E402

from examples.msm.assets.utils import EXAMPLE_CRYPTO_ASSETS  # noqa: E402
from msm_portfolios.data_nodes.storage import (  # noqa: E402
    ExternalPricesStorage,
    configured_interpolated_prices_storage,
)

NAMESPACE = "mainsequence.examples.portfolios"
INDEX_TYPE_PORTFOLIO = "portfolio"
PORTFOLIO_UNIQUE_IDENTIFIER = "example-equal-weight-portfolio"
PORTFOLIO_INDEX_UNIQUE_IDENTIFIER = "example-equal-weight-portfolio-index"
PORTFOLIO_INDEX_DISPLAY_NAME = "Example Equal Weight Portfolio Index"
CRYPTO_CALENDAR_UNIQUE_IDENTIFIER = "CRYPTO_24_7"
TIME_INDEX = pd.Timestamp("2026-05-25T00:00:00Z")
ASSET_UNIQUE_IDENTIFIERS = [payload["unique_identifier"] for payload in EXAMPLE_CRYPTO_ASSETS]
ACCOUNT_GROUP_NAME = "Example Portfolio Allocation Accounts"
ACCOUNT_UNIQUE_IDENTIFIER = "example-portfolio-allocation-account"
VIRTUAL_FUND_UNIQUE_IDENTIFIER = "example-equal-weight-virtual-fund"
SOURCE_PRICE_CADENCE = ExternalPricesStorage.__cadence__
PRICE_UPSAMPLE_FREQUENCY_ID = "1d"
PRICE_INTERPOLATION_RULE = "ffill"

DYNAMIC_SOURCE_STORAGE_HASH_ENV = "MSM_EXAMPLE_PORTFOLIO_SOURCE_STORAGE_HASH"
DYNAMIC_SOURCE_CADENCE_ENV = "MSM_EXAMPLE_PORTFOLIO_SOURCE_CADENCE"
DYNAMIC_UPSAMPLE_FREQUENCY_ENV = "MSM_EXAMPLE_PORTFOLIO_UPSAMPLE_FREQUENCY"
DYNAMIC_INTERPOLATION_RULE_ENV = "MSM_EXAMPLE_PORTFOLIO_INTERPOLATION_RULE"
DYNAMIC_MIGRATION_PROVIDER = (
    "examples.msm_portfolios.portfolio_equal_weights_dynamic_migration:migration"
)

PORTFOLIO_EXAMPLE_RUNTIME_MODELS = [
    "IndexType",
    "Index",
    "AssetType",
    "Asset",
    "AccountGroup",
    "Account",
    "AccountHoldingsSet",
    "AccountHoldingsStorage",
    "Calendar",
    "CalendarDate",
    "CalendarSession",
    "Portfolio",
    "VirtualFund",
    "VirtualFundHoldingsSet",
    "VirtualFundHoldingsStorage",
    "SignalMetadata",
    "RebalanceStrategyMetadata",
    "ExternalPricesStorage",
    "PortfolioWeightsStorage",
    "SignalWeightsStorage",
    "PortfoliosStorage",
]


def configured_equal_weight_interpolated_prices_storage(
    *,
    source_storage_hash: str,
    source_cadence: str,
) -> type[Any]:
    """Return the configured interpolation storage class for this example policy."""

    return configured_interpolated_prices_storage(
        source_storage_hash=source_storage_hash,
        source_cadence=source_cadence,
        upsample_frequency_id=PRICE_UPSAMPLE_FREQUENCY_ID,
        intraday_bar_interpolation_rule=PRICE_INTERPOLATION_RULE,
    )


def source_storage_hash_from_meta_table(source_meta_table: Any) -> str:
    """Return the backend storage hash for a registered source price storage table."""

    storage_hash = getattr(source_meta_table, "storage_hash", None)
    if storage_hash in (None, ""):
        raise RuntimeError(
            "Registered source price storage is missing storage_hash; cannot derive "
            "the configured interpolated price storage table. Attach the registered "
            "ExternalPricesStorage TimeIndexMetaTable first."
        )
    return str(storage_hash)


def source_cadence_from_meta_table(
    source_meta_table: Any,
) -> str:
    """Return declared cadence from registered source storage metadata."""

    profile = getattr(source_meta_table, "time_indexed_profile", None)
    cadence: Any = None
    if isinstance(profile, Mapping):
        cadence = profile.get("cadence")
    elif profile is not None:
        cadence = getattr(profile, "cadence", None)

    if cadence not in (None, ""):
        return str(cadence).strip().lower()

    cadence = getattr(source_meta_table, "cadence", None)
    if cadence not in (None, ""):
        return str(cadence).strip().lower()

    contract = getattr(source_meta_table, "table_contract", None)
    if isinstance(contract, Mapping):
        authoring = contract.get("authoring")
        if isinstance(authoring, Mapping):
            time_indexed = authoring.get("time_indexed")
            if isinstance(time_indexed, Mapping):
                cadence = time_indexed.get("cadence")
                if cadence not in (None, ""):
                    return str(cadence).strip().lower()

    raise RuntimeError(
        "Registered source price storage is missing backend cadence metadata; "
        "cannot derive the configured interpolated price storage table. "
        f"meta_table_uid={getattr(source_meta_table, 'uid', None)}, "
        f"physical_table_name={getattr(source_meta_table, 'physical_table_name', None)}, "
        f"storage_hash={getattr(source_meta_table, 'storage_hash', None)}."
    )


def repair_source_cadence_metadata(
    source_meta_table: Any,
    *,
    expected_cadence: str,
) -> tuple[Any, str, bool]:
    """Ensure the registered source TimeIndexMetaTable declares cadence metadata."""

    try:
        return source_meta_table, source_cadence_from_meta_table(source_meta_table), False
    except RuntimeError as missing_error:
        patch = getattr(source_meta_table, "patch", None)
        if not callable(patch):
            raise missing_error

    patched = patch(cadence=expected_cadence)
    try:
        return patched, source_cadence_from_meta_table(patched), True
    except RuntimeError as patched_error:
        raise RuntimeError(
            "Registered source price storage cadence repair was attempted, but "
            "the backend response still does not expose cadence metadata."
        ) from patched_error


def dynamic_provider_env(
    *,
    source_storage_hash: str,
    source_cadence: str,
) -> dict[str, str]:
    """Return the environment needed by the dynamic migration provider."""

    return {
        EXAMPLE_NAMESPACE_ENV: EXAMPLE_METATABLE_NAMESPACE,
        DYNAMIC_SOURCE_STORAGE_HASH_ENV: source_storage_hash,
        DYNAMIC_SOURCE_CADENCE_ENV: source_cadence,
        DYNAMIC_UPSAMPLE_FREQUENCY_ENV: PRICE_UPSAMPLE_FREQUENCY_ID,
        DYNAMIC_INTERPOLATION_RULE_ENV: PRICE_INTERPOLATION_RULE,
    }


def dynamic_storage_from_env() -> type[Any]:
    """Build the configured interpolation storage class for the migration provider."""

    source_storage_hash = os.environ.get(DYNAMIC_SOURCE_STORAGE_HASH_ENV)
    source_cadence = os.environ.get(DYNAMIC_SOURCE_CADENCE_ENV)
    if source_storage_hash in (None, "") or source_cadence in (None, ""):
        raise RuntimeError(
            "Dynamic portfolio migration provider requires "
            f"{DYNAMIC_SOURCE_STORAGE_HASH_ENV} and {DYNAMIC_SOURCE_CADENCE_ENV}. "
            "Run examples/msm_portfolios/portfolio_equal_weights_prepare_schema.py "
            "instead of invoking the provider directly."
        )

    return configured_interpolated_prices_storage(
        source_storage_hash=str(source_storage_hash),
        source_cadence=str(source_cadence),
        upsample_frequency_id=os.environ.get(
            DYNAMIC_UPSAMPLE_FREQUENCY_ENV,
            PRICE_UPSAMPLE_FREQUENCY_ID,
        ),
        intraday_bar_interpolation_rule=os.environ.get(
            DYNAMIC_INTERPOLATION_RULE_ENV,
            PRICE_INTERPOLATION_RULE,
        ),
    )


def metadata_for_storage_model(storage_model: type[Any]) -> MetaData:
    """Return isolated SQLAlchemy metadata containing only the configured table."""

    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())
    storage_model.__table__.to_metadata(metadata)
    return metadata


__all__ = [
    "ACCOUNT_GROUP_NAME",
    "ACCOUNT_UNIQUE_IDENTIFIER",
    "ASSET_UNIQUE_IDENTIFIERS",
    "CRYPTO_CALENDAR_UNIQUE_IDENTIFIER",
    "DYNAMIC_INTERPOLATION_RULE_ENV",
    "DYNAMIC_MIGRATION_PROVIDER",
    "DYNAMIC_SOURCE_CADENCE_ENV",
    "DYNAMIC_SOURCE_STORAGE_HASH_ENV",
    "DYNAMIC_UPSAMPLE_FREQUENCY_ENV",
    "INDEX_TYPE_PORTFOLIO",
    "NAMESPACE",
    "PORTFOLIO_EXAMPLE_RUNTIME_MODELS",
    "PORTFOLIO_INDEX_DISPLAY_NAME",
    "PORTFOLIO_INDEX_UNIQUE_IDENTIFIER",
    "PORTFOLIO_UNIQUE_IDENTIFIER",
    "PRICE_INTERPOLATION_RULE",
    "PRICE_UPSAMPLE_FREQUENCY_ID",
    "SOURCE_PRICE_CADENCE",
    "TIME_INDEX",
    "VIRTUAL_FUND_UNIQUE_IDENTIFIER",
    "configured_equal_weight_interpolated_prices_storage",
    "dynamic_provider_env",
    "dynamic_storage_from_env",
    "metadata_for_storage_model",
    "repair_source_cadence_metadata",
    "source_cadence_from_meta_table",
    "source_storage_hash_from_meta_table",
]
