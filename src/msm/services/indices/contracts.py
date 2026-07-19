from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from msm.api.indices import Index


class IndexServiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IndexActor(IndexServiceModel):
    user_uid: str = Field(min_length=1, max_length=255)
    username: str | None = None
    team_uids: tuple[str, ...] = ()


class IndexListRequest(IndexServiceModel):
    search: str = ""
    uids: tuple[uuid.UUID, ...] = ()
    unique_identifiers: tuple[str, ...] = ()
    index_type: str | None = None
    provider: str | None = None
    has_definition: bool | None = None
    has_canonical_values: bool | None = None
    cadence: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    order: Literal["display_name", "unique_identifier", "index_type", "provider"] = "display_name"


class IndexPage(IndexServiceModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    results: tuple[Index, ...]


class IndexMethodologySummary(IndexServiceModel):
    uid: uuid.UUID
    index_uid: uuid.UUID
    definition_version: int
    status: str
    effective_from: dt.datetime
    effective_to: dt.datetime | None = None
    calculation_kind: str
    calculation_family: str
    output_unit: str
    composition_mode: str
    definition_hash: str
    leg_count: int = Field(ge=0)


class IndexMethodologyLeg(IndexServiceModel):
    uid: uuid.UUID
    definition_uid: uuid.UUID
    leg_key: str
    leg_order: int
    component_kind: str
    asset_uid: uuid.UUID | None = None
    component_index_uid: uuid.UUID | None = None
    selector_code: str | None = None
    observable: str
    input_unit: str
    transform_kind: str
    coefficient_method: str
    coefficient: float | None = None
    metadata_json: dict[str, Any] | None = None


class IndexMethodologyDetail(IndexMethodologySummary):
    calculation_parameters_json: dict[str, Any] | None = None
    alignment_policy: str
    alignment_parameters_json: dict[str, Any] | None = None
    missing_data_policy: str
    missing_data_parameters_json: dict[str, Any] | None = None
    rebalance_policy: str | None = None
    rebalance_parameters_json: dict[str, Any] | None = None
    source: str | None = None
    metadata_json: dict[str, Any] | None = None
    legs: tuple[IndexMethodologyLeg, ...]


class IndexDatasetAccess(IndexServiceModel):
    can_view: bool
    can_edit: bool | None = None
    reason: str | None = None


class IndexForeignKeyDescriptor(IndexServiceModel):
    source_column: str
    target_table: str
    target_column: str
    on_delete: str | None = None


class IndexDatasetDescriptor(IndexServiceModel):
    meta_table_uid: str
    identifier: str
    namespace: str | None = None
    cadence: str
    physical_table_name: str
    time_index_name: str
    index_names: tuple[str, ...]
    columns: tuple[str, ...]
    foreign_keys: tuple[IndexForeignKeyDescriptor, ...]
    description: str | None = None
    storage_kind: Literal[
        "canonical_index_values",
        "resolved_index_legs",
        "declared_extension_values",
        "related_reference_table",
        "inferred_candidate",
    ]
    discovery_source: Literal["core_model", "declared_provider", "inferred"]
    access: IndexDatasetAccess
    producer_identifiers: tuple[str, ...] = ()
    scoped_delete_supported: bool = False


class IndexDatasetSummary(IndexServiceModel):
    dataset: IndexDatasetDescriptor
    index_uid: uuid.UUID
    index_identifier: str
    row_count: int | None = Field(default=None, ge=0)
    count_accuracy: Literal["exact", "estimated", "unavailable"]
    earliest_time_index: dt.datetime | None = None
    latest_time_index: dt.datetime | None = None
    latest_value: float | None = None
    latest_unit: str | None = None
    latest_status: str | None = None
    latest_source_as_of: dt.datetime | None = None
    error: str | None = None


class IndexValueRow(IndexServiceModel):
    time_index: dt.datetime
    index_identifier: str
    value: float
    unit: str
    definition_uid: uuid.UUID | None = None
    observation_status: str | None = None
    source_as_of: dt.datetime | None = None
    metadata_json: dict[str, Any] | None = None


class IndexValuesResult(IndexServiceModel):
    dataset: IndexDatasetDescriptor
    index_uid: uuid.UUID
    index_identifier: str
    start: dt.datetime
    end: dt.datetime
    order: Literal["asc", "desc"]
    limit: int
    rows: tuple[IndexValueRow, ...]


class IndexRelatedMetaTable(IndexServiceModel):
    key: str
    label: str
    owning_package: str
    storage_kind: str
    meta_table_uid: str | None = None
    identifier: str
    relationship_type: str
    join_kind: Literal["uid", "unique_identifier", "indirect"]
    join_column: str | None = None
    on_delete: str
    authoritative: bool
    discovery_source: Literal["core_model", "declared_provider", "inferred"]
    exploration_capability: Literal["none", "count", "summary", "values"]
    delete_capability: Literal["none", "scoped", "cascade", "set_null", "manual"]
    count: int | None = Field(default=None, ge=0)
    blocks_delete: bool = False
    confidence_reason: str | None = None


class IndexDetail(IndexServiceModel):
    index: Index
    methodologies: tuple[IndexMethodologySummary, ...]
    datasets: tuple[IndexDatasetDescriptor, ...]
    related_meta_tables: tuple[IndexRelatedMetaTable, ...]
    warnings: tuple[str, ...] = ()


class IndexSummary(IndexServiceModel):
    index: Index
    definition_count: int = Field(ge=0)
    leg_count: int = Field(ge=0)
    active_definition: IndexMethodologySummary | None = None
    dataset_count: int = Field(ge=0)
    cadences: tuple[str, ...]
    dataset_summaries: tuple[IndexDatasetSummary, ...]
    authoritative_relationship_count: int = Field(ge=0)
    inferred_relationship_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


IndexDeleteMode = Literal["values_only", "identity_only", "identity_and_values"]


class IndexBulkDeletePreviewRequest(IndexServiceModel):
    index_uids: tuple[uuid.UUID, ...] = Field(min_length=1, max_length=100)
    mode: IndexDeleteMode
    canonical_dataset_uids: tuple[str, ...] | None = None
    declared_extension_dataset_uids: tuple[str, ...] = ()
    failure_policy: Literal["stop_on_error"] = "stop_on_error"

    @field_validator("index_uids")
    @classmethod
    def _unique_uids(cls, value: tuple[uuid.UUID, ...]) -> tuple[uuid.UUID, ...]:
        return tuple(dict.fromkeys(value))

    @field_validator("canonical_dataset_uids", "declared_extension_dataset_uids")
    @classmethod
    def _unique_dataset_uids(cls, value: tuple[str, ...] | None):
        if value is None:
            return None
        normalized = tuple(str(item).strip() for item in value)
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("dataset UIDs must be non-empty and unique")
        return normalized

    @model_validator(mode="after")
    def _validate_mode_options(self):
        if self.mode == "identity_only" and (
            self.canonical_dataset_uids is not None or self.declared_extension_dataset_uids
        ):
            raise ValueError("identity_only cannot select value datasets")
        return self


class IndexDeleteWarning(IndexServiceModel):
    code: str
    severity: Literal["info", "warning", "blocking", "destructive"]
    title: str
    message: str
    affected_index_uids: tuple[uuid.UUID, ...] = ()
    affected_meta_table_uids: tuple[str, ...] = ()
    requires_acknowledgement: bool


class IndexDeleteItemImpact(IndexServiceModel):
    uid: uuid.UUID
    exists: bool
    unique_identifier: str | None = None
    display_name: str | None = None
    index_type: str | None = None
    definition_count: int | None = None
    leg_count: int | None = None
    component_dependency_count: int | None = None
    can_delete_identity: bool


class IndexDatasetDeleteImpact(IndexServiceModel):
    meta_table_uid: str
    identifier: str
    cadence: str | None = None
    storage_kind: str
    provider_key: str | None = None
    selected: bool
    affected_index_uids: tuple[uuid.UUID, ...]
    affected_row_count: int | None = Field(default=None, ge=0)
    count_accuracy: Literal["exact", "estimated", "unavailable"]
    earliest_time_index: dt.datetime | None = None
    latest_time_index: dt.datetime | None = None
    access: IndexDatasetAccess
    scoped_delete_supported: bool


class IndexBulkDeletePreview(IndexServiceModel):
    plan_id: uuid.UUID
    requested_mode: IndexDeleteMode
    normalized_request: IndexBulkDeletePreviewRequest
    created_at: dt.datetime
    expires_at: dt.datetime
    created_by_user_uid: str
    scope_hash: str
    confirmation_token: str
    executable: bool
    indexes: tuple[IndexDeleteItemImpact, ...]
    datasets: tuple[IndexDatasetDeleteImpact, ...]
    relationships: tuple[IndexRelatedMetaTable, ...]
    warnings: tuple[IndexDeleteWarning, ...]
    required_acknowledgement_codes: tuple[str, ...]
    confirmation_phrase: str


class IndexBulkDeleteExecuteRequest(IndexServiceModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1)
    acknowledged_warning_codes: tuple[str, ...]
    idempotency_key: str = Field(min_length=1, max_length=255)


class IndexDeleteItemResult(IndexServiceModel):
    index_uid: uuid.UUID
    unique_identifier: str | None = None
    status: Literal["deleted", "kept", "already_absent", "failed", "not_started"]
    error: str | None = None


class IndexDatasetDeleteResult(IndexServiceModel):
    meta_table_uid: str
    identifier: str
    status: Literal["deleted", "already_empty", "failed", "not_started"]
    deleted_count: int | None = Field(default=None, ge=0)
    error: str | None = None


class IndexBulkDeleteResult(IndexServiceModel):
    status: Literal["completed", "partial", "failed"]
    plan_id: uuid.UUID
    idempotency_key: str
    requested_mode: IndexDeleteMode
    requested_index_count: int = Field(ge=0)
    deleted_index_count: int = Field(ge=0)
    deleted_value_count: int = Field(ge=0)
    deleted_resolved_leg_count: int = Field(ge=0)
    index_results: tuple[IndexDeleteItemResult, ...]
    dataset_results: tuple[IndexDatasetDeleteResult, ...]
    warnings: tuple[IndexDeleteWarning, ...]


__all__ = [name for name in globals() if name.startswith("Index")]
