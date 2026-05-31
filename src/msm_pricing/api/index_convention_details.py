from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from msm.api.base import operation_result_rows
from msm.models import IndexTable, IndexTypeTable
from msm.repositories.crud import (
    create_model,
    get_model_by_uid,
    update_model,
    upsert_model,
)

from msm_pricing.bootstrap import create_pricing_schemas, resolve_pricing_runtime
from msm_pricing.models.index_convention_details import IndexConventionDetailsTable

DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT = "msm_pricing.index_convention.v1"


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


class IndexConventionDetails(BaseModel):
    """Pricing convention details attached one-to-one to a canonical index."""

    model_config = ConfigDict(extra="ignore", frozen=True)

    __table__: ClassVar[type[IndexConventionDetailsTable]] = IndexConventionDetailsTable
    __required_tables__: ClassVar[list[type[Any]]] = [
        IndexTypeTable,
        IndexTable,
        IndexConventionDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("index_uid",)

    index_uid: uuid.UUID
    index_family: str
    convention_dump: dict[str, Any]
    serialization_format: str = DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT
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
        payload: IndexConventionDetailsCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexConventionDetails:
        values = _validate_payload(IndexConventionDetailsCreate, payload, kwargs).model_dump()
        result = create_model(cls._active_context(), model=cls.__table__, values=values)
        return cls._from_operation_result(result)

    @classmethod
    def upsert(
        cls,
        payload: IndexConventionDetailsUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexConventionDetails:
        values = _validate_payload(IndexConventionDetailsUpsert, payload, kwargs).model_dump()
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
        index_uid: uuid.UUID | str,
        payload: IndexConventionDetailsUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexConventionDetails:
        values = _validate_payload(IndexConventionDetailsUpdate, payload, kwargs).model_dump(
            exclude_unset=True,
        )
        result = update_model(
            cls._active_context(),
            model=cls.__table__,
            uid=index_uid,
            values=values,
        )
        return cls._from_operation_result(result)

    @classmethod
    def get_by_index_uid(cls, index_uid: uuid.UUID | str) -> IndexConventionDetails | None:
        result = get_model_by_uid(cls._active_context(), model=cls.__table__, uid=index_uid)
        return cls._from_operation_result(result, required=False)

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
    ) -> IndexConventionDetails | None:
        rows = operation_result_rows(result)
        if rows:
            return cls.model_validate(rows[0])
        if required:
            raise LookupError(
                "MetaTable operation result did not include an IndexConventionDetails row."
            )
        return None


class IndexConventionDetailsCreate(BaseModel):
    """Payload for creating pricing convention details for an index."""

    model_config = ConfigDict(extra="forbid")

    index_uid: uuid.UUID
    index_family: str = Field(min_length=1, max_length=64)
    convention_dump: dict[str, Any]
    serialization_format: str = Field(
        default=DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT,
        min_length=1,
        max_length=128,
    )
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


class IndexConventionDetailsUpsert(IndexConventionDetailsCreate):
    """Payload for inserting or replacing convention details by index UID."""


class IndexConventionDetailsUpdate(BaseModel):
    """Payload for updating mutable index convention detail fields."""

    model_config = ConfigDict(extra="forbid")

    index_family: str | None = Field(default=None, min_length=1, max_length=64)
    convention_dump: dict[str, Any] | None = None
    serialization_format: str | None = Field(default=None, min_length=1, max_length=128)
    source: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None


__all__ = [
    "DEFAULT_INDEX_CONVENTION_SERIALIZATION_FORMAT",
    "IndexConventionDetails",
    "IndexConventionDetailsCreate",
    "IndexConventionDetailsUpdate",
    "IndexConventionDetailsUpsert",
]
