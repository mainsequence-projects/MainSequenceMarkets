"""MetaTables delete impact, rendered as bulk-delete preflight warnings and blockers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger

from msm.api.http import TableImpact, TableImpactEdge, TableImpactNode

logger = _mainsequence_logger.bind(sub_application="markets", component="table_impact")

IMPACT_UNAVAILABLE_WARNING = (
    "MetaTables could not report which tables this delete reaches through foreign keys. "
    "The database still applies every foreign-key action when the rows are deleted."
)

# What a foreign-key action does to the referencing rows, by MetaTables edge effect.
_REFERENCING_ROW_OUTCOMES = {
    "cascade_delete": "are deleted too",
    "cascade_update": "are updated too",
    "set_null": "have that reference set to NULL",
    "set_default": "have that reference reset to its default",
}
# The edge effect each ON DELETE action produces; any other effect follows ON UPDATE.
_ON_DELETE_EFFECTS = {
    "cascade": "cascade_delete",
    "set null": "set_null",
    "set default": "set_default",
}


@dataclass(frozen=True)
class DeleteRowsImpact:
    """MetaTables' delete impact with the preflight warnings and blockers it implies."""

    impact: TableImpact | None
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)


def delete_rows_impact(model: type[Any]) -> DeleteRowsImpact:
    """Ask MetaTables what deleting rows from ``model``'s table reaches.

    Each foreign-key action the delete triggers (cascades, SET NULL, SET DEFAULT)
    becomes a warning, and each reason MetaTables gives for refusing the delete
    becomes a blocker. The impact is advisory: the database enforces the same rules
    when the rows are deleted, so an unavailable impact only adds a warning.
    """

    meta_table = model.get_meta_table()
    if meta_table is None:
        logger.warning("MetaTables delete impact skipped: model is not bound", model=model.__name__)
        return DeleteRowsImpact(impact=None, warnings=[IMPACT_UNAVAILABLE_WARNING])
    try:
        impact = TableImpact.model_validate(
            meta_table.get_impact(action="delete_rows").model_dump(mode="json")
        )
    except Exception:
        logger.exception("MetaTables delete impact failed", model=model.__name__)
        return DeleteRowsImpact(impact=None, warnings=[IMPACT_UNAVAILABLE_WARNING])

    nodes = {node.id: node for node in impact.nodes}
    warnings = [
        _foreign_key_warning(edge, nodes)
        for edge in impact.edges
        if edge.kind == "foreign_key" and edge.effect in _REFERENCING_ROW_OUTCOMES
    ]
    blockers = [
        f"{_label(nodes.get(blocker.node), sentence_start=True)}: {blocker.message}"
        if blocker.node
        else blocker.message
        for blocker in impact.blockers
    ]
    return DeleteRowsImpact(
        impact=impact,
        warnings=list(dict.fromkeys(warnings)),
        blockers=blockers,
    )


def _foreign_key_warning(edge: TableImpactEdge, nodes: dict[str, TableImpactNode]) -> str:
    # Edges point from the referencing table (source) to the table it references.
    source = nodes.get(edge.source)
    target = nodes.get(edge.target)
    deleted = (
        target is not None
        and "delete" in target.effects
        and _ON_DELETE_EFFECTS.get((edge.on_delete or "").lower()) == edge.effect
    )
    action = edge.on_delete if deleted else edge.on_update
    clause = f" (ON {'DELETE' if deleted else 'UPDATE'} {action.upper()})" if action else ""
    return (
        f"{_rows(source, sentence_start=True)} that reference "
        f"{'deleted' if deleted else 'changed'} {_rows(target)} "
        f"{_REFERENCING_ROW_OUTCOMES[edge.effect]}{clause}."
    )


def _rows(node: TableImpactNode | None, *, sentence_start: bool = False) -> str:
    if node is None or node.type == "hidden":
        return f"{'R' if sentence_start else 'r'}ows in a table you cannot view"
    return f"{_label(node)} rows"


def _label(node: TableImpactNode | None, *, sentence_start: bool = False) -> str:
    # Hidden tables are opaque: MetaTables reports that they are affected, not which.
    if node is None or node.type == "hidden":
        return f"{'A' if sentence_start else 'a'} table you cannot view"
    if node.identifier:
        return node.identifier
    if node.physical_table_name:
        schema = f"{node.physical_schema}." if node.physical_schema else ""
        return f"{schema}{node.physical_table_name}"
    return node.id


__all__ = [
    "IMPACT_UNAVAILABLE_WARNING",
    "DeleteRowsImpact",
    "delete_rows_impact",
]
