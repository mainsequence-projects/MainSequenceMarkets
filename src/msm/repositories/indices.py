from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import Any

import pandas as pd

from msm.analytics.indices import IndexCalculationDefinition, IndexCalculationLeg
from msm.api.base import operation_result_rows
from msm.models import IndexCalculationDefinitionTable, IndexCalculationLegTable
from msm.repositories.crud import (
    create_model,
    delete_model,
    get_model_by_uid,
    search_model,
    update_model,
)


def _utc(value: datetime.datetime | str | pd.Timestamp) -> datetime.datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("definition lookup timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


def definition_history(context, *, index_uid: uuid.UUID | str) -> list[IndexCalculationDefinition]:
    result = search_model(
        context,
        model=IndexCalculationDefinitionTable,
        filters={"index_uid": uuid.UUID(str(index_uid))},
        limit=10_000,
    )
    definitions = [
        IndexCalculationDefinition.model_validate(row) for row in operation_result_rows(result)
    ]
    return sorted(definitions, key=lambda definition: definition.definition_version or 0)


def definition_legs(
    context,
    *,
    definition_uid: uuid.UUID | str,
) -> list[IndexCalculationLeg]:
    result = search_model(
        context,
        model=IndexCalculationLegTable,
        filters={"definition_uid": uuid.UUID(str(definition_uid))},
        limit=10_000,
    )
    legs = [IndexCalculationLeg.model_validate(row) for row in operation_result_rows(result)]
    return sorted(legs, key=lambda leg: (leg.leg_order, leg.leg_key))


def get_definition(
    context,
    *,
    definition_uid: uuid.UUID | str,
) -> IndexCalculationDefinition | None:
    result = get_model_by_uid(
        context,
        model=IndexCalculationDefinitionTable,
        uid=definition_uid,
    )
    rows = operation_result_rows(result)
    return IndexCalculationDefinition.model_validate(rows[0]) if rows else None


def effective_definition(
    context,
    *,
    index_uid: uuid.UUID | str,
    at: datetime.datetime | str | pd.Timestamp,
) -> IndexCalculationDefinition | None:
    timestamp = _utc(at)
    candidates = [
        definition
        for definition in definition_history(context, index_uid=index_uid)
        if definition.status != "draft"
        and definition.effective_from <= timestamp
        and (definition.effective_to is None or timestamp < definition.effective_to)
    ]
    if len(candidates) > 1:
        raise ValueError("overlapping effective derived-index definitions were found")
    return candidates[0] if candidates else None


def next_definition_version(context, *, index_uid: uuid.UUID | str) -> int:
    history = definition_history(context, index_uid=index_uid)
    return max((definition.definition_version or 0 for definition in history), default=0) + 1


def find_definition_by_hash(
    context,
    *,
    index_uid: uuid.UUID | str,
    definition_hash: str,
) -> IndexCalculationDefinition | None:
    result = search_model(
        context,
        model=IndexCalculationDefinitionTable,
        filters={
            "index_uid": uuid.UUID(str(index_uid)),
            "definition_hash": definition_hash,
        },
        limit=2,
    )
    rows = operation_result_rows(result)
    if len(rows) > 1:
        raise ValueError("duplicate definition hashes exist for one index")
    return IndexCalculationDefinition.model_validate(rows[0]) if rows else None


def create_definition_and_legs(
    context,
    *,
    definition: IndexCalculationDefinition,
    legs: Sequence[IndexCalculationLeg],
) -> tuple[IndexCalculationDefinition, list[IndexCalculationLeg]]:
    """Persist a definition and its ordered legs with explicit compensating rollback."""

    if definition.uid is None or definition.index_uid is None:
        raise ValueError("persisted definitions require uid and index_uid")
    created_leg_uids: list[uuid.UUID] = []
    definition_created = False
    try:
        definition_payload = definition.model_dump(mode="python", exclude_none=True)
        result = create_model(
            context,
            model=IndexCalculationDefinitionTable,
            values=definition_payload,
        )
        definition_rows = operation_result_rows(result)
        if not definition_rows:
            raise LookupError("definition insert did not return a row")
        persisted_definition = IndexCalculationDefinition.model_validate(definition_rows[0])
        definition_created = True

        persisted_legs: list[IndexCalculationLeg] = []
        for leg in legs:
            leg_payload = leg.model_copy(
                update={
                    "uid": leg.uid or uuid.uuid4(),
                    "definition_uid": persisted_definition.uid,
                }
            )
            leg_result = create_model(
                context,
                model=IndexCalculationLegTable,
                values=leg_payload.model_dump(mode="python", exclude_none=True),
            )
            leg_rows = operation_result_rows(leg_result)
            if not leg_rows:
                raise LookupError(f"leg insert did not return row {leg.leg_key!r}")
            persisted_leg = IndexCalculationLeg.model_validate(leg_rows[0])
            persisted_legs.append(persisted_leg)
            created_leg_uids.append(persisted_leg.uid)
        return persisted_definition, persisted_legs
    except Exception:
        for leg_uid in reversed(created_leg_uids):
            delete_model(context, model=IndexCalculationLegTable, uid=leg_uid)
        if definition_created:
            delete_model(
                context,
                model=IndexCalculationDefinitionTable,
                uid=definition.uid,
            )
        raise


def activate_definition(
    context,
    *,
    definition_uid: uuid.UUID | str,
) -> IndexCalculationDefinition:
    definition = get_definition(context, definition_uid=definition_uid)
    if definition is None:
        raise LookupError(f"definition {definition_uid!s} does not exist")
    if definition.status == "active":
        return definition
    if definition.status == "retired":
        raise ValueError("retired derived-index definitions cannot be reactivated")
    history = definition_history(context, index_uid=definition.index_uid)
    for existing in history:
        if existing.uid == definition.uid or existing.status == "draft":
            continue
        if _intervals_overlap(existing, definition):
            if (
                existing.status == "active"
                and existing.effective_from < definition.effective_from
                and existing.effective_to is None
            ):
                update_model(
                    context,
                    model=IndexCalculationDefinitionTable,
                    uid=existing.uid,
                    values={
                        "status": "retired",
                        "effective_to": definition.effective_from,
                    },
                )
                continue
            raise ValueError(
                "definition effective interval overlaps another activated methodology version"
            )
    result = update_model(
        context,
        model=IndexCalculationDefinitionTable,
        uid=definition.uid,
        values={"status": "active"},
    )
    rows = operation_result_rows(result)
    if not rows:
        raise LookupError("definition activation did not return a row")
    return IndexCalculationDefinition.model_validate(rows[0])


def retire_definition(
    context,
    *,
    definition_uid: uuid.UUID | str,
    effective_to: datetime.datetime | str | pd.Timestamp | None = None,
) -> IndexCalculationDefinition:
    definition = get_definition(context, definition_uid=definition_uid)
    if definition is None:
        raise LookupError(f"definition {definition_uid!s} does not exist")
    timestamp = (
        _utc(effective_to) if effective_to is not None else datetime.datetime.now(datetime.UTC)
    )
    if timestamp <= definition.effective_from:
        raise ValueError("retirement effective_to must be later than effective_from")
    values: dict[str, Any] = {
        "status": "retired",
        "effective_to": timestamp,
    }
    result = update_model(
        context,
        model=IndexCalculationDefinitionTable,
        uid=definition.uid,
        values=values,
    )
    rows = operation_result_rows(result)
    if not rows:
        raise LookupError("definition retirement did not return a row")
    return IndexCalculationDefinition.model_validate(rows[0])


def validate_no_index_cycle(
    context,
    *,
    index_uid: uuid.UUID,
    legs: Sequence[IndexCalculationLeg],
) -> None:
    active_result = search_model(
        context,
        model=IndexCalculationDefinitionTable,
        in_filters={"status": ["active", "retired"]},
        limit=100_000,
    )
    definitions = [
        IndexCalculationDefinition.model_validate(row)
        for row in operation_result_rows(active_result)
    ]
    definition_by_uid = {
        definition.uid: definition for definition in definitions if definition.uid is not None
    }
    existing_legs: list[IndexCalculationLeg] = []
    if definition_by_uid:
        legs_result = search_model(
            context,
            model=IndexCalculationLegTable,
            in_filters={"definition_uid": list(definition_by_uid)},
            limit=100_000,
        )
        existing_legs = [
            IndexCalculationLeg.model_validate(row) for row in operation_result_rows(legs_result)
        ]

    graph: dict[uuid.UUID, set[uuid.UUID]] = {}
    for leg in existing_legs:
        if leg.component_index_uid is None or leg.definition_uid not in definition_by_uid:
            continue
        owner = definition_by_uid[leg.definition_uid].index_uid
        if owner is not None:
            graph.setdefault(owner, set()).add(leg.component_index_uid)
    graph[index_uid] = {
        leg.component_index_uid for leg in legs if leg.component_index_uid is not None
    }

    visiting: list[uuid.UUID] = []
    visited: set[uuid.UUID] = set()

    def visit(node: uuid.UUID) -> None:
        if node in visiting:
            cycle = [*visiting[visiting.index(node) :], node]
            raise ValueError("derived-index dependency cycle: " + " -> ".join(map(str, cycle)))
        if node in visited:
            return
        visiting.append(node)
        for dependency in graph.get(node, set()):
            visit(dependency)
        visiting.pop()
        visited.add(node)

    visit(index_uid)


def _intervals_overlap(
    left: IndexCalculationDefinition,
    right: IndexCalculationDefinition,
) -> bool:
    maximum = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    return left.effective_from < (right.effective_to or maximum) and right.effective_from < (
        left.effective_to or maximum
    )


__all__ = [
    "activate_definition",
    "create_definition_and_legs",
    "definition_history",
    "definition_legs",
    "effective_definition",
    "find_definition_by_hash",
    "get_definition",
    "next_definition_version",
    "retire_definition",
    "validate_no_index_cycle",
]
