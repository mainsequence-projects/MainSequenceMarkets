from __future__ import annotations

import datetime
import hashlib
import json
import math
import uuid
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DefinitionStatus = Literal["draft", "active", "retired"]
CompositionMode = Literal["fixed", "rule_selected", "rebalanced"]
ComponentKind = Literal["asset", "index", "selector"]


def _utc(value: datetime.datetime | str | pd.Timestamp | None) -> datetime.datetime | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("methodology timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


class IndexCalculationDefinition(BaseModel):
    """Typed persisted or in-memory derived-index methodology version."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: uuid.UUID | None = None
    index_uid: uuid.UUID | None = None
    definition_version: int | None = Field(default=None, gt=0)
    status: DefinitionStatus = "draft"
    effective_from: datetime.datetime
    effective_to: datetime.datetime | None = None
    calculation_kind: str = Field(min_length=1, max_length=64)
    calculation_family: str = Field(min_length=1, max_length=64)
    calculation_parameters_json: dict[str, Any] | None = None
    output_unit: str = Field(min_length=1, max_length=64)
    alignment_policy: str = Field(default="inner", min_length=1, max_length=64)
    alignment_parameters_json: dict[str, Any] | None = None
    missing_data_policy: str = Field(default="drop", min_length=1, max_length=64)
    missing_data_parameters_json: dict[str, Any] | None = None
    composition_mode: CompositionMode = "fixed"
    rebalance_policy: str | None = Field(default=None, max_length=64)
    rebalance_parameters_json: dict[str, Any] | None = None
    definition_hash: str | None = Field(default=None, min_length=64, max_length=64)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("effective_from", "effective_to", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: Any) -> datetime.datetime | None:
        return _utc(value)

    @field_validator(
        "calculation_kind",
        "calculation_family",
        "output_unit",
        "alignment_policy",
        "missing_data_policy",
        "composition_mode",
        "rebalance_policy",
        mode="before",
    )
    @classmethod
    def _normalize_code(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip().lower().replace(" ", "_")

    @model_validator(mode="after")
    def _validate_interval_and_composition(self) -> IndexCalculationDefinition:
        if self.effective_to is not None and self.effective_to <= self.effective_from:
            raise ValueError("effective_to must be later than effective_from")
        if self.composition_mode == "fixed" and self.rebalance_policy is not None:
            raise ValueError("fixed definitions cannot declare a rebalance_policy")
        if self.composition_mode != "fixed" and not self.rebalance_policy:
            raise ValueError("non-fixed definitions require a rebalance_policy")
        return self

    def semantic_payload(self) -> dict[str, Any]:
        """Return output-affecting fields used by the deterministic definition hash."""

        return self.model_dump(
            mode="json",
            exclude={
                "uid",
                "index_uid",
                "definition_version",
                "status",
                # Lifecycle closure is allowed when a successor activates or a
                # definition retires; it must not invalidate the immutable
                # methodology digest recorded on historical values.
                "effective_to",
                "definition_hash",
                "source",
                "metadata_json",
            },
            exclude_none=True,
        )


class IndexCalculationLeg(BaseModel):
    """Typed ordered input leg for a derived-index definition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: uuid.UUID | None = None
    definition_uid: uuid.UUID | None = None
    leg_key: str = Field(min_length=1, max_length=64)
    leg_order: int = Field(ge=0)
    leg_role: str | None = Field(default=None, max_length=64)
    component_kind: ComponentKind
    asset_uid: uuid.UUID | None = None
    component_index_uid: uuid.UUID | None = None
    selector_code: str | None = Field(default=None, max_length=64)
    selector_parameters_json: dict[str, Any] | None = None
    observable_code: str = Field(min_length=1, max_length=64)
    input_unit: str = Field(min_length=1, max_length=64)
    transform_code: str = Field(default="identity", min_length=1, max_length=64)
    transform_parameters_json: dict[str, Any] | None = None
    coefficient_method: str = Field(default="fixed", min_length=1, max_length=64)
    coefficient: float | None = None
    coefficient_parameters_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator(
        "leg_key",
        "leg_role",
        "component_kind",
        "selector_code",
        "observable_code",
        "input_unit",
        "transform_code",
        "coefficient_method",
        mode="before",
    )
    @classmethod
    def _normalize_code(cls, value: Any) -> Any:
        if value is None:
            return None
        return str(value).strip().lower().replace(" ", "_")

    @model_validator(mode="after")
    def _validate_component_and_coefficient(self) -> IndexCalculationLeg:
        sources = [self.asset_uid, self.component_index_uid, self.selector_code]
        if sum(source is not None for source in sources) != 1:
            raise ValueError(
                "exactly one of asset_uid, component_index_uid, or selector_code is required"
            )
        expected_kind = (
            "asset"
            if self.asset_uid is not None
            else "index"
            if self.component_index_uid is not None
            else "selector"
        )
        if self.component_kind != expected_kind:
            raise ValueError(
                f"component_kind={self.component_kind!r} does not match configured {expected_kind} source"
            )
        if self.coefficient_method == "fixed":
            if self.coefficient is None or not math.isfinite(float(self.coefficient)):
                raise ValueError("fixed coefficient_method requires a finite coefficient")
        elif self.coefficient is not None:
            raise ValueError("dynamic coefficient methods cannot persist a resolved coefficient")
        return self

    def semantic_payload(self) -> dict[str, Any]:
        return self.model_dump(
            mode="json",
            exclude={"uid", "definition_uid", "metadata_json"},
            exclude_none=True,
        )


class ResolvedIndexLeg(BaseModel):
    """Concrete component and coefficient effective at one calculation time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    time_index: datetime.datetime
    index_identifier: str
    definition_uid: uuid.UUID
    leg_key: str
    resolved_component_key: str
    component_kind: Literal["asset", "index"]
    resolved_coefficient: float
    coefficient_method: str
    observable_code: str
    source_observation_time: datetime.datetime | None = None
    resolution_status: str = "ready"
    metadata_json: dict[str, Any] | None = None

    @field_validator("time_index", "source_observation_time", mode="before")
    @classmethod
    def _normalize_timestamp(cls, value: Any) -> datetime.datetime | None:
        return _utc(value)

    @field_validator("resolved_coefficient")
    @classmethod
    def _finite_coefficient(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("resolved_coefficient must be finite")
        return value


class IndexCalculationResult(BaseModel):
    """Pure calculation result and its canonical publication frame."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    values: pd.DataFrame
    resolved_legs: pd.DataFrame | None = None


def compute_definition_hash(
    definition: IndexCalculationDefinition,
    legs: list[IndexCalculationLeg] | tuple[IndexCalculationLeg, ...],
) -> str:
    ordered = sorted(legs, key=lambda leg: (leg.leg_order, leg.leg_key))
    payload = {
        "definition": definition.semantic_payload(),
        "legs": [leg.semantic_payload() for leg in ordered],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_definition_hash(
    definition: IndexCalculationDefinition,
    legs: list[IndexCalculationLeg] | tuple[IndexCalculationLeg, ...],
) -> str:
    calculated = compute_definition_hash(definition, legs)
    if definition.definition_hash is not None and definition.definition_hash != calculated:
        raise ValueError("definition_hash does not match the ordered output-affecting semantics")
    return calculated


__all__ = [
    "ComponentKind",
    "CompositionMode",
    "DefinitionStatus",
    "IndexCalculationDefinition",
    "IndexCalculationLeg",
    "IndexCalculationResult",
    "ResolvedIndexLeg",
    "compute_definition_hash",
    "validate_definition_hash",
]
