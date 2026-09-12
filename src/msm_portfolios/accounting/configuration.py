"""Hash-bearing configuration for the opt-in accounting engine."""

from __future__ import annotations

import importlib
import datetime as dt
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from mainsequence.meta_tables.time_index_table_updates.configuration import (
    Serializer,
    serialize_argument,
)
from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater

from .lifecycle import LifecycleEventModel
from .valuation import PositionValuationModel


class HistoricalInformationPolicy(BaseModel):
    """Controls whether calculation uses as-known or corrected information."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["as_known", "corrected"] = "as_known"


class RoundingAndBalancePolicy(BaseModel):
    """Numerical reconciliation contract for event application."""

    model_config = ConfigDict(extra="forbid")

    balance_tolerance: float = Field(default=1e-9, ge=0.0)


class PortfolioAccountingConfiguration(BaseModel):
    """Explicit opt-in configuration for position-aware accounting."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    valuation_asset_identifier: str = Field(min_length=1)
    initial_nav: float = Field(gt=0.0, allow_inf_nan=False)
    initial_state_time_index: dt.datetime
    execution_fact_source_instance: TimeIndexTableUpdater | TimeIndexTableRef | None = Field(
        default=None,
        description="Explicit execution-fact dependency for the replay lane.",
    )
    position_valuation_model_instance: PositionValuationModel
    lifecycle_event_model_instances: tuple[LifecycleEventModel, ...] = ()
    historical_information_policy: HistoricalInformationPolicy = Field(
        default_factory=HistoricalInformationPolicy
    )
    rounding_and_balance_policy: RoundingAndBalancePolicy = Field(
        default_factory=RoundingAndBalancePolicy
    )

    @field_validator("initial_state_time_index")
    @classmethod
    def require_aware_initial_time(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("initial_state_time_index must be timezone-aware.")
        return value.astimezone(dt.UTC)

    @model_validator(mode="after")
    def validate_models(self) -> PortfolioAccountingConfiguration:
        identifiers: set[str] = set()
        for model in self.lifecycle_event_model_instances:
            model.validate_extension_contract()
            if model.model_identifier in identifiers:
                raise ValueError(
                    f"Duplicate lifecycle model_identifier {model.model_identifier!r}."
                )
            identifiers.add(model.model_identifier)
            dependencies = model.declared_dependencies()
            contracts = model.required_input_contracts()
            if set(dependencies) != set(contracts):
                raise ValueError(
                    f"{model.model_identifier} dependency names and input contracts must match."
                )
        return self

    @field_serializer("position_valuation_model_instance", when_used="json")
    def serialize_valuation_model(self, value: PositionValuationModel) -> dict[str, Any]:
        return canonical_valuation_model_configuration(value)

    @field_serializer("execution_fact_source_instance", when_used="json")
    def serialize_execution_source(
        self,
        value: TimeIndexTableUpdater | TimeIndexTableRef | None,
    ) -> dict[str, Any] | None:
        return None if value is None else serialize_argument(value)

    @field_serializer("lifecycle_event_model_instances", when_used="json")
    def serialize_lifecycle_models(
        self,
        value: tuple[LifecycleEventModel, ...],
    ) -> list[dict[str, Any]]:
        return sorted(
            (canonical_lifecycle_model_configuration(model) for model in value),
            key=lambda payload: payload["model_identifier"],
        )


def canonical_lifecycle_model_configuration(model: LifecycleEventModel) -> dict[str, Any]:
    """Return replayable concrete model config plus dependency identities."""

    model.validate_extension_contract()
    _require_importable_class(model.__class__)
    dependencies = {
        name: serialize_argument(dependency)
        for name, dependency in sorted(model.declared_dependencies().items())
    }
    return {
        "class_import_path": _class_import_path(model.__class__),
        "model_identifier": model.model_identifier,
        "model_version": model.model_version,
        "configuration_schema_version": model.configuration_schema_version,
        "economic_ordering_priority": model.economic_ordering_priority,
        "config": Serializer().serialize_init_kwargs(model.model_dump(mode="python")),
        "declared_dependencies": dependencies,
    }


def canonical_valuation_model_configuration(model: PositionValuationModel) -> dict[str, Any]:
    """Return replayable concrete valuation config plus dependency identities."""

    _require_importable_class(model.__class__)
    return {
        "class_import_path": _class_import_path(model.__class__),
        "model_identifier": model.model_identifier,
        "model_version": model.model_version,
        "config": Serializer().serialize_init_kwargs(model.model_dump(mode="python")),
        "declared_dependencies": {
            name: serialize_argument(dependency)
            for name, dependency in sorted(model.declared_dependencies().items())
        },
    }


def _class_import_path(cls: type) -> dict[str, str]:
    return {"module": cls.__module__, "qualname": cls.__qualname__}


def _require_importable_class(cls: type) -> None:
    if "<locals>" in cls.__qualname__:
        raise TypeError(f"{cls.__name__} must be a module-level importable class.")
    module = importlib.import_module(cls.__module__)
    value: Any = module
    for name in cls.__qualname__.split("."):
        value = getattr(value, name)
    if value is not cls:
        raise TypeError(f"{cls.__module__}.{cls.__qualname__} does not resolve to its class.")


__all__ = [
    "HistoricalInformationPolicy",
    "PortfolioAccountingConfiguration",
    "RoundingAndBalancePolicy",
    "canonical_lifecycle_model_configuration",
    "canonical_valuation_model_configuration",
]
