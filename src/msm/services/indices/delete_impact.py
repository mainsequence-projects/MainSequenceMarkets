from __future__ import annotations

from msm.api.indices import Index
from msm.repositories.base import MarketsOperationContext

from .catalog import list_related_meta_tables
from .contracts import IndexDeleteImpact, IndexDeleteImpactRelationship, RelatedMetaTable


def get_index_delete_impact(
    context: MarketsOperationContext,
    *,
    index: Index,
) -> IndexDeleteImpact:
    """Describe the effects of ordinary direct deletion without authorizing it."""

    relationships = tuple(
        _normalize_relationship(item)
        for item in list_related_meta_tables(
            context,
            index=index,
            numeric=False,
            timestamped=False,
        )
    )
    unavailable_blockers = [
        item for item in relationships if item.blocks_delete and item.count is None
    ]
    blocking_count = sum(
        item.count or 0 for item in relationships if item.blocks_delete and item.count is not None
    )
    warnings = []
    if unavailable_blockers:
        warnings.append(
            "At least one restrictive relationship count is unavailable; deletion is "
            "conservatively reported as blocked."
        )
    return IndexDeleteImpact(
        uid=index.uid,
        identifier=index.unique_identifier,
        display_name=index.display_name,
        can_delete=not any(item.blocks_delete for item in relationships),
        blocking_count=blocking_count,
        affected_count=sum(item.count or 0 for item in relationships),
        delete_endpoint=f"/api/v1/index/{index.uid}/",
        relationships=relationships,
        warnings=tuple(warnings),
    )


def _normalize_relationship(item: RelatedMetaTable) -> IndexDeleteImpactRelationship:
    action = str(item.on_delete).upper().replace("_", " ")
    if action not in {"RESTRICT", "NO ACTION", "CASCADE", "SET NULL", "APPLICATION"}:
        action = "UNKNOWN"
    count_accuracy = "exact" if item.count is not None else "unavailable"
    count = item.count

    if action in {"RESTRICT", "NO ACTION"} and (count is None or count > 0):
        effect = "blocks_delete"
        severity = "blocking" if count is not None else "warning"
        blocks_delete = True
    elif count == 0:
        effect = "informational"
        severity = "info"
        blocks_delete = False
    elif action == "CASCADE":
        effect = "cascade_delete"
        severity = "destructive"
        blocks_delete = False
    elif action == "SET NULL":
        effect = "set_null"
        severity = "mutating"
        blocks_delete = False
    else:
        effect = "informational"
        severity = "warning"
        blocks_delete = False

    relationship_type = item.relationship_type
    if relationship_type not in {"direct", "indirect", "derived"}:
        relationship_type = "direct" if item.authoritative else "indirect"
    description = item.confidence_reason or (
        "Authoritative declared Index relationship."
        if item.authoritative
        else "Inferred relationship; deletion behavior is not owned by the Index service."
    )
    return IndexDeleteImpactRelationship(
        key=item.key,
        label=item.label,
        model=item.identifier,
        column=item.join_column or "indirect",
        relationship_type=relationship_type,
        on_delete=action,
        count=count,
        count_accuracy=count_accuracy,
        effect=effect,
        severity=severity,
        blocks_delete=blocks_delete,
        description=description,
    )


__all__ = ["get_index_delete_impact"]
