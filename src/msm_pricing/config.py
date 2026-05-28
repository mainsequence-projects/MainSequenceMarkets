from __future__ import annotations

from collections.abc import Mapping
from threading import RLock
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from msm_pricing.settings import PRICING_CONTEXT_DEFAULT


class PricingMarketDataConfiguration(BaseModel):
    """Runtime pricing context and direct DataNode identifier overrides."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    context_key: str = Field(
        default=PRICING_CONTEXT_DEFAULT,
        min_length=1,
        max_length=64,
        description="Pricing market-data context key, for example default, eod, or live.",
    )
    data_node_identifiers: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Direct per-concept DataNode identifier overrides. Keys are pricing "
            "concept keys such as discount_curves or interest_rate_index_fixings."
        ),
    )

    @field_validator("context_key")
    @classmethod
    def _validate_context_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("context_key cannot be empty.")
        return normalized

    @field_validator("data_node_identifiers")
    @classmethod
    def _validate_data_node_identifiers(cls, value: dict[str, str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for concept_key, identifier in value.items():
            normalized_concept = str(concept_key).strip()
            normalized_identifier = str(identifier).strip()
            if not normalized_concept:
                raise ValueError("data_node_identifiers cannot contain empty concept keys.")
            if not normalized_identifier:
                raise ValueError("data_node_identifiers cannot contain empty identifiers.")
            normalized[normalized_concept] = normalized_identifier
        return normalized

    def direct_identifier_for(self, concept_key: str) -> str | None:
        """Return a direct configured DataNode identifier for one concept."""

        return self.data_node_identifiers.get(concept_key)


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
    """Install a process-wide pricing market-data configuration.

    Passing ``None`` resets the process to the canonical package defaults.
    """

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
