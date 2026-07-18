from __future__ import annotations

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ImplementationT = TypeVar("ImplementationT")


def normalize_code(value: str) -> str:
    code = str(value).strip().lower().replace("/", "_per_").replace(" ", "_")
    while "__" in code:
        code = code.replace("__", "_")
    if not code:
        raise ValueError("registry code cannot be empty")
    return code


class NoParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AsOfParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_staleness_seconds: float = Field(gt=0)


class ForwardFillParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_age_seconds: float = Field(gt=0)


class RebaseParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_value: float = Field(default=100.0, gt=0)


class RollingCoefficientParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    window: int = Field(default=60, gt=1)
    min_observations: int = Field(default=30, gt=1)
    lag: int = Field(default=1, ge=1)
    include_intercept: bool = True
    lower_bound: float | None = None
    upper_bound: float | None = None
    sign: float = -1.0
    observable_code: str | None = None
    fallback_policy: Literal["drop", "fail"] = "drop"

    @model_validator(mode="after")
    def _validate_window_and_bounds(self) -> RollingCoefficientParameters:
        if self.min_observations > self.window:
            raise ValueError("min_observations cannot exceed window")
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("lower_bound cannot exceed upper_bound")
        return self


class LaggedCoefficientParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lag: int = Field(default=1, ge=0)
    lower_bound: float | None = None
    upper_bound: float | None = None
    sign: float = -1.0
    observable_code: str | None = None
    reference_observable_code: str | None = None
    fallback_policy: Literal["drop", "fail"] = "drop"

    @model_validator(mode="after")
    def _validate_bounds(self) -> LaggedCoefficientParameters:
        if (
            self.lower_bound is not None
            and self.upper_bound is not None
            and self.lower_bound > self.upper_bound
        ):
            raise ValueError("lower_bound cannot exceed upper_bound")
        return self


class SelfFinancingParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_value: float = Field(default=100.0, gt=0)
    initial_capital: float = Field(default=100.0, gt=0)
    financing_rate: float = 0.0
    periods_per_year: float = Field(default=252.0, gt=0)
    transaction_cost_bps: float = Field(default=0.0, ge=0)
    position_lag: int = Field(default=1, ge=1)


class ChainedReturnParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_value: float = Field(default=100.0, gt=0)


class NearestTenorParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_tenor_years: float = Field(gt=0)
    tenor_column: str = "tenor_years"
    component_column: str = "component_key"
    liquidity_column: str | None = None


class FuturesRankParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank: int = Field(ge=1)
    rank_column: str = "rank"
    component_column: str = "component_key"


class ScheduleParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "UTC"


class EventRebalanceParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_times: tuple[datetime.datetime, ...] = Field(min_length=1)

    @field_validator("event_times")
    @classmethod
    def _require_timezone_aware_events(
        cls,
        values: tuple[datetime.datetime, ...],
    ) -> tuple[datetime.datetime, ...]:
        normalized: list[datetime.datetime] = []
        for value in values:
            timestamp = pd.Timestamp(value)
            if timestamp.tzinfo is None:
                raise ValueError("event rebalance timestamps must be timezone-aware")
            normalized.append(timestamp.tz_convert("UTC").to_pydatetime())
        return tuple(sorted(set(normalized)))


@dataclass(frozen=True)
class RegistryEntry(Generic[ImplementationT]):
    implementation: ImplementationT
    parameters_model: type[BaseModel]


class TypedRegistry(Generic[ImplementationT]):
    """Extensible named implementation registry with strict parameter validation."""

    def __init__(self, label: str):
        self.label = label
        self._entries: dict[str, RegistryEntry[ImplementationT]] = {}

    def register(
        self,
        code: str,
        implementation: ImplementationT,
        *,
        parameters_model: type[BaseModel] = NoParameters,
        replace: bool = False,
    ) -> None:
        key = normalize_code(code)
        if key in self._entries and not replace:
            raise ValueError(f"{self.label} {key!r} is already registered")
        self._entries[key] = RegistryEntry(
            implementation=implementation,
            parameters_model=parameters_model,
        )

    def get(self, code: str) -> ImplementationT:
        key = normalize_code(code)
        try:
            return self._entries[key].implementation
        except KeyError as exc:
            raise ValueError(f"unknown {self.label} {key!r}") from exc

    def validate_parameters(self, code: str, parameters: dict[str, Any] | None) -> BaseModel:
        key = normalize_code(code)
        try:
            model = self._entries[key].parameters_model
        except KeyError as exc:
            raise ValueError(f"unknown {self.label} {key!r}") from exc
        return model.model_validate(parameters or {})

    def codes(self) -> tuple[str, ...]:
        return tuple(self._entries)


@dataclass(frozen=True)
class UnitDefinition:
    dimension: str


class UnitRegistry:
    """Strict unit registry supporting compatible identity and explicit factor conversions."""

    def __init__(self) -> None:
        self._units: dict[str, UnitDefinition] = {}
        self._factors: dict[tuple[str, str], float] = {}

    def register_unit(self, code: str, *, dimension: str) -> None:
        key = normalize_code(code)
        definition = UnitDefinition(dimension=normalize_code(dimension))
        existing = self._units.get(key)
        if existing is not None and existing != definition:
            raise ValueError(f"unit {key!r} is already registered with another dimension")
        self._units[key] = definition
        self._factors[(key, key)] = 1.0

    def register_conversion(
        self,
        source: str,
        target: str,
        *,
        factor: float,
        bidirectional: bool = True,
    ) -> None:
        source_key = normalize_code(source)
        target_key = normalize_code(target)
        if source_key not in self._units or target_key not in self._units:
            raise ValueError("register both units before registering a conversion")
        if self._units[source_key].dimension != self._units[target_key].dimension:
            raise ValueError("unit conversions require matching dimensions")
        if factor == 0:
            raise ValueError("unit conversion factor cannot be zero")
        self._factors[(source_key, target_key)] = float(factor)
        if bidirectional:
            self._factors[(target_key, source_key)] = 1.0 / float(factor)

    def dimension(self, code: str) -> str:
        key = normalize_code(code)
        try:
            return self._units[key].dimension
        except KeyError as exc:
            raise ValueError(f"unknown unit {key!r}") from exc

    def ensure_compatible(self, source: str, target: str) -> None:
        if self.dimension(source) != self.dimension(target):
            raise ValueError(f"incompatible units: {source!r} and {target!r}")

    def convert(self, values: pd.Series, source: str, target: str) -> pd.Series:
        source_key = normalize_code(source)
        target_key = normalize_code(target)
        self.ensure_compatible(source_key, target_key)
        try:
            factor = self._factors[(source_key, target_key)]
        except KeyError as exc:
            raise ValueError(
                f"no registered conversion from {source_key!r} to {target_key!r}"
            ) from exc
        return values.astype(float) * factor


CalculationFunction = Callable[..., pd.Series]
TransformFunction = Callable[..., pd.Series]
SelectorFunction = Callable[..., pd.DataFrame]
CoefficientFunction = Callable[..., pd.Series]

CALCULATION_REGISTRY: TypedRegistry[CalculationFunction] = TypedRegistry("calculation kind")
TRANSFORM_REGISTRY: TypedRegistry[TransformFunction] = TypedRegistry("transform")
SELECTOR_REGISTRY: TypedRegistry[SelectorFunction] = TypedRegistry("selector")
COEFFICIENT_REGISTRY: TypedRegistry[CoefficientFunction] = TypedRegistry("coefficient method")
ALIGNMENT_REGISTRY: TypedRegistry[str] = TypedRegistry("alignment policy")
MISSING_DATA_REGISTRY: TypedRegistry[str] = TypedRegistry("missing-data policy")
REBALANCE_REGISTRY: TypedRegistry[str] = TypedRegistry("rebalance policy")
UNIT_REGISTRY = UnitRegistry()


def _register_builtin_units() -> None:
    for code in ("decimal", "percent", "basis_points"):
        UNIT_REGISTRY.register_unit(code, dimension="rate")
    UNIT_REGISTRY.register_conversion("decimal", "percent", factor=100.0)
    UNIT_REGISTRY.register_conversion("decimal", "basis_points", factor=10_000.0)
    UNIT_REGISTRY.register_conversion("percent", "basis_points", factor=100.0)

    UNIT_REGISTRY.register_unit("ratio", dimension="ratio")
    UNIT_REGISTRY.register_unit("index_points", dimension="index_level")
    for currency in ("usd", "mxn", "eur", "gbp", "jpy"):
        UNIT_REGISTRY.register_unit(currency, dimension=f"currency_{currency}")
    UNIT_REGISTRY.register_unit("usd_per_gallon", dimension="usd_per_volume")
    UNIT_REGISTRY.register_unit("usd_per_barrel", dimension="usd_per_volume")
    UNIT_REGISTRY.register_conversion("usd_per_gallon", "usd_per_barrel", factor=42.0)


_register_builtin_units()


__all__ = [
    "ALIGNMENT_REGISTRY",
    "AsOfParameters",
    "CALCULATION_REGISTRY",
    "COEFFICIENT_REGISTRY",
    "ChainedReturnParameters",
    "ForwardFillParameters",
    "FuturesRankParameters",
    "EventRebalanceParameters",
    "LaggedCoefficientParameters",
    "MISSING_DATA_REGISTRY",
    "NearestTenorParameters",
    "NoParameters",
    "REBALANCE_REGISTRY",
    "RebaseParameters",
    "RollingCoefficientParameters",
    "SELECTOR_REGISTRY",
    "ScheduleParameters",
    "SelfFinancingParameters",
    "TRANSFORM_REGISTRY",
    "TypedRegistry",
    "UNIT_REGISTRY",
    "UnitRegistry",
    "normalize_code",
]
