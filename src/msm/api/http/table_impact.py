"""MetaTables table-impact contract: what a row action reaches through foreign keys."""

from __future__ import annotations

from pydantic import Field

from ._base import HttpContractModel


class _TableImpactModel(HttpContractModel):
    # MetaTables owns this shape; drop fields that newer MetaTables releases add.
    model_config = HttpContractModel.model_config | {"extra": "ignore"}


class TableImpactNode(_TableImpactModel):
    """A table, unregistered relation, update or hidden table the action reaches."""

    id: str
    type: str = Field(description="meta_table, relation, update or hidden.")
    uid: str | None = None
    identifier: str | None = None
    namespace: str | None = None
    table_kind: str | None = None
    physical_schema: str | None = None
    physical_table_name: str | None = None
    output_table_uid: str | None = None
    effects: list[str] = Field(
        default_factory=list,
        description="What the action does here: drop, delete, update or input_changed.",
    )
    can_write: bool | None = Field(
        default=None,
        description="Whether the caller may write this table; null for updates.",
    )


class TableImpactEdge(_TableImpactModel):
    """Points from the dependent (referencing table or reading update) to what it depends on."""

    source: str
    target: str
    kind: str = Field(description="foreign_key, alembic_version or reads.")
    effect: str = Field(
        description=(
            "cascade_delete, cascade_update, set_null, set_default, restrict "
            "(fails while referencing rows exist), drop or reads."
        )
    )
    name: str | None = None
    on_delete: str | None = None
    on_update: str | None = None


class TableImpactBlocker(_TableImpactModel):
    """A reason MetaTables gives for refusing the action, and the node it concerns."""

    code: str
    message: str
    node: str | None = None


class TableImpact(_TableImpactModel):
    """MetaTables' answer to what an action on a table reaches and whether it may run."""

    root_uid: str
    action: str = Field(description="delete_rows, update_keys or drop_table.")
    allowed: bool
    nodes: list[TableImpactNode]
    edges: list[TableImpactEdge]
    blockers: list[TableImpactBlocker]


__all__ = [
    "TableImpact",
    "TableImpactBlocker",
    "TableImpactEdge",
    "TableImpactNode",
]
