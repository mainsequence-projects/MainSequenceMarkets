from __future__ import annotations

import datetime
import uuid
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import pandas as pd
from mainsequence.client.metatables import MetaTable
from pydantic import BaseModel, ConfigDict

from msm.analytics.indices import (
    IndexFormulaDefinition,
    IndexFormulaInput,
    IndexFormulaResult,
    calculate_formula_index,
    compute_formula_definition_hash,
    validate_formula_contract,
)
from msm.models import (
    AssetTable,
    IndexDatasetAvailabilityTable,
    IndexFormulaDefinitionTable,
    IndexFormulaInputTable,
    IndexTable,
    IndexTypeTable,
)
from msm.repositories.crud import delete_model
from msm.repositories.indices import (
    StoredFormulaInput,
    activate_formula_definition,
    create_formula_and_inputs,
    effective_formula_definition,
    find_formula_by_hash,
    formula_history,
    formula_inputs,
    get_formula_definition,
    next_formula_version,
    retire_formula_definition,
    validate_no_formula_cycle,
)

if TYPE_CHECKING:
    from msm.api.indices import Index


_NUMERIC_DATA_TYPES = {
    "int16",
    "int32",
    "int64",
    "smallint",
    "integer",
    "bigint",
    "float32",
    "float64",
    "float",
    "real",
    "double",
    "double precision",
    "numeric",
    "decimal",
}


class FormulaIndex(BaseModel):
    """Canonical Index identity with one persisted formula version and its inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: Index
    definition: IndexFormulaDefinition
    inputs: tuple[IndexFormulaInput, ...]

    @classmethod
    def start_engine(cls, **kwargs: Any):
        from msm.bootstrap import start_engine

        requested = list(kwargs.pop("models", None) or [])
        return start_engine(
            models=[
                AssetTable,
                IndexTypeTable,
                IndexTable,
                IndexDatasetAvailabilityTable,
                IndexFormulaDefinitionTable,
                IndexFormulaInputTable,
                *requested,
            ],
            **kwargs,
        )

    @classmethod
    def _active_context(cls):
        from msm.bootstrap import resolve_runtime

        return resolve_runtime(
            models=[
                AssetTable,
                IndexTypeTable,
                IndexTable,
                IndexDatasetAvailabilityTable,
                IndexFormulaDefinitionTable,
                IndexFormulaInputTable,
            ],
            row_model_name=cls.__name__,
        ).context

    @classmethod
    def upsert(
        cls,
        *,
        unique_identifier: str,
        index_type: str,
        display_name: str,
        definition: IndexFormulaDefinition | Mapping[str, Any],
        inputs: Sequence[IndexFormulaInput | Mapping[str, Any]],
        value_format: str,
        value_suffix: str | None = None,
        description: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> FormulaIndex:
        """Persist an idempotent Formula Index and exact source table bindings."""

        typed_definition = (
            definition
            if isinstance(definition, IndexFormulaDefinition)
            else IndexFormulaDefinition.model_validate(definition)
        )
        typed_inputs = tuple(
            item if isinstance(item, IndexFormulaInput) else IndexFormulaInput.model_validate(item)
            for item in inputs
        )
        validate_formula_contract(typed_definition, typed_inputs)

        from msm.api.assets import Asset
        from msm.api.indices import Index

        context = cls._active_context()
        target = Index.get_by_unique_identifier(unique_identifier)
        if target is not None and target.calculation_method != "formula":
            raise ValueError(
                f"Index {unique_identifier!r} uses calculation_method='custom' and cannot own formulas"
            )
        resolved_sources: list[tuple[IndexFormulaInput, uuid.UUID | None, uuid.UUID | None]] = []
        component_index_uids: list[uuid.UUID] = []
        for formula_input in typed_inputs:
            _validate_source_meta_table(context, formula_input)
            reference = formula_input.source_reference
            if reference.type == "asset":
                source = Asset.get_by_unique_identifier(reference.identifier)
                if source is None:
                    raise LookupError(f"formula Asset source {reference.identifier!r} was not found")
                resolved_sources.append((formula_input, source.uid, None))
            else:
                if reference.identifier == unique_identifier:
                    raise ValueError("an Index formula cannot reference its own Index identity")
                source = Index.get_by_unique_identifier(reference.identifier)
                if source is None:
                    raise LookupError(f"formula Index source {reference.identifier!r} was not found")
                component_index_uids.append(source.uid)
                resolved_sources.append((formula_input, None, source.uid))

        identity_created = False
        if target is None:
            target = Index.create(
                unique_identifier=unique_identifier,
                index_type=index_type,
                display_name=display_name,
                calculation_method="formula",
                value_format=value_format,
                value_suffix=value_suffix,
                description=description,
                metadata_json=metadata_json,
            )
            identity_created = True
        validate_no_formula_cycle(
            context,
            index_uid=target.uid,
            component_index_uids=component_index_uids,
        )

        definition_uid = typed_definition.uid or uuid.uuid4()
        draft = typed_definition.model_copy(
            update={
                "uid": definition_uid,
                "index_uid": target.uid,
                "version": typed_definition.version or 1,
                "status": "draft",
                "definition_hash": None,
            }
        )
        digest = compute_formula_definition_hash(draft, typed_inputs)
        existing = find_formula_by_hash(
            context,
            index_uid=target.uid,
            definition_hash=digest,
        )
        if existing is not None:
            target = Index.upsert(
                unique_identifier=unique_identifier,
                index_type=index_type,
                display_name=display_name,
                calculation_method="formula",
                value_format=value_format,
                value_suffix=value_suffix,
                description=description,
                metadata_json=metadata_json,
            )
            return cls._from_stored(target, existing, context=context)

        expected_version = next_formula_version(context, index_uid=target.uid)
        version = typed_definition.version or expected_version
        if version != expected_version:
            if identity_created:
                delete_model(context, model=IndexTable, uid=target.uid)
            raise ValueError(f"formula version must be the next monotonic version {expected_version}")
        draft = draft.model_copy(update={"version": version, "definition_hash": digest})
        stored_inputs = tuple(
            StoredFormulaInput(
                uid=uuid.uuid4(),
                definition_uid=definition_uid,
                asset_uid=asset_uid,
                component_index_uid=component_index_uid,
                meta_table_uid=formula_input.meta_table_uid,
                observable=formula_input.observable,
            )
            for formula_input, asset_uid, component_index_uid in resolved_sources
        )
        persisted: IndexFormulaDefinition | None = None
        try:
            persisted, _ = create_formula_and_inputs(
                context,
                definition=draft,
                inputs=stored_inputs,
            )
            if typed_definition.status == "active":
                persisted = activate_formula_definition(context, definition_uid=persisted.uid)
            elif typed_definition.status == "retired":
                persisted = retire_formula_definition(
                    context,
                    definition_uid=persisted.uid,
                    valid_to=typed_definition.valid_to,
                )
            target = Index.upsert(
                unique_identifier=unique_identifier,
                index_type=index_type,
                display_name=display_name,
                calculation_method="formula",
                value_format=value_format,
                value_suffix=value_suffix,
                description=description,
                metadata_json=metadata_json,
            )
            return cls(index=target, definition=persisted, inputs=typed_inputs)
        except Exception:
            if persisted is not None and persisted.uid is not None:
                for stored in formula_inputs(context, definition_uid=persisted.uid):
                    delete_model(context, model=IndexFormulaInputTable, uid=stored.uid)
                delete_model(context, model=IndexFormulaDefinitionTable, uid=persisted.uid)
            if identity_created:
                delete_model(context, model=IndexTable, uid=target.uid)
            raise

    @classmethod
    def get_by_identifier(
        cls,
        unique_identifier: str,
        *,
        at: datetime.datetime | str | pd.Timestamp | None = None,
    ) -> FormulaIndex | None:
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
    ) -> FormulaIndex | None:
        from msm.api.indices import Index

        index = Index.get_by_uid(index_uid)
        if index is None:
            return None
        if index.calculation_method != "formula":
            return None
        context = cls._active_context()
        definition = effective_formula_definition(
            context,
            index_uid=index.uid,
            at=at or datetime.datetime.now(datetime.UTC),
        )
        return None if definition is None else cls._from_stored(index, definition, context=context)

    @classmethod
    def get_by_definition_uid(
        cls,
        definition_uid: uuid.UUID | str,
    ) -> FormulaIndex | None:
        from msm.api.indices import Index

        context = cls._active_context()
        definition = get_formula_definition(context, definition_uid=definition_uid)
        if definition is None:
            return None
        index = Index.get_by_uid(definition.index_uid)
        if index is None:
            raise LookupError(f"formula definition {definition_uid!s} references a missing Index")
        return cls._from_stored(index, definition, context=context)

    @classmethod
    def history(cls, index_uid: uuid.UUID | str) -> tuple[IndexFormulaDefinition, ...]:
        return tuple(formula_history(cls._active_context(), index_uid=index_uid))

    def calculate(
        self,
        observations: Mapping[Any, pd.Series | pd.DataFrame],
        *,
        times: Sequence[Any] | pd.DatetimeIndex | None = None,
    ) -> IndexFormulaResult:
        return calculate_formula_index(
            index_identifier=self.index.unique_identifier,
            definition=self.definition,
            inputs=self.inputs,
            observations=observations,
            times=times,
        )

    def calculate_from_sources(
        self,
        *,
        start: datetime.datetime | str | pd.Timestamp,
        end: datetime.datetime | str | pd.Timestamp,
        times: Sequence[Any] | pd.DatetimeIndex | None = None,
    ) -> IndexFormulaResult:
        """Read the pinned MetaTables over one bounded interval and calculate."""

        from mainsequence.meta_tables import APIDataNode

        start_at = _utc_boundary(start, field="start")
        end_at = _utc_boundary(end, field="end")
        if end_at <= start_at:
            raise ValueError("end must be later than start")
        source_start = start_at
        if self.definition.alignment_policy == "asof":
            staleness = float(
                (self.definition.alignment_parameters_json or {})[
                    "max_staleness_seconds"
                ]
            )
            source_start -= datetime.timedelta(seconds=staleness)

        context = self._active_context()
        observations: dict[Any, pd.DataFrame] = {}
        for formula_input in self.inputs:
            meta_table = _validate_source_meta_table(context, formula_input)
            identity_column = (
                "asset_identifier"
                if formula_input.source_reference.type == "asset"
                else "index_identifier"
            )
            dependency = APIDataNode.build_from_meta_table(meta_table)
            frame = dependency.get_df_between_dates(
                start_date=source_start,
                end_date=end_at,
                dimension_filters={
                    identity_column: [formula_input.source_reference.identifier],
                },
                columns=["time_index", identity_column, formula_input.observable],
            )
            flat = frame.reset_index() if "time_index" in frame.index.names else frame.copy()
            required = {"time_index", identity_column, formula_input.observable}
            missing = required - set(flat.columns)
            if missing:
                raise ValueError(
                    f"formula source {formula_input.meta_table_uid!s} is missing columns "
                    f"{sorted(missing)}"
                )
            selected = flat.loc[
                flat[identity_column].astype(str)
                == formula_input.source_reference.identifier,
                ["time_index", formula_input.observable],
            ].copy()
            selected["time_index"] = pd.to_datetime(selected["time_index"], utc=True)
            observations[formula_input.reference] = selected.set_index("time_index")

        result = self.calculate(observations, times=times)
        values = result.values
        timestamps = pd.to_datetime(values["time_index"], utc=True)
        values = values.loc[(timestamps >= start_at) & (timestamps < end_at)].reset_index(drop=True)
        return IndexFormulaResult(values=values)

    def activate(self) -> FormulaIndex:
        """Activate this draft and retire the open predecessor atomically."""

        if self.definition.uid is None:
            raise ValueError("persisted formula definition uid is required")
        definition = activate_formula_definition(
            self._active_context(),
            definition_uid=self.definition.uid,
        )
        return self.model_copy(update={"definition": definition})

    def retire(
        self,
        *,
        valid_to: datetime.datetime | str | pd.Timestamp | None = None,
    ) -> FormulaIndex:
        """Retire this formula version at an exclusive validity boundary."""

        if self.definition.uid is None:
            raise ValueError("persisted formula definition uid is required")
        definition = retire_formula_definition(
            self._active_context(),
            definition_uid=self.definition.uid,
            valid_to=valid_to,
        )
        return self.model_copy(update={"definition": definition})

    @classmethod
    def _from_stored(cls, index: Index, definition: IndexFormulaDefinition, *, context) -> FormulaIndex:
        from msm.api.assets import Asset
        from msm.api.indices import Index

        public_inputs: list[IndexFormulaInput] = []
        for stored in formula_inputs(context, definition_uid=definition.uid):
            if stored.asset_uid is not None:
                source = Asset.get_by_uid(stored.asset_uid)
                source_type = "asset"
            else:
                source = Index.get_by_uid(stored.component_index_uid)
                source_type = "index"
            if source is None:
                raise LookupError(f"formula input {stored.uid} references a missing {source_type}")
            public_inputs.append(
                IndexFormulaInput.model_validate(
                    {
                        "source_reference": {
                            "type": source_type,
                            "identifier": source.unique_identifier,
                        },
                        "meta_table_uid": stored.meta_table_uid,
                        "observable": stored.observable,
                    }
                )
            )
        return cls(index=index, definition=definition, inputs=tuple(public_inputs))


def _validate_source_meta_table(context, formula_input: IndexFormulaInput) -> MetaTable:
    meta_table = MetaTable.get_by_uid(str(formula_input.meta_table_uid))
    if meta_table is None:
        raise LookupError(f"formula source MetaTable {formula_input.meta_table_uid!s} was not found")
    if meta_table.time_indexed is not True:
        raise ValueError("formula source MetaTable must be time-indexed")
    columns = {column.name: column for column in meta_table.columns}
    observable = columns.get(formula_input.observable)
    if observable is None:
        raise ValueError(
            f"formula source MetaTable is missing observable {formula_input.observable!r}"
        )
    if not _is_numeric_data_type(observable.data_type):
        raise ValueError(f"formula observable {formula_input.observable!r} must be numeric")
    source_type = formula_input.source_reference.type
    source_column = "asset_identifier" if source_type == "asset" else "index_identifier"
    if source_column not in columns:
        raise ValueError(f"formula source MetaTable is missing {source_column!r}")
    target_model = AssetTable if source_type == "asset" else IndexTable
    target_uid = context.meta_table_uid_for_model(target_model)
    if not any(
        foreign_key.source_columns == [source_column]
        and str(foreign_key.target_table_uid) == str(target_uid)
        and foreign_key.target_columns == ["unique_identifier"]
        for foreign_key in meta_table.foreign_keys
    ):
        raise ValueError(
            f"formula source MetaTable must declare {source_column} as a foreign key to "
            f"{source_type}.unique_identifier"
        )
    time_index_name = getattr(meta_table, "time_index_name", None)
    index_names = tuple(getattr(meta_table, "index_names", ()) or ())
    if time_index_name != "time_index" or index_names != ("time_index", source_column):
        raise ValueError(
            "formula source MetaTable grain must be exactly "
            f"('time_index', {source_column!r})"
        )
    return meta_table


def _utc_boundary(
    value: datetime.datetime | str | pd.Timestamp,
    *,
    field: str,
) -> datetime.datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _is_numeric_data_type(value: Any) -> bool:
    normalized = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    return normalized in _NUMERIC_DATA_TYPES or normalized.startswith(("numeric(", "decimal("))


__all__ = ["FormulaIndex"]
