from __future__ import annotations

import datetime as dt
import re
import uuid
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.base import MarketsMetaTableRow, operation_result_rows
from msm.models import (
    IndexCalculationDefinitionTable,
    IndexCalculationLegTable,
    IndexDeletionExecutionTable,
    IndexTable,
    IndexTypeTable,
)
from msm.repositories.crud import search_model

if TYPE_CHECKING:
    from msm.repositories.base import MarketsOperationContext
    from msm.services.indices import (
        IndexActor,
        IndexBulkDeleteExecuteRequest,
        IndexBulkDeletePreview,
        IndexBulkDeletePreviewRequest,
        IndexBulkDeleteResult,
        IndexDatasetDescriptor,
        IndexDatasetSummary,
        IndexDetail,
        IndexListRequest,
        IndexMethodologyDetail,
        IndexMethodologySummary,
        IndexPage,
        IndexRelatedMetaTable,
        IndexSummary,
        IndexValuesResult,
    )


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


def normalize_index_type(index_type: str | None) -> str | None:
    """Return the canonical index type key stored by the typed API."""

    if index_type is None:
        return None

    normalized = re.sub(r"\s+", "_", str(index_type).strip().lower())
    if not normalized:
        raise ValueError("index_type cannot be empty.")
    return normalized


class IndexType(MarketsMetaTableRow):
    """Typed row for the index type registry."""

    __table__: ClassVar[type[IndexTypeTable]] = IndexTypeTable
    __required_tables__: ClassVar[list[type[IndexTypeTable]]] = [IndexTypeTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("index_type",)

    index_type: str
    display_name: str | None = None
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_row_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type cannot be empty.")
        return normalized

    @classmethod
    def create(
        cls,
        payload: IndexTypeCreate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexType:
        return super().create(_validate_payload(IndexTypeCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: IndexTypeUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexType:
        return super().upsert(_validate_payload(IndexTypeUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: IndexTypeUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexType:
        return super().update(uid, _validate_payload(IndexTypeUpdate, payload, kwargs))


class IndexTypeCreate(BaseModel):
    """Payload for creating an index type registry row."""

    model_config = ConfigDict(extra="forbid")

    index_type: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type cannot be empty.")
        return normalized


class IndexTypeUpsert(IndexTypeCreate):
    """Payload for inserting or updating an index type by registry key."""


class IndexTypeUpdate(BaseModel):
    """Payload for updating mutable index type fields."""

    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    metadata_json: dict[str, Any] | None = None


class Index(MarketsMetaTableRow):
    """User-facing market index reference row."""

    __table__: ClassVar[type[IndexTable]] = IndexTable
    __required_tables__: ClassVar[list[type[Any]]] = [IndexTypeTable, IndexTable]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("unique_identifier",)

    unique_identifier: str
    index_type: str
    display_name: str
    description: str | None = None
    provider: str | None = None
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_row_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type is required.")
        return normalized

    @classmethod
    def create(cls, payload: IndexCreate | Mapping[str, Any] | None = None, **kwargs: Any) -> Index:
        return super().create(_validate_payload(IndexCreate, payload, kwargs))

    @classmethod
    def upsert(
        cls,
        payload: IndexUpsert | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Index:
        return super().upsert(_validate_payload(IndexUpsert, payload, kwargs))

    @classmethod
    def update(
        cls,
        uid: uuid.UUID | str,
        payload: IndexUpdate | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Index:
        return super().update(uid, _validate_payload(IndexUpdate, payload, kwargs))

    @classmethod
    def filter_by_uids(
        cls,
        uids: list[uuid.UUID | str] | tuple[uuid.UUID | str, ...] | set[uuid.UUID | str],
    ) -> list[Index]:
        resolved_uids = [uuid.UUID(str(value)) for value in uids]
        if not resolved_uids:
            return []
        result = search_model(
            cls._active_context(),
            model=cls.__table__,
            in_filters={"uid": resolved_uids},
            limit=len(resolved_uids),
        )
        return [cls.model_validate(row) for row in operation_result_rows(result)]

    @classmethod
    def list_page(
        cls,
        request: IndexListRequest | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> IndexPage:
        """Return a typed, counted Index catalog page."""

        from msm.services.indices import IndexListRequest, list_indexes

        resolved = (
            request
            if isinstance(request, IndexListRequest)
            else IndexListRequest.model_validate(request or kwargs)
        )
        return list_indexes(cls._service_context(), resolved)

    @classmethod
    def get_detail(
        cls,
        uid: uuid.UUID | str,
        *,
        actor: IndexActor | None = None,
    ) -> IndexDetail | None:
        from msm.services.indices import get_index_detail

        index = cls.get_by_uid(uid)
        return (
            None
            if index is None
            else get_index_detail(cls._service_context(), index=index, actor=actor)
        )

    @classmethod
    def get_summary(
        cls,
        uid: uuid.UUID | str,
        *,
        actor: IndexActor | None = None,
    ) -> IndexSummary | None:
        from msm.services.indices import get_index_summary

        index = cls.get_by_uid(uid)
        return (
            None
            if index is None
            else get_index_summary(cls._service_context(), index=index, actor=actor)
        )

    @classmethod
    def list_methodologies(cls, uid: uuid.UUID | str) -> tuple[IndexMethodologySummary, ...]:
        from msm.services.indices import list_methodologies

        if cls.get_by_uid(uid) is None:
            raise LookupError(f"Index {uid!s} was not found")
        return list_methodologies(cls._service_context(), index_uid=uid)

    @classmethod
    def get_methodology(
        cls,
        uid: uuid.UUID | str,
        definition_uid: uuid.UUID | str,
    ) -> IndexMethodologyDetail | None:
        from msm.services.indices import get_methodology

        if cls.get_by_uid(uid) is None:
            raise LookupError(f"Index {uid!s} was not found")
        return get_methodology(
            cls._service_context(),
            index_uid=uid,
            definition_uid=definition_uid,
        )

    @classmethod
    def list_datasets(
        cls,
        uid: uuid.UUID | str,
        *,
        actor: IndexActor | None = None,
    ) -> tuple[IndexDatasetDescriptor, ...]:
        from msm.services.indices import discover_canonical_datasets

        if cls.get_by_uid(uid) is None:
            raise LookupError(f"Index {uid!s} was not found")
        return discover_canonical_datasets(actor=actor)

    @classmethod
    def get_dataset_summary(
        cls,
        uid: uuid.UUID | str,
        meta_table_uid: str,
        *,
        actor: IndexActor | None = None,
    ) -> IndexDatasetSummary:
        from msm.services.indices import dataset_summary, get_canonical_dataset

        index = cls.get_by_uid(uid)
        if index is None:
            raise LookupError(f"Index {uid!s} was not found")
        dataset = get_canonical_dataset(meta_table_uid, actor=actor)
        if dataset is None:
            raise LookupError(f"Canonical Index dataset {meta_table_uid!r} was not found")
        return dataset_summary(cls._service_context(), index=index, dataset=dataset)

    @classmethod
    def get_values(
        cls,
        uid: uuid.UUID | str,
        meta_table_uid: str,
        *,
        start: dt.datetime,
        end: dt.datetime,
        order: str = "desc",
        limit: int = 500,
        actor: IndexActor | None = None,
    ) -> IndexValuesResult:
        from msm.services.indices import get_canonical_dataset, read_index_values

        index = cls.get_by_uid(uid)
        if index is None:
            raise LookupError(f"Index {uid!s} was not found")
        dataset = get_canonical_dataset(meta_table_uid, actor=actor)
        if dataset is None:
            raise LookupError(f"Canonical Index dataset {meta_table_uid!r} was not found")
        return read_index_values(
            cls._service_context(),
            index=index,
            dataset=dataset,
            start=start,
            end=end,
            order=order,
            limit=limit,
        )

    @classmethod
    def list_related_meta_tables(cls, uid: uuid.UUID | str) -> tuple[IndexRelatedMetaTable, ...]:
        from msm.services.indices import list_related_meta_tables

        index = cls.get_by_uid(uid)
        if index is None:
            raise LookupError(f"Index {uid!s} was not found")
        return list_related_meta_tables(cls._service_context(), index=index)

    @classmethod
    def preview_bulk_delete(
        cls,
        request: IndexBulkDeletePreviewRequest | Mapping[str, Any],
        *,
        actor: IndexActor | None = None,
    ) -> IndexBulkDeletePreview:
        from msm.services.indices import (
            IndexBulkDeletePreviewRequest,
            preview_bulk_delete,
            resolve_authenticated_index_actor,
        )

        resolved_request = (
            request
            if isinstance(request, IndexBulkDeletePreviewRequest)
            else IndexBulkDeletePreviewRequest.model_validate(request)
        )
        return preview_bulk_delete(
            cls._service_context(),
            actor=actor or resolve_authenticated_index_actor(),
            request=resolved_request,
        )

    @classmethod
    def bulk_delete(
        cls,
        request: IndexBulkDeleteExecuteRequest | Mapping[str, Any],
        *,
        actor: IndexActor | None = None,
        expected_single_index_uid: uuid.UUID | str | None = None,
    ) -> IndexBulkDeleteResult:
        from msm.services.indices import (
            IndexBulkDeleteExecuteRequest,
            execute_bulk_delete,
            resolve_authenticated_index_actor,
        )

        resolved_request = (
            request
            if isinstance(request, IndexBulkDeleteExecuteRequest)
            else IndexBulkDeleteExecuteRequest.model_validate(request)
        )
        return execute_bulk_delete(
            cls._service_context(),
            actor=actor or resolve_authenticated_index_actor(),
            request=resolved_request,
            expected_single_index_uid=expected_single_index_uid,
        )

    @classmethod
    def delete(
        cls,
        uid: uuid.UUID | str,
        *,
        confirmation_token: str | None = None,
        confirmation_phrase: str | None = None,
        acknowledged_warning_codes=(),
        idempotency_key: str | None = None,
        actor: IndexActor | None = None,
    ) -> IndexBulkDeleteResult:
        """Delete one Index only through the reviewed bulk-deletion contract."""

        from msm.services.indices import (
            IndexBulkDeleteExecuteRequest,
            IndexDeletionConfirmationRequired,
        )

        if not confirmation_token or not confirmation_phrase or not idempotency_key:
            raise IndexDeletionConfirmationRequired(
                "Index.delete requires a preview token, exact phrase, warning acknowledgements, "
                "and idempotency key. Use Index.preview_bulk_delete first."
            )
        result = cls.bulk_delete(
            IndexBulkDeleteExecuteRequest(
                confirmation_token=confirmation_token,
                confirmation_phrase=confirmation_phrase,
                acknowledged_warning_codes=tuple(acknowledged_warning_codes),
                idempotency_key=idempotency_key,
            ),
            actor=actor,
            expected_single_index_uid=uid,
        )
        return result

    @classmethod
    def _delete_repository(cls, uid: uuid.UUID | str) -> dict[str, Any]:
        """Private compensation primitive; not an interactive deletion workflow."""

        from msm.repositories.crud import delete_model

        return delete_model(cls._active_context(), model=cls.__table__, uid=uid)

    @classmethod
    def _service_context(cls) -> MarketsOperationContext:
        """Resolve the broader Index exploration/lifecycle runtime on demand."""

        from msm.bootstrap import resolve_runtime
        from msm.data_nodes.indices.storage import IndexResolvedLegsStorage

        return resolve_runtime(
            models=[
                IndexTypeTable,
                IndexTable,
                IndexCalculationDefinitionTable,
                IndexCalculationLegTable,
                IndexDeletionExecutionTable,
                IndexResolvedLegsStorage,
            ],
            row_model_name="Index catalog and lifecycle services",
        ).context


class IndexCreate(BaseModel):
    """Payload for creating an index reference row."""

    model_config = ConfigDict(extra="forbid")

    unique_identifier: str = Field(min_length=1, max_length=255)
    index_type: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_index_type(cls, value: str) -> str:
        normalized = normalize_index_type(value)
        if normalized is None:
            raise ValueError("index_type is required.")
        return normalized


class IndexUpsert(IndexCreate):
    """Payload for inserting or updating an index by unique identifier."""


class IndexUpdate(BaseModel):
    """Payload for updating mutable index reference fields."""

    model_config = ConfigDict(extra="forbid")

    index_type: str | None = Field(default=None, max_length=64)
    display_name: str | None = Field(default=None, max_length=255)
    description: str | None = None
    provider: str | None = Field(default=None, max_length=255)
    metadata_json: dict[str, Any] | None = None

    @field_validator("index_type", mode="before")
    @classmethod
    def _normalize_index_type(cls, value: str | None) -> str | None:
        return normalize_index_type(value)

    @model_validator(mode="after")
    def _reject_explicit_null_index_type(self) -> IndexUpdate:
        if "index_type" in self.model_fields_set and self.index_type is None:
            raise ValueError("index_type cannot be null.")
        return self


__all__ = [
    "DerivedIndex",
    "IncompleteObservationsError",
    "IndexCalculationDefinition",
    "IndexCalculationError",
    "IndexCalculationLeg",
    "IndexCalculationResult",
    "Index",
    "IndexCreate",
    "IndexType",
    "IndexTypeCreate",
    "IndexTypeUpdate",
    "IndexTypeUpsert",
    "IndexUpdate",
    "IndexUpsert",
    "LookAheadError",
    "ResolvedIndexLeg",
    "calculate_index",
    "compute_definition_hash",
    "normalize_index_type",
]


# Imported after the canonical Index row APIs are defined to avoid a module cycle.
from msm.analytics.indices import (  # noqa: E402
    IncompleteObservationsError,
    IndexCalculationDefinition,
    IndexCalculationError,
    IndexCalculationLeg,
    IndexCalculationResult,
    LookAheadError,
    ResolvedIndexLeg,
    calculate_index,
    compute_definition_hash,
)
from msm.api.derived_indices import DerivedIndex  # noqa: E402

DerivedIndex.model_rebuild(_types_namespace={"Index": Index})
