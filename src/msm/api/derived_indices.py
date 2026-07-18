from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd
from pydantic import BaseModel, ConfigDict

from msm.analytics.indices import (
    IndexCalculationDefinition,
    IndexCalculationLeg,
    IndexCalculationResult,
    calculate_index,
    compute_definition_hash,
    validate_calculation_contract,
)
from msm.constants import INDEX_TYPE_DERIVED, INDEX_TYPE_DERIVED_DEFINITION
from msm.models import (
    IndexCalculationDefinitionTable,
    IndexCalculationLegTable,
    IndexTable,
    IndexTypeTable,
)
from msm.repositories.crud import delete_model, update_model
from msm.repositories.indices import (
    activate_definition,
    create_definition_and_legs,
    definition_history,
    definition_legs,
    effective_definition,
    find_definition_by_hash,
    next_definition_version,
    retire_definition,
    validate_no_index_cycle,
)

if TYPE_CHECKING:
    from msm.api.indices import Index


class DerivedIndex(BaseModel):
    """Canonical Index identity together with one persisted calculation version and legs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: Index
    definition: IndexCalculationDefinition
    legs: tuple[IndexCalculationLeg, ...]

    @classmethod
    def start_engine(cls, **kwargs: Any):
        from msm.bootstrap import start_engine

        requested = list(kwargs.pop("models", None) or [])
        return start_engine(
            models=[
                IndexTypeTable,
                IndexTable,
                IndexCalculationDefinitionTable,
                IndexCalculationLegTable,
                *requested,
            ],
            **kwargs,
        )

    @classmethod
    def _active_context(cls):
        from msm.bootstrap import resolve_runtime

        return resolve_runtime(
            models=[
                IndexTypeTable,
                IndexTable,
                IndexCalculationDefinitionTable,
                IndexCalculationLegTable,
            ],
            row_model_name=cls.__name__,
        ).context

    @classmethod
    def upsert(
        cls,
        *,
        unique_identifier: str,
        display_name: str,
        definition: IndexCalculationDefinition | Mapping[str, Any],
        legs: Sequence[IndexCalculationLeg | Mapping[str, Any]],
        description: str | None = None,
        provider: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> DerivedIndex:
        """Persist an idempotent derived index with explicit compensating rollback."""

        typed_definition = (
            definition
            if isinstance(definition, IndexCalculationDefinition)
            else IndexCalculationDefinition.model_validate(definition)
        )
        from msm.api.indices import Index, IndexType

        typed_legs = tuple(
            leg if isinstance(leg, IndexCalculationLeg) else IndexCalculationLeg.model_validate(leg)
            for leg in legs
        )
        validate_calculation_contract(typed_definition, typed_legs)

        context = cls._active_context()
        existing_index = Index.get_by_unique_identifier(unique_identifier)
        existing_snapshot = existing_index.model_dump(mode="python") if existing_index else None
        index_created = existing_index is None
        persisted_definition: IndexCalculationDefinition | None = None
        try:
            IndexType.upsert(INDEX_TYPE_DERIVED_DEFINITION.as_payload())
            index = Index.upsert(
                unique_identifier=unique_identifier,
                index_type=INDEX_TYPE_DERIVED,
                display_name=display_name,
                description=description,
                provider=provider,
                metadata_json=metadata_json,
            )
            validate_no_index_cycle(context, index_uid=index.uid, legs=typed_legs)

            definition_uid = typed_definition.uid or uuid.uuid4()
            draft_definition = typed_definition.model_copy(
                update={
                    "uid": definition_uid,
                    "index_uid": index.uid,
                    "definition_version": typed_definition.definition_version or 1,
                    "status": "draft",
                    "definition_hash": None,
                }
            )
            definition_hash = compute_definition_hash(draft_definition, list(typed_legs))
            existing_definition = find_definition_by_hash(
                context,
                index_uid=index.uid,
                definition_hash=definition_hash,
            )
            if existing_definition is not None:
                return cls(
                    index=index,
                    definition=existing_definition,
                    legs=tuple(definition_legs(context, definition_uid=existing_definition.uid)),
                )

            expected_version = next_definition_version(context, index_uid=index.uid)
            version = typed_definition.definition_version or expected_version
            if version != expected_version:
                raise ValueError(
                    f"definition_version must be the next monotonic version {expected_version}"
                )
            draft_definition = draft_definition.model_copy(
                update={
                    "definition_version": version,
                    "definition_hash": definition_hash,
                }
            )
            persisted_definition, persisted_legs = create_definition_and_legs(
                context,
                definition=draft_definition,
                legs=typed_legs,
            )
            if typed_definition.status == "active":
                persisted_definition = activate_definition(
                    context,
                    definition_uid=persisted_definition.uid,
                )
            elif typed_definition.status == "retired":
                persisted_definition = retire_definition(
                    context,
                    definition_uid=persisted_definition.uid,
                    effective_to=typed_definition.effective_to,
                )
            return cls(
                index=index,
                definition=persisted_definition,
                legs=tuple(persisted_legs),
            )
        except Exception:
            if persisted_definition is not None and persisted_definition.uid is not None:
                for leg in definition_legs(context, definition_uid=persisted_definition.uid):
                    if leg.uid is not None:
                        delete_model(context, model=IndexCalculationLegTable, uid=leg.uid)
                delete_model(
                    context,
                    model=IndexCalculationDefinitionTable,
                    uid=persisted_definition.uid,
                )
            if index_created:
                current = Index.get_by_unique_identifier(unique_identifier)
                if current is not None:
                    Index.delete(current.uid)
            elif existing_snapshot is not None:
                restore = {key: value for key, value in existing_snapshot.items() if key != "uid"}
                update_model(
                    context,
                    model=IndexTable,
                    uid=existing_snapshot["uid"],
                    values=restore,
                )
            raise

    @classmethod
    def get_by_identifier(
        cls,
        unique_identifier: str,
        *,
        at: datetime.datetime | str | pd.Timestamp | None = None,
    ) -> DerivedIndex | None:
        from msm.api.indices import Index

        index = Index.get_by_unique_identifier(unique_identifier)
        if index is None:
            return None
        return cls.get_by_index_uid(index.uid, at=at)

    @classmethod
    def get_by_index_uid(
        cls,
        index_uid: uuid.UUID | str,
        *,
        at: datetime.datetime | str | pd.Timestamp | None = None,
    ) -> DerivedIndex | None:
        from msm.api.indices import Index

        index = Index.get_by_uid(index_uid)
        if index is None:
            return None
        context = cls._active_context()
        lookup_time = at or datetime.datetime.now(datetime.UTC)
        definition = effective_definition(context, index_uid=index.uid, at=lookup_time)
        if definition is None:
            return None
        return cls(
            index=index,
            definition=definition,
            legs=tuple(definition_legs(context, definition_uid=definition.uid)),
        )

    @classmethod
    def definition_history(
        cls,
        index_uid: uuid.UUID | str,
    ) -> list[IndexCalculationDefinition]:
        return definition_history(cls._active_context(), index_uid=index_uid)

    def activate(self) -> DerivedIndex:
        definition = activate_definition(
            self._active_context(),
            definition_uid=self.definition.uid,
        )
        return self.model_copy(update={"definition": definition})

    def retire(
        self,
        *,
        effective_to: datetime.datetime | str | pd.Timestamp | None = None,
    ) -> DerivedIndex:
        definition = retire_definition(
            self._active_context(),
            definition_uid=self.definition.uid,
            effective_to=effective_to,
        )
        return self.model_copy(update={"definition": definition})

    def calculate(
        self,
        observations: Mapping[str, pd.Series | pd.DataFrame],
        *,
        calculation_times: Sequence[Any] | pd.DatetimeIndex | None = None,
        resolved_coefficients: Mapping[str, pd.Series | float] | None = None,
        resolved_coefficient_source_times: Mapping[str, pd.Series] | None = None,
        coefficient_inputs: Mapping[str, pd.Series] | None = None,
    ) -> IndexCalculationResult:
        return calculate_index(
            self.definition,
            self.legs,
            observations,
            index_identifier=self.index.unique_identifier,
            calculation_times=calculation_times,
            resolved_coefficients=resolved_coefficients,
            resolved_coefficient_source_times=resolved_coefficient_source_times,
            coefficient_inputs=coefficient_inputs,
        )


__all__ = ["DerivedIndex"]
