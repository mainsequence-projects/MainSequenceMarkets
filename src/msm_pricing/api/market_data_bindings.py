from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from msm.api.base import operation_result_rows
from msm.repositories.crud import (
    create_model,
    get_model_by_uid,
    search_model,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import create_pricing_schemas, resolve_pricing_runtime
from msm_pricing.models.market_data_bindings import PricingMarketDataBindingTable
from msm_pricing.settings import PRICING_CONTEXT_DEFAULT


def _validate_payload(
    payload_model: type[BaseModel],
    payload: BaseModel | Mapping[str, Any] | None,
    kwargs: Mapping[str, Any],
) -> BaseModel:
    if payload is None:
        return payload_model(**dict(kwargs))
    if kwargs:
        raise TypeError("Pass either a payload object or keyword fields, not both.")
    if isinstance(payload, payload_model):
        return payload
    if isinstance(payload, BaseModel):
        return payload_model.model_validate(payload.model_dump(exclude_unset=True))
    if isinstance(payload, Mapping):
        return payload_model.model_validate(dict(payload))
    raise TypeError("Payload must be a Pydantic model, mapping, or None.")


class PricingMarketDataBinding(BaseModel):
    """Pricing market-data DataNode binding for one context and concept."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[PricingMarketDataBindingTable]] = PricingMarketDataBindingTable
    __required_tables__: ClassVar[list[type[Any]]] = [PricingMarketDataBindingTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("context_key", "concept_key")

    uid: uuid.UUID
    context_key: str
    concept_key: str
    data_node_identifier: str
    source: str | None = None
    metadata_json: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("metadata_json", "metadata"),
    )

    @classmethod
    def create_schemas(cls, **kwargs: Any):
        requested_models = kwargs.pop("models", None)
        models = [*cls.__required_tables__, *(requested_models or [])]
        return create_pricing_schemas(models=models, **kwargs)

    @classmethod
    def create(
        cls,
        payload: PricingMarketDataBindingCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataBinding:
        values = _validate_payload(PricingMarketDataBindingCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: PricingMarketDataBindingUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataBinding:
        values = _validate_payload(PricingMarketDataBindingUpsert, payload, kwargs).model_dump()
        result = upsert_model(
            cls._active_context(),
            model=cls.__table__,
            values=values,
            conflict_columns=cls.__upsert_keys__,
        )
        return cls._from_operation_result(result)

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: PricingMarketDataBindingUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> PricingMarketDataBinding:
        values = _validate_payload(PricingMarketDataBindingUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def get_by_uid(cls, uid: uuid.UUID | str) -> PricingMarketDataBinding | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=uid)
        return cls._from_operation_result(result, required=False)

    @classmethod
    def get_by_context_and_concept(
        cls,
        *,
        context_key: str,
        concept_key: str,
    ) -> PricingMarketDataBinding | None:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={"context_key": context_key, "concept_key": concept_key},
            limit=1,
        )
        return cls._from_operation_result(result, required=False)

    @classmethod
    def resolve_data_node_identifier(
        cls,
        *,
        context_key: str,
        concept_key: str,
    ) -> str | None:
        binding = cls.get_by_context_and_concept(
            context_key=context_key,
            concept_key=concept_key,
        )
        if binding is None:
            return None
        return binding.data_node_identifier

    @classmethod
    def filter(cls, *, limit: int = 500, **filters: Any) -> list[PricingMarketDataBinding]:
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            filters={key: value for key, value in filters.items() if value is not None},
            limit=limit,
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def _active_context(cls):
        runtime = resolve_pricing_runtime(
            models=cls.__required_tables__,
            row_model_name=cls.__name__,
        )
        return runtime.context

    @classmethod
    def _from_operation_result(
        cls,
        result: Mapping[str, Any],
        *,
        required: bool = True,
    ) -> PricingMarketDataBinding | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include a PricingMarketDataBinding row."
            )
        return None


class PricingMarketDataBindingCreate(BaseModel):
    """Payload for creating one pricing market-data binding."""

    model_config = ConfigDict(extra="forbid")

    context_key: str = Field(
        default=PRICING_CONTEXT_DEFAULT,
        min_length=1,
        max_length=64,
    )
    concept_key: str = Field(min_length=1, max_length=128)
    data_node_identifier: str = Field(min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class PricingMarketDataBindingUpsert(PricingMarketDataBindingCreate):
    """Payload for inserting or replacing a binding by context and concept."""


class PricingMarketDataBindingUpdate(BaseModel):
    """Payload for updating mutable binding fields."""

    model_config = ConfigDict(extra="forbid")

    data_node_identifier: str | None = Field(default=None, min_length=1, max_length=255)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "PricingMarketDataBinding",
    "PricingMarketDataBindingCreate",
    "PricingMarketDataBindingUpdate",
    "PricingMarketDataBindingUpsert",
]
