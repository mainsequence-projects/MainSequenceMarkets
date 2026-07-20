from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

RelationshipType = Literal["direct", "indirect", "derived"]
OnDeleteAction = Literal["RESTRICT", "NO ACTION", "CASCADE", "SET NULL", "APPLICATION", "UNKNOWN"]
DeleteImpactEffect = Literal[
    "blocks_delete",
    "blocks_cascade",
    "cascade_delete",
    "set_null",
    "delete_cleanup",
    "manual_cleanup_required",
    "informational",
]
DeleteImpactSeverity = Literal["blocking", "destructive", "mutating", "warning", "info"]


class DeleteImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_samples: bool = False
    sample_limit: int = Field(default=0, ge=0, le=100)


class DeleteImpactRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    model: str
    column: str
    relationship_type: RelationshipType
    on_delete: OnDeleteAction
    count: int | None = Field(default=None, ge=0)
    count_accuracy: Literal["exact", "unavailable"] = "exact"
    effect: DeleteImpactEffect
    severity: DeleteImpactSeverity
    blocks_delete: bool
    description: str


class DeleteImpactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_type: str
    uid: UUID
    identifier: str | None = None
    display_name: str | None = None
    can_delete: bool
    blocking_count: int = Field(ge=0)
    affected_count: int = Field(ge=0)
    delete_endpoint: str
    relationships: list[DeleteImpactRelationship]
    warnings: list[str] = Field(default_factory=list)
