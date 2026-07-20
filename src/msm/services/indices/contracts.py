from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from msm.analytics.indices import IndexFormulaInput
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
    has_formula: bool | None = None
    has_canonical_values: bool | None = None
    cadence: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)
    order: Literal[
        "display_name",
        "unique_identifier",
        "index_type",
        "calculation_method",
    ] = "display_name"


class IndexPage(IndexServiceModel):
    count: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
    results: tuple[Index, ...]


class IndexFormulaSummary(IndexServiceModel):
    uid: uuid.UUID
    index_uid: uuid.UUID
    version: int
    status: str
    valid_from: dt.datetime
    valid_to: dt.datetime | None = None
    formula: str
    alignment_policy: str
    missing_data_policy: str
    definition_hash: str
    input_count: int = Field(ge=0)


class IndexFormulaDetail(IndexFormulaSummary):
    alignment_parameters_json: dict[str, Any] | None = None
    metadata_json: dict[str, Any] | None = None
    inputs: tuple[IndexFormulaInput, ...]


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
        "declared_extension_values",
        "related_reference_table",
        "inferred_candidate",
    ]
    discovery_source: Literal["core_model", "declared_provider", "inferred"]
    access: IndexDatasetAccess
    producer_identifiers: tuple[str, ...] = ()


IndexDatasetPopulationState = Literal[
    "populated",
    "compatible_empty",
    "unavailable",
]


class IndexDatasetState(IndexServiceModel):
    dataset: IndexDatasetDescriptor
    index_uid: uuid.UUID
    index_identifier: str
    population_state: IndexDatasetPopulationState
    row_count: int | None = Field(default=None, ge=0)
    earliest_time_index: dt.datetime | None = None
    latest_time_index: dt.datetime | None = None
    reconciled_at: dt.datetime
    error: str | None = None


class IndexDatasetReconciliationResult(IndexServiceModel):
    index_uids: tuple[uuid.UUID, ...]
    dataset_count: int = Field(ge=0)
    states: tuple[IndexDatasetState, ...]


class IndexDatasetSummary(IndexServiceModel):
    dataset: IndexDatasetDescriptor
    index_uid: uuid.UUID
    index_identifier: str
    row_count: int | None = Field(default=None, ge=0)
    count_accuracy: Literal["exact", "estimated", "unavailable"]
    earliest_time_index: dt.datetime | None = None
    latest_time_index: dt.datetime | None = None
    latest_value: float | None = None
    latest_status: str | None = None
    latest_source_as_of: dt.datetime | None = None
    error: str | None = None


class IndexValueRow(IndexServiceModel):
    time_index: dt.datetime
    index_identifier: str
    value: float
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


class RelatedMetaTable(IndexServiceModel):
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
    delete_capability: Literal["none", "cascade", "set_null"]
    count: int | None = Field(default=None, ge=0)
    blocks_delete: bool = False
    confidence_reason: str | None = None


class IndexDeleteImpactRelationship(IndexServiceModel):
    key: str
    label: str
    model: str
    column: str
    relationship_type: Literal["direct", "indirect", "derived"]
    on_delete: Literal[
        "RESTRICT",
        "NO ACTION",
        "CASCADE",
        "SET NULL",
        "APPLICATION",
        "UNKNOWN",
    ]
    count: int | None = Field(default=None, ge=0)
    count_accuracy: Literal["exact", "unavailable"]
    effect: Literal[
        "blocks_delete",
        "blocks_cascade",
        "cascade_delete",
        "set_null",
        "delete_cleanup",
        "manual_cleanup_required",
        "informational",
    ]
    severity: Literal["blocking", "destructive", "mutating", "warning", "info"]
    blocks_delete: bool
    description: str


class IndexDeleteImpact(IndexServiceModel):
    resource_type: Literal["index"] = "index"
    uid: uuid.UUID
    identifier: str
    display_name: str
    can_delete: bool
    blocking_count: int = Field(ge=0)
    affected_count: int = Field(ge=0)
    delete_endpoint: str
    relationships: tuple[IndexDeleteImpactRelationship, ...]
    warnings: tuple[str, ...] = ()


class IndexDetail(IndexServiceModel):
    index: Index
    formulas: tuple[IndexFormulaSummary, ...]
    datasets: tuple[IndexDatasetState, ...]
    related_meta_tables: tuple[RelatedMetaTable, ...]
    warnings: tuple[str, ...] = ()


class IndexSummary(IndexServiceModel):
    index: Index
    formula_count: int = Field(ge=0)
    input_count: int = Field(ge=0)
    active_formula: IndexFormulaSummary | None = None
    dataset_count: int = Field(ge=0)
    cadences: tuple[str, ...]
    dataset_states: tuple[IndexDatasetState, ...]
    authoritative_relationship_count: int = Field(ge=0)
    inferred_relationship_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


__all__ = [name for name in globals() if name.startswith("Index")] + ["RelatedMetaTable"]
