from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
import pandas as pd
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import and_, case, exists, or_, select, update

from msm.analytics.indices import IndexFormulaDefinition
from msm.api.base import operation_result_rows
from msm.models import IndexFormulaDefinitionTable, IndexFormulaInputTable
from msm.repositories.base import compile_markets_statement, execute_markets_operation
from msm.repositories.crud import (
    create_model,
    delete_model,
    get_model_by_uid,
    search_model,
    update_model,
)


class StoredFormulaInput(BaseModel):
    """Internal relational form of an exact formula source binding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    uid: uuid.UUID
    definition_uid: uuid.UUID
    asset_uid: uuid.UUID | None = None
    component_index_uid: uuid.UUID | None = None
    meta_table_uid: uuid.UUID
    observable: str

    @model_validator(mode="after")
    def _exactly_one_source(self) -> StoredFormulaInput:
        if (self.asset_uid is None) == (self.component_index_uid is None):
            raise ValueError("stored formula input requires exactly one source uid")
        return self


def _utc(value: datetime.datetime | str | pd.Timestamp) -> datetime.datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError("formula lookup timestamps must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


def formula_history(context, *, index_uid: uuid.UUID | str) -> list[IndexFormulaDefinition]:
    result = search_model(
        context,
        model=IndexFormulaDefinitionTable,
        filters={"index_uid": uuid.UUID(str(index_uid))},
        limit=10_000,
    )
    definitions = [
        IndexFormulaDefinition.model_validate(row) for row in operation_result_rows(result)
    ]
    return sorted(definitions, key=lambda definition: definition.version or 0)


def formula_inputs(
    context,
    *,
    definition_uid: uuid.UUID | str,
) -> list[StoredFormulaInput]:
    result = search_model(
        context,
        model=IndexFormulaInputTable,
        filters={"definition_uid": uuid.UUID(str(definition_uid))},
        limit=10_000,
    )
    inputs = [StoredFormulaInput.model_validate(row) for row in operation_result_rows(result)]
    return sorted(inputs, key=lambda item: (str(item.asset_uid or item.component_index_uid), item.observable))


def get_formula_definition(
    context,
    *,
    definition_uid: uuid.UUID | str,
) -> IndexFormulaDefinition | None:
    result = get_model_by_uid(
        context,
        model=IndexFormulaDefinitionTable,
        uid=definition_uid,
    )
    rows = operation_result_rows(result)
    return IndexFormulaDefinition.model_validate(rows[0]) if rows else None


def effective_formula_definition(
    context,
    *,
    index_uid: uuid.UUID | str,
    at: datetime.datetime | str | pd.Timestamp,
) -> IndexFormulaDefinition | None:
    timestamp = _utc(at)
    candidates = [
        definition
        for definition in formula_history(context, index_uid=index_uid)
        if definition.status != "draft"
        and definition.valid_from <= timestamp
        and (definition.valid_to is None or timestamp < definition.valid_to)
    ]
    if len(candidates) > 1:
        raise ValueError("overlapping active Index formula definitions were found")
    return candidates[0] if candidates else None


def next_formula_version(context, *, index_uid: uuid.UUID | str) -> int:
    history = formula_history(context, index_uid=index_uid)
    return max((definition.version or 0 for definition in history), default=0) + 1


def find_formula_by_hash(
    context,
    *,
    index_uid: uuid.UUID | str,
    definition_hash: str,
) -> IndexFormulaDefinition | None:
    result = search_model(
        context,
        model=IndexFormulaDefinitionTable,
        filters={
            "index_uid": uuid.UUID(str(index_uid)),
            "definition_hash": definition_hash,
        },
        limit=2,
    )
    rows = operation_result_rows(result)
    if len(rows) > 1:
        raise ValueError("duplicate formula definition hashes exist for one Index")
    return IndexFormulaDefinition.model_validate(rows[0]) if rows else None


def create_formula_and_inputs(
    context,
    *,
    definition: IndexFormulaDefinition,
    inputs: Sequence[StoredFormulaInput],
) -> tuple[IndexFormulaDefinition, list[StoredFormulaInput]]:
    """Persist one formula version and exact source bindings with compensation."""

    if definition.uid is None or definition.index_uid is None:
        raise ValueError("persisted formula definitions require uid and index_uid")
    created_input_uids: list[uuid.UUID] = []
    definition_created = False
    try:
        result = create_model(
            context,
            model=IndexFormulaDefinitionTable,
            values=definition.model_dump(mode="python", exclude_none=True),
        )
        rows = operation_result_rows(result)
        if not rows:
            raise LookupError("formula definition insert did not return a row")
        persisted_definition = IndexFormulaDefinition.model_validate(rows[0])
        definition_created = True

        persisted_inputs: list[StoredFormulaInput] = []
        for formula_input in inputs:
            result = create_model(
                context,
                model=IndexFormulaInputTable,
                values=formula_input.model_dump(mode="python", exclude_none=True),
            )
            rows = operation_result_rows(result)
            if not rows:
                raise LookupError("formula input insert did not return a row")
            persisted = StoredFormulaInput.model_validate(rows[0])
            persisted_inputs.append(persisted)
            created_input_uids.append(persisted.uid)
        return persisted_definition, persisted_inputs
    except Exception:
        for input_uid in reversed(created_input_uids):
            delete_model(context, model=IndexFormulaInputTable, uid=input_uid)
        if definition_created:
            delete_model(context, model=IndexFormulaDefinitionTable, uid=definition.uid)
        raise


def activate_formula_definition(
    context,
    *,
    definition_uid: uuid.UUID | str,
) -> IndexFormulaDefinition:
    definition = get_formula_definition(context, definition_uid=definition_uid)
    if definition is None:
        raise LookupError(f"formula definition {definition_uid!s} does not exist")
    if definition.status == "active":
        return definition
    if definition.status == "retired":
        raise ValueError("retired Index formula definitions cannot be reactivated")
    history = formula_history(context, index_uid=definition.index_uid)
    previous_active: IndexFormulaDefinition | None = None
    for existing in history:
        if existing.uid == definition.uid or existing.status == "draft":
            continue
        if _intervals_overlap(existing, definition):
            if (
                existing.status == "active"
                and existing.valid_from < definition.valid_from
                and existing.valid_to is None
            ):
                if previous_active is not None:
                    raise ValueError("multiple active Index formula definitions were found")
                previous_active = existing
                continue
            raise ValueError("formula validity overlaps another activated version")
    table = IndexFormulaDefinitionTable.__table__
    target = table.alias("target_formula_definition")
    target_ready = exists(
        select(target.c.uid).where(
            target.c.uid == definition.uid,
            target.c.index_uid == definition.index_uid,
            target.c.status == "draft",
        )
    )
    row_conditions = [
        and_(
            IndexFormulaDefinitionTable.uid == definition.uid,
            IndexFormulaDefinitionTable.status == "draft",
        )
    ]
    readiness = [target_ready]
    if previous_active is not None:
        prior = table.alias("previous_active_formula_definition")
        readiness.append(
            exists(
                select(prior.c.uid).where(
                    prior.c.uid == previous_active.uid,
                    prior.c.index_uid == definition.index_uid,
                    prior.c.status == "active",
                    prior.c.valid_to.is_(None),
                )
            )
        )
        row_conditions.append(
            and_(
                IndexFormulaDefinitionTable.uid == previous_active.uid,
                IndexFormulaDefinitionTable.status == "active",
                IndexFormulaDefinitionTable.valid_to.is_(None),
            )
        )
    statement = (
        update(IndexFormulaDefinitionTable)
        .where(
            IndexFormulaDefinitionTable.index_uid == definition.index_uid,
            *readiness,
            or_(*row_conditions),
        )
        .values(
            status=case(
                (IndexFormulaDefinitionTable.uid == definition.uid, "active"),
                else_="retired",
            ),
            valid_to=case(
                (IndexFormulaDefinitionTable.uid == definition.uid, definition.valid_to),
                else_=definition.valid_from,
            ),
        )
        .returning(IndexFormulaDefinitionTable)
    )
    result = execute_markets_operation(
        compile_markets_statement(
            statement,
            context=context,
            operation="update",
            models=[IndexFormulaDefinitionTable],
            access="write",
        ),
        context=context,
    )
    rows = operation_result_rows(result)
    expected_uids = {definition.uid}
    if previous_active is not None:
        expected_uids.add(previous_active.uid)
    returned_uids = {uuid.UUID(str(row["uid"])) for row in rows}
    if returned_uids != expected_uids:
        raise RuntimeError("formula activation preconditions changed concurrently")
    activated = next(row for row in rows if str(row["uid"]) == str(definition.uid))
    return IndexFormulaDefinition.model_validate(activated)


def retire_formula_definition(
    context,
    *,
    definition_uid: uuid.UUID | str,
    valid_to: datetime.datetime | str | pd.Timestamp | None = None,
) -> IndexFormulaDefinition:
    definition = get_formula_definition(context, definition_uid=definition_uid)
    if definition is None:
        raise LookupError(f"formula definition {definition_uid!s} does not exist")
    timestamp = _utc(valid_to) if valid_to is not None else datetime.datetime.now(datetime.UTC)
    if timestamp <= definition.valid_from:
        raise ValueError("retirement valid_to must be later than valid_from")
    result = update_model(
        context,
        model=IndexFormulaDefinitionTable,
        uid=definition.uid,
        values={"status": "retired", "valid_to": timestamp},
    )
    rows = operation_result_rows(result)
    if not rows:
        raise LookupError("formula retirement did not return a row")
    return IndexFormulaDefinition.model_validate(rows[0])


def validate_no_formula_cycle(
    context,
    *,
    index_uid: uuid.UUID,
    component_index_uids: Sequence[uuid.UUID],
) -> None:
    result = search_model(
        context,
        model=IndexFormulaDefinitionTable,
        in_filters={"status": ["active", "retired"]},
        limit=100_000,
    )
    definitions = [
        IndexFormulaDefinition.model_validate(row) for row in operation_result_rows(result)
    ]
    owners = {
        definition.uid: definition.index_uid
        for definition in definitions
        if definition.uid is not None and definition.index_uid is not None
    }
    existing_inputs: list[StoredFormulaInput] = []
    if owners:
        input_result = search_model(
            context,
            model=IndexFormulaInputTable,
            in_filters={"definition_uid": list(owners)},
            limit=100_000,
        )
        existing_inputs = [
            StoredFormulaInput.model_validate(row) for row in operation_result_rows(input_result)
        ]
    graph: dict[uuid.UUID, set[uuid.UUID]] = {}
    for formula_input in existing_inputs:
        owner = owners.get(formula_input.definition_uid)
        if owner is not None and formula_input.component_index_uid is not None:
            graph.setdefault(owner, set()).add(formula_input.component_index_uid)
    graph[index_uid] = set(component_index_uids)

    visiting: list[uuid.UUID] = []
    visited: set[uuid.UUID] = set()

    def visit(node: uuid.UUID) -> None:
        if node in visiting:
            cycle = [*visiting[visiting.index(node) :], node]
            raise ValueError("Index formula dependency cycle: " + " -> ".join(map(str, cycle)))
        if node in visited:
            return
        visiting.append(node)
        for dependency in graph.get(node, set()):
            visit(dependency)
        visiting.pop()
        visited.add(node)

    visit(index_uid)


def _intervals_overlap(left: IndexFormulaDefinition, right: IndexFormulaDefinition) -> bool:
    maximum = datetime.datetime.max.replace(tzinfo=datetime.UTC)
    return left.valid_from < (right.valid_to or maximum) and right.valid_from < (
        left.valid_to or maximum
    )


__all__ = [
    "StoredFormulaInput",
    "activate_formula_definition",
    "create_formula_and_inputs",
    "effective_formula_definition",
    "find_formula_by_hash",
    "formula_history",
    "formula_inputs",
    "get_formula_definition",
    "next_formula_version",
    "retire_formula_definition",
    "validate_no_formula_cycle",
]
