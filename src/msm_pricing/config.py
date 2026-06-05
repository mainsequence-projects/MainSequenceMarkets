from __future__ import annotations

import uuid
from collections.abc import Mapping
from threading import RLock
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from msm_pricing.settings import PRICING_MARKET_DATA_SET_DEFAULT


class PricingMarketDataConfiguration(BaseModel):
    """Runtime default market-data set and direct storage UID overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    market_data_set: str | uuid.UUID = Field(
        default=PRICING_MARKET_DATA_SET_DEFAULT,
        description=(
            "Default pricing market-data set selector used when a pricing call does "
            "not pass market_data_set explicitly."
        ),
    )
    data_node_uids: dict[str, uuid.UUID] = Field(
        default_factory=dict,
        description=(
            "Direct per-concept storage table UID overrides. Keys are pricing concept "
            "keys such as discount_curves or interest_rate_index_fixings."
        ),
    )

    @field_validator("market_data_set")
    @classmethod
    def _validate_market_data_set(cls, value: str | uuid.UUID) -> str | uuid.UUID:
        if isinstance(value, uuid.UUID):
            return value
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("market_data_set cannot be empty.")
        return normalized

    @field_validator("data_node_uids")
    @classmethod
    def _validate_data_node_uids(cls, value: dict[str, uuid.UUID]) -> dict[str, uuid.UUID]:
        normalized: dict[str, uuid.UUID] = {}
        for concept_key, data_node_uid in value.items():
            normalized_concept = str(concept_key).strip()
            if not normalized_concept:
                raise ValueError("data_node_uids cannot contain empty concept keys.")
            normalized[normalized_concept] = (
                data_node_uid
                if isinstance(data_node_uid, uuid.UUID)
                else uuid.UUID(str(data_node_uid))
            )
        return normalized

    def direct_data_node_uid_for(self, concept_key: str) -> uuid.UUID | None:
        """Return a directly configured storage table UID for one concept."""

        return self.data_node_uids.get(concept_key)


PricingMarketDataConfigurationInput: TypeAlias = PricingMarketDataConfiguration | Mapping[str, Any]

_CONFIGURATION_LOCK = RLock()
_PRICING_MARKET_DATA_CONFIGURATION: PricingMarketDataConfiguration | None = None


def default_pricing_market_data_configuration() -> PricingMarketDataConfiguration:
    """Return a new default pricing market-data configuration."""

    return PricingMarketDataConfiguration()


def get_pricing_market_data_configuration() -> PricingMarketDataConfiguration:
    """Return the active pricing market-data configuration."""

    with _CONFIGURATION_LOCK:
        if _PRICING_MARKET_DATA_CONFIGURATION is not None:
            return _PRICING_MARKET_DATA_CONFIGURATION
    return default_pricing_market_data_configuration()


def set_pricing_market_data_configuration(
    configuration: PricingMarketDataConfigurationInput | None = None,
) -> PricingMarketDataConfiguration:
    """Install a process-wide default pricing market-data configuration."""

    resolved_configuration = (
        default_pricing_market_data_configuration()
        if configuration is None
        else _coerce_pricing_market_data_configuration(configuration)
    )
    global _PRICING_MARKET_DATA_CONFIGURATION
    with _CONFIGURATION_LOCK:
        _PRICING_MARKET_DATA_CONFIGURATION = resolved_configuration
    return resolved_configuration


def reset_pricing_market_data_configuration() -> PricingMarketDataConfiguration:
    """Clear overrides and return the canonical default configuration."""

    global _PRICING_MARKET_DATA_CONFIGURATION
    with _CONFIGURATION_LOCK:
        _PRICING_MARKET_DATA_CONFIGURATION = None
    return default_pricing_market_data_configuration()


def _coerce_pricing_market_data_configuration(
    configuration: PricingMarketDataConfigurationInput,
) -> PricingMarketDataConfiguration:
    if isinstance(configuration, PricingMarketDataConfiguration):
        return configuration
    return PricingMarketDataConfiguration.model_validate(dict(configuration))


__all__ = [
    "PricingMarketDataConfiguration",
    "PricingMarketDataConfigurationInput",
    "default_pricing_market_data_configuration",
    "get_pricing_market_data_configuration",
    "reset_pricing_market_data_configuration",
    "set_pricing_market_data_configuration",
]
