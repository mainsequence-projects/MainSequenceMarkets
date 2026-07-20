from __future__ import annotations

import datetime
import uuid
from collections.abc import Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import Field, model_validator
import sqlalchemy as sa

from mainsequence.meta_tables import APIDataNode, PlatformTimeIndexMetaTable

from msm.analytics.indices import IndexFormulaError
from msm.api.formula_indices import FormulaIndex
from msm.api.indices import Index
from msm.data_nodes.indices.storage import require_cadenced_index_values_storage
from msm.data_nodes.indices.timestamped import IndexDataNodeConfiguration, IndexTimestampedDataNode
from msm.data_nodes.indices.values import index_identifiers_in_frame
from msm.data_nodes.utils.stamped import normalize_stamped_frame


class FormulaIndexDataNodeConfiguration(IndexDataNodeConfiguration):
    """Immutable formula versions and exact registered source storage classes."""

    formula_definition_uids: tuple[uuid.UUID, ...] = Field(..., min_length=1)
    source_storage_tables: tuple[type[PlatformTimeIndexMetaTable], ...] = Field(
        ...,
        min_length=1,
    )

    @model_validator(mode="after")
    def _unique_configuration(self) -> FormulaIndexDataNodeConfiguration:
        if len(set(self.formula_definition_uids)) != len(self.formula_definition_uids):
            raise ValueError("formula_definition_uids must be unique")
        identifiers = [table.__metatable_identifier__ for table in self.source_storage_tables]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("source_storage_tables must be unique")
        return self


class FormulaIndexDataNode(IndexTimestampedDataNode):
    """Calculate immutable Index formulas from exact MetaTable dependencies."""

    configuration_class: ClassVar[type[FormulaIndexDataNodeConfiguration]] = (
        FormulaIndexDataNodeConfiguration
    )
    frame_label: ClassVar[str] = "Formula Index Values"

    def __init__(
        self,
        config: FormulaIndexDataNodeConfiguration,
        storage_table: type[PlatformTimeIndexMetaTable],
        *,
        hash_namespace: str | None = None,
    ) -> None:
        require_cadenced_index_values_storage(storage_table)
        self.config = config
        self._formulas = self._load_formulas(config.formula_definition_uids)
        self._source_tables, self._source_dependencies = self._build_source_dependencies(
            config.source_storage_tables
        )
        required_source_uids = {
            str(formula_input.meta_table_uid)
            for formula in self._formulas
            for formula_input in formula.inputs
        }
        configured_source_uids = set(self._source_tables)
        if configured_source_uids != required_source_uids:
            raise ValueError(
                "source_storage_tables must exactly match formula input MetaTable UIDs; "
                f"missing={sorted(required_source_uids - configured_source_uids)}, "
                f"unused={sorted(configured_source_uids - required_source_uids)}"
            )
        for formula in self._formulas:
            for formula_input in formula.inputs:
                self._validate_source_storage(
                    self._source_tables[str(formula_input.meta_table_uid)],
                    formula_input,
                )
        super().__init__(
            config=config,
            storage_table=storage_table,
            hash_namespace=hash_namespace,
        )

    def dependencies(self) -> dict[str, APIDataNode]:
        return dict(self._source_dependencies)

    def update(self) -> pd.DataFrame:
        outputs: list[pd.DataFrame] = []
        for formula in self._formulas:
            publication_start = self._incremental_start(formula.index.unique_identifier)
            definition = formula.definition
            start = _later(publication_start, definition.valid_from)
            end = definition.valid_to
            source_start = start
            if definition.alignment_policy == "asof" and start is not None:
                staleness = float(
                    (definition.alignment_parameters_json or {})["max_staleness_seconds"]
                )
                source_start = start - datetime.timedelta(seconds=staleness)
            observations = {
                formula_input.reference: self._load_observations(
                    formula_input,
                    start=source_start,
                    end=end,
                )
                for formula_input in formula.inputs
            }
            result = formula.calculate(observations)
            frame = result.values
            if start is not None:
                frame = frame.loc[pd.to_datetime(frame["time_index"], utc=True) >= start]
            if end is not None:
                frame = frame.loc[pd.to_datetime(frame["time_index"], utc=True) < end]
            if not frame.empty:
                outputs.append(frame)
        flat = (
            pd.concat(outputs, ignore_index=True)
            if outputs
            else pd.DataFrame(columns=[column.name for column in self.storage_table.__table__.columns])
        )
        normalized = normalize_stamped_frame(
            flat,
            storage_table=self.storage_table,
            frame_label=self.frame_label,
        )
        self._published_index_identifiers = index_identifiers_in_frame(normalized)
        return normalized

    def run_post_update_routines(self, error_on_last_update: bool) -> None:
        if error_on_last_update:
            return
        identifiers = getattr(self, "_published_index_identifiers", ())
        if identifiers:
            Index.reconcile_dataset_availability(index_identifiers=identifiers)

    def repair_after(
        self,
        after_date: datetime.datetime | str | None,
        *,
        index_identifiers: Sequence[str],
    ) -> Any:
        if not index_identifiers:
            raise ValueError("repair_after requires at least one Index identifier")
        return self.storage_table.get_time_index_meta_table().delete_after_date(
            after_date,
            dimension_filters={"index_identifier": list(index_identifiers)},
        )

    @staticmethod
    def _load_formulas(definition_uids: Sequence[uuid.UUID]) -> tuple[FormulaIndex, ...]:
        formulas: list[FormulaIndex] = []
        for definition_uid in definition_uids:
            formula = FormulaIndex.get_by_definition_uid(definition_uid)
            if formula is None:
                raise LookupError(f"formula definition {definition_uid!s} was not found")
            if formula.definition.status == "draft":
                raise ValueError(f"draft formula definition {definition_uid!s} cannot be published")
            formulas.append(formula)
        return tuple(formulas)

    @staticmethod
    def _build_source_dependencies(
        storage_tables: Sequence[type[PlatformTimeIndexMetaTable]],
    ) -> tuple[dict[str, type[PlatformTimeIndexMetaTable]], dict[str, APIDataNode]]:
        tables: dict[str, type[PlatformTimeIndexMetaTable]] = {}
        dependencies: dict[str, APIDataNode] = {}
        for storage_table in storage_tables:
            meta_table = storage_table.get_time_index_meta_table()
            if meta_table is None or not getattr(meta_table, "uid", None):
                raise ValueError(f"source storage {storage_table.__name__} is not registered")
            uid = str(meta_table.uid)
            if uid in tables:
                raise ValueError(f"multiple source storage classes resolve to MetaTable {uid}")
            tables[uid] = storage_table
            dependencies[f"source_{uid.replace('-', '_')}"] = APIDataNode.build_from_meta_table(
                meta_table
            )
        return tables, dependencies

    @staticmethod
    def _validate_source_storage(storage_table, formula_input) -> None:
        identity_column = (
            "asset_identifier"
            if formula_input.source_reference.type == "asset"
            else "index_identifier"
        )
        expected_index = ["time_index", identity_column]
        if list(storage_table.__index_names__) != expected_index:
            raise ValueError(
                f"formula source storage grain must be exactly {expected_index!r}"
            )
        column = storage_table.__table__.columns.get(formula_input.observable)
        if column is None:
            raise ValueError(
                f"formula source storage is missing observable {formula_input.observable!r}"
            )
        if not isinstance(column.type, (sa.Integer, sa.Float, sa.Numeric)):
            raise ValueError(
                f"formula observable {formula_input.observable!r} must be numeric"
            )

    def _load_observations(
        self,
        formula_input,
        *,
        start: datetime.datetime | None,
        end: datetime.datetime | None,
    ) -> pd.DataFrame:
        meta_table_uid = str(formula_input.meta_table_uid)
        dependency = self._source_dependencies[f"source_{meta_table_uid.replace('-', '_')}"]
        source_type = formula_input.source_reference.type
        identity_column = "asset_identifier" if source_type == "asset" else "index_identifier"
        frame = dependency.get_df_between_dates(
            start_date=start,
            end_date=end,
            dimension_filters={
                identity_column: [formula_input.source_reference.identifier],
            },
            columns=["time_index", identity_column, formula_input.observable],
        )
        flat = frame.reset_index() if "time_index" in frame.index.names else frame.copy()
        missing = {"time_index", identity_column, formula_input.observable} - set(flat.columns)
        if missing:
            raise IndexFormulaError(
                f"formula source {meta_table_uid} is missing columns {sorted(missing)}"
            )
        selected = flat.loc[
            flat[identity_column].astype(str) == formula_input.source_reference.identifier,
            ["time_index", formula_input.observable],
        ].copy()
        selected["time_index"] = pd.to_datetime(selected["time_index"], utc=True)
        return selected.set_index("time_index")

    def _incremental_start(self, index_identifier: str) -> datetime.datetime | None:
        if self.update_statistics is not None:
            last = self.update_statistics.get_last_update_for_identity(index_identifier)
            if last is not None:
                timestamp = pd.Timestamp(last)
                timestamp = (
                    timestamp.tz_localize("UTC")
                    if timestamp.tzinfo is None
                    else timestamp.tz_convert("UTC")
                )
                return (timestamp + pd.Timedelta(microseconds=1)).to_pydatetime()
        return self.config.offset_start


def _later(
    left: datetime.datetime | None,
    right: datetime.datetime | None,
) -> datetime.datetime | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


__all__ = ["FormulaIndexDataNode", "FormulaIndexDataNodeConfiguration"]
