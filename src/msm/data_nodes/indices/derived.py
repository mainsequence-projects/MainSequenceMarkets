from __future__ import annotations

import datetime
import re
import uuid
from collections.abc import Sequence
from typing import Any, ClassVar

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mainsequence.meta_tables import APIDataNode, PlatformTimeIndexMetaTable

from msm.analytics.indices import (
    ALIGNMENT_REGISTRY,
    CALCULATION_REGISTRY,
    COEFFICIENT_REGISTRY,
    MISSING_DATA_REGISTRY,
    REBALANCE_REGISTRY,
    SELECTOR_REGISTRY,
    TRANSFORM_REGISTRY,
    IndexCalculationDefinition,
    IndexCalculationError,
    IndexCalculationLeg,
    calculate_index,
    resolve_index_legs,
    resolve_selector,
)
from msm.api.derived_indices import DerivedIndex
from msm.api.indices import Index
from msm.data_nodes.indices.storage import (
    IndexResolvedLegsStorage,
    require_cadenced_index_values_storage,
)
from msm.data_nodes.indices.timestamped import (
    IndexDataNodeConfiguration,
    IndexTimestampedDataNode,
)
from msm.data_nodes.indices.values import index_identifiers_in_frame
from msm.data_nodes.utils.stamped import normalize_stamped_frame
from msm.repositories.indices import definition_history, definition_legs


class DerivedIndexSourceBinding(BaseModel):
    """One bounded, dimension-aware source dependency for derived publication."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    storage_table: type[PlatformTimeIndexMetaTable]
    component_dimension: str = Field(min_length=1)
    static_dimension_filters: dict[str, tuple[str, ...]] = Field(default_factory=dict)

    @field_validator("component_dimension")
    @classmethod
    def _validate_component_dimension(cls, value: str) -> str:
        normalized = str(value).strip()
        if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", normalized):
            raise ValueError("component_dimension must be a valid column name")
        return normalized

    @field_validator("static_dimension_filters")
    @classmethod
    def _validate_static_filters(
        cls, value: dict[str, tuple[str, ...]]
    ) -> dict[str, tuple[str, ...]]:
        if any(not str(key).strip() or not values for key, values in value.items()):
            raise ValueError("static dimension filters require non-empty names and values")
        return value


class DerivedIndexDataNodeConfiguration(IndexDataNodeConfiguration):
    """Hashed updater scope for canonical derived-index publication."""

    index_identifiers: tuple[str, ...] = Field(
        ...,
        min_length=1,
        description="Canonical derived Index identifiers published by this updater.",
        examples=[("MX_MBONOS_2S5S_YIELD_SPREAD",)],
    )
    source_bindings: dict[str, DerivedIndexSourceBinding] = Field(
        ...,
        min_length=1,
        description=(
            "Registered source storage classes keyed by leg_key or observable_code. "
            "Changing a binding changes the deterministic dependency graph and update hash."
        ),
    )
    requires_resolved_legs: bool = Field(
        default=False,
        description=(
            "Whether this updater publishes dynamic selector/coefficient provenance through "
            "a required resolved-leg dependency before values."
        ),
    )
    resolved_legs_storage: type[PlatformTimeIndexMetaTable] | None = Field(
        default=None,
        description=(
            "Registered resolved-leg output storage required when dynamic methodology "
            "provenance is enabled."
        ),
    )

    @model_validator(mode="after")
    def _validate_dynamic_storage(self) -> DerivedIndexDataNodeConfiguration:
        if self.requires_resolved_legs and self.resolved_legs_storage is None:
            raise ValueError("requires_resolved_legs=True requires resolved_legs_storage")
        if not self.requires_resolved_legs and self.resolved_legs_storage is not None:
            raise ValueError("resolved_legs_storage is only valid when requires_resolved_legs=True")
        if len(set(self.index_identifiers)) != len(self.index_identifiers):
            raise ValueError("index_identifiers must be unique")
        dependency_keys = [_dependency_key(key) for key in self.source_bindings]
        if any(not key for key in dependency_keys):
            raise ValueError("source binding keys must contain an alphanumeric character")
        if len(set(dependency_keys)) != len(dependency_keys):
            raise ValueError(
                "source binding keys must remain unique after dependency normalization"
            )
        return self


class _DerivedIndexSourceMixin:
    config: DerivedIndexDataNodeConfiguration
    _source_dependencies: dict[str, APIDataNode]

    def _build_source_dependencies(
        self,
        config: DerivedIndexDataNodeConfiguration,
    ) -> dict[str, APIDataNode]:
        dependencies: dict[str, APIDataNode] = {}
        for binding_key, binding in sorted(config.source_bindings.items()):
            meta_table = binding.storage_table.get_time_index_meta_table()
            dependencies[f"source_{_dependency_key(binding_key)}"] = (
                APIDataNode.build_from_meta_table(meta_table)
            )
        return dependencies

    def _source_dependency_for_leg(self, leg: IndexCalculationLeg) -> APIDataNode:
        binding_key = (
            leg.leg_key if leg.leg_key in self.config.source_bindings else leg.observable_code
        )
        dependency_key = f"source_{_dependency_key(binding_key)}"
        try:
            return self._source_dependencies[dependency_key]
        except KeyError as exc:
            raise IndexCalculationError(
                f"no source binding for leg {leg.leg_key!r} or observable {leg.observable_code!r}"
            ) from exc

    def _source_binding_for_leg(self, leg: IndexCalculationLeg) -> DerivedIndexSourceBinding:
        binding_key = (
            leg.leg_key if leg.leg_key in self.config.source_bindings else leg.observable_code
        )
        try:
            return self.config.source_bindings[binding_key]
        except KeyError as exc:
            raise IndexCalculationError(
                f"no source binding for leg {leg.leg_key!r} or observable {leg.observable_code!r}"
            ) from exc

    def _source_frame(
        self,
        leg: IndexCalculationLeg,
        *,
        start: datetime.datetime | None,
        end: datetime.datetime | None,
    ) -> pd.DataFrame:
        binding = self._source_binding_for_leg(leg)
        dimension_filters = {
            key: list(values) for key, values in binding.static_dimension_filters.items()
        }
        if leg.selector_code is None:
            dimension_filters[binding.component_dimension] = [_fixed_component_identifier(leg)]
        elif binding.component_dimension not in dimension_filters:
            selector_universe = (leg.selector_parameters_json or {}).get(
                "component_identifiers"
            )
            if not selector_universe:
                raise IndexCalculationError(
                    f"selector leg {leg.leg_key!r} requires a bounded component universe"
                )
            dimension_filters[binding.component_dimension] = [
                str(item) for item in selector_universe
            ]
        return self._source_dependency_for_leg(leg).get_df_between_dates(
            start_date=start,
            end_date=end,
            dimension_filters=dimension_filters,
        )

    def _methodologies(self, index_identifier: str) -> list[DerivedIndex]:
        index = Index.get_by_unique_identifier(index_identifier)
        if index is None:
            raise LookupError(f"derived Index {index_identifier!r} does not exist")
        context = DerivedIndex._active_context()
        versions: list[DerivedIndex] = []
        for definition in definition_history(context, index_uid=index.uid):
            if definition.status == "draft":
                continue
            versions.append(
                DerivedIndex(
                    index=index,
                    definition=definition,
                    legs=tuple(definition_legs(context, definition_uid=definition.uid)),
                )
            )
        return versions

    def _incremental_start(self, index_identifier: str) -> datetime.datetime | None:
        if self.update_statistics is not None:
            last = self.update_statistics.get_last_update_for_identity(index_identifier)
            if last is not None:
                timestamp = pd.Timestamp(last)
                if timestamp.tzinfo is None:
                    timestamp = timestamp.tz_localize("UTC")
                else:
                    timestamp = timestamp.tz_convert("UTC")
                return (timestamp + pd.Timedelta(microseconds=1)).to_pydatetime()
        return self.config.offset_start

    def _calculation_start(
        self,
        methodology: DerivedIndex,
        publication_start: datetime.datetime | None,
    ) -> datetime.datetime | None:
        if publication_start is None:
            return self.config.offset_start
        definition = methodology.definition
        history_modes = {
            CALCULATION_REGISTRY.history_mode(definition.calculation_kind),
            ALIGNMENT_REGISTRY.history_mode(definition.alignment_policy),
            MISSING_DATA_REGISTRY.history_mode(definition.missing_data_policy),
            *(
                TRANSFORM_REGISTRY.history_mode(leg.transform_code)
                for leg in methodology.legs
            ),
            *(
                COEFFICIENT_REGISTRY.history_mode(leg.coefficient_method)
                for leg in methodology.legs
            ),
        }
        history_modes.update(
            SELECTOR_REGISTRY.history_mode(leg.selector_code)
            for leg in methodology.legs
            if leg.selector_code is not None
        )
        if definition.rebalance_policy is not None:
            history_modes.add(REBALANCE_REGISTRY.history_mode(definition.rebalance_policy))
        if history_modes == {"none"}:
            return publication_start
        lower = definition.effective_from
        if self.config.offset_start is not None:
            lower = max(lower, self.config.offset_start)
        return lower

    def _load_version_inputs(
        self,
        methodology: DerivedIndex,
        *,
        start: datetime.datetime | None,
        end: datetime.datetime | None,
    ) -> tuple[
        dict[str, pd.Series],
        dict[str, pd.DataFrame],
        dict[uuid.UUID, str],
        dict[str, pd.Series],
    ]:
        raw_frames = {
            leg.leg_key: self._source_frame(leg, start=start, end=end) for leg in methodology.legs
        }
        calculation_times = _calculation_times(raw_frames.values())
        observations: dict[str, pd.Series] = {}
        selector_candidates: dict[str, pd.DataFrame] = {}
        component_identifiers: dict[uuid.UUID, str] = {}
        coefficient_inputs: dict[str, pd.Series] = {}
        reference_leg = methodology.legs[0]

        for leg in methodology.legs:
            raw = _flat_source_frame(raw_frames[leg.leg_key])
            selected_components: pd.DataFrame | None = None
            if leg.selector_code is not None:
                selector_candidates[leg.leg_key] = raw
                selected_components = resolve_selector(
                    leg.selector_code,
                    raw,
                    calculation_times,
                    parameters=leg.selector_parameters_json,
                    rebalance_policy=methodology.definition.rebalance_policy,
                    rebalance_parameters=methodology.definition.rebalance_parameters_json,
                )
                observations[leg.leg_key] = _selected_observation_series(
                    raw,
                    selected_components,
                    observable_code=leg.observable_code,
                )
            else:
                component_key = _fixed_component_identifier(leg)
                if leg.asset_uid is not None:
                    component_identifiers[leg.asset_uid] = component_key
                if leg.component_index_uid is not None:
                    component_identifiers[leg.component_index_uid] = component_key
                observations[leg.leg_key] = _fixed_observation_series(
                    raw,
                    component_key=component_key,
                    observable_code=leg.observable_code,
                )
            parameter_observable = (leg.coefficient_parameters_json or {}).get("observable_code")
            if parameter_observable and parameter_observable in raw.columns:
                if selected_components is not None:
                    coefficient_inputs[leg.leg_key] = _selected_observation_series(
                        raw,
                        selected_components,
                        observable_code=str(parameter_observable),
                    )
                else:
                    coefficient_inputs[leg.leg_key] = _fixed_observation_series(
                        raw,
                        component_key=_fixed_component_identifier(leg),
                        observable_code=str(parameter_observable),
                    )
            reference_observable = (leg.coefficient_parameters_json or {}).get(
                "reference_observable_code"
            )
            if reference_observable:
                reference_raw = _flat_source_frame(raw_frames[reference_leg.leg_key])
                if reference_leg.selector_code is not None:
                    reference_selection = resolve_selector(
                        reference_leg.selector_code,
                        reference_raw,
                        calculation_times,
                        parameters=reference_leg.selector_parameters_json,
                        rebalance_policy=methodology.definition.rebalance_policy,
                        rebalance_parameters=methodology.definition.rebalance_parameters_json,
                    )
                    coefficient_inputs[reference_leg.leg_key] = _selected_observation_series(
                        reference_raw,
                        reference_selection,
                        observable_code=str(reference_observable),
                    )
                else:
                    coefficient_inputs[reference_leg.leg_key] = _fixed_observation_series(
                        reference_raw,
                        component_key=_fixed_component_identifier(reference_leg),
                        observable_code=str(reference_observable),
                    )
        return observations, selector_candidates, component_identifiers, coefficient_inputs


class DerivedIndexResolvedLegsDataNode(_DerivedIndexSourceMixin, IndexTimestampedDataNode):
    """Publish dynamic component and coefficient methodology audit facts."""

    configuration_class: ClassVar[type[DerivedIndexDataNodeConfiguration]] = (
        DerivedIndexDataNodeConfiguration
    )
    frame_label: ClassVar[str] = "Derived Index Resolved Legs"

    def __init__(
        self,
        config: DerivedIndexDataNodeConfiguration,
        storage_table: type[PlatformTimeIndexMetaTable] = IndexResolvedLegsStorage,
        *,
        hash_namespace: str | None = None,
    ):
        self.config = config
        self._source_dependencies = self._build_source_dependencies(config)
        super().__init__(
            config=config,
            storage_table=storage_table,
            hash_namespace=hash_namespace,
        )

    def dependencies(self) -> dict[str, APIDataNode]:
        return dict(self._source_dependencies)

    def update(self) -> pd.DataFrame:
        outputs: list[pd.DataFrame] = []
        for index_identifier in self.config.index_identifiers:
            publication_start = self._incremental_start(index_identifier)
            for methodology in self._methodologies(index_identifier):
                if _definition_completed_before(
                    methodology.definition, publication_start=publication_start
                ):
                    continue
                calculation_start = self._calculation_start(methodology, publication_start)
                inputs = self._load_version_inputs(
                    methodology,
                    start=calculation_start,
                    end=methodology.definition.effective_to,
                )
                observations, candidates, identifiers, coefficient_inputs = inputs
                times = _calculation_times_from_series(observations.values())
                times = _times_for_definition(
                    times, methodology.definition, start=calculation_start
                )
                if times.empty:
                    continue
                resolved = resolve_index_legs(
                        methodology.definition,
                        methodology.legs,
                        observations,
                        index_identifier=index_identifier,
                        calculation_times=times,
                        selector_candidates=candidates,
                        component_identifiers=identifiers,
                        coefficient_inputs=coefficient_inputs,
                    )
                outputs.append(_trim_publication_frame(resolved, publication_start))
        frame = pd.concat(outputs).sort_index() if outputs else _empty_resolved_frame()
        return normalize_stamped_frame(
            frame,
            storage_table=self.storage_table,
            frame_label=self.frame_label,
        )


class DerivedIndexDataNode(_DerivedIndexSourceMixin, IndexTimestampedDataNode):
    """Incrementally calculate and publish canonical derived-index values."""

    configuration_class: ClassVar[type[DerivedIndexDataNodeConfiguration]] = (
        DerivedIndexDataNodeConfiguration
    )
    frame_label: ClassVar[str] = "Derived Index Values"

    def __init__(
        self,
        config: DerivedIndexDataNodeConfiguration,
        storage_table: type[PlatformTimeIndexMetaTable],
        *,
        hash_namespace: str | None = None,
    ):
        require_cadenced_index_values_storage(storage_table)
        self.config = config
        self._source_dependencies = self._build_source_dependencies(config)
        self._resolved_legs_dependency: DerivedIndexResolvedLegsDataNode | None = None
        if config.requires_resolved_legs:
            self._resolved_legs_dependency = DerivedIndexResolvedLegsDataNode(
                config=config,
                storage_table=config.resolved_legs_storage,
                hash_namespace=hash_namespace,
            )
        super().__init__(
            config=config,
            storage_table=storage_table,
            hash_namespace=hash_namespace,
        )

    def dependencies(self) -> dict[str, Any]:
        dependencies: dict[str, Any] = dict(self._source_dependencies)
        if self._resolved_legs_dependency is not None:
            dependencies["resolved_legs"] = self._resolved_legs_dependency
        return dependencies

    def update(self) -> pd.DataFrame:
        outputs: list[pd.DataFrame] = []
        for index_identifier in self.config.index_identifiers:
            publication_start = self._incremental_start(index_identifier)
            for methodology in self._methodologies(index_identifier):
                if _definition_completed_before(
                    methodology.definition, publication_start=publication_start
                ):
                    continue
                calculation_start = self._calculation_start(methodology, publication_start)
                observations, _candidates, _identifiers, coefficient_inputs = (
                    self._load_version_inputs(
                        methodology,
                        start=calculation_start,
                        end=methodology.definition.effective_to,
                    )
                )
                times = _calculation_times_from_series(observations.values())
                times = _times_for_definition(
                    times, methodology.definition, start=calculation_start
                )
                if times.empty:
                    continue
                resolved_coefficients, resolved_coefficient_source_times = (
                    self._load_resolved_coefficients(
                        methodology,
                        start=calculation_start,
                        end=methodology.definition.effective_to,
                    )
                )
                result = calculate_index(
                    methodology.definition,
                    methodology.legs,
                    observations,
                    index_identifier=index_identifier,
                    calculation_times=times,
                    resolved_coefficients=resolved_coefficients,
                    resolved_coefficient_source_times=resolved_coefficient_source_times,
                    coefficient_inputs=coefficient_inputs,
                )
                outputs.append(_trim_publication_frame(result.values, publication_start))
        frame = pd.concat(outputs).sort_index() if outputs else _empty_values_frame()
        normalized = normalize_stamped_frame(
            frame,
            storage_table=self.storage_table,
            frame_label=self.frame_label,
        )
        validated = _validate_derived_values_frame(normalized)
        self._published_index_identifiers = index_identifiers_in_frame(validated)
        return validated

    def run_post_update_routines(self, error_on_last_update: bool) -> None:
        if error_on_last_update:
            return
        identifiers = getattr(self, "_published_index_identifiers", ())
        if identifiers:
            Index.reconcile_dataset_availability(index_identifiers=identifiers)

    def _load_resolved_coefficients(
        self,
        methodology: DerivedIndex,
        *,
        start: datetime.datetime | None,
        end: datetime.datetime | None,
    ) -> tuple[dict[str, pd.Series] | None, dict[str, pd.Series] | None]:
        dynamic_legs = [
            leg
            for leg in methodology.legs
            if leg.selector_code is not None
            or leg.coefficient_method not in {"fixed", "equal_weight"}
        ]
        if not dynamic_legs:
            return None, None
        if self._resolved_legs_dependency is None:
            raise IndexCalculationError(
                "dynamic methodology values require a resolved-leg DataNode dependency"
            )
        frame = self._resolved_legs_dependency.get_df_between_dates(
            start_date=start,
            end_date=end,
            dimension_filters={"index_identifier": [methodology.index.unique_identifier]},
        )
        flat = frame.reset_index() if any(frame.index.names) else frame.copy()
        if flat.empty:
            raise IndexCalculationError(
                "dynamic methodology values cannot publish without resolved-leg provenance"
            )
        result: dict[str, pd.Series] = {}
        source_times: dict[str, pd.Series] = {}
        for leg in dynamic_legs:
            rows = flat.loc[flat["leg_key"] == leg.leg_key].copy()
            rows["time_index"] = pd.to_datetime(rows["time_index"], utc=True)
            result[leg.leg_key] = rows.set_index("time_index")["resolved_coefficient"]
            if leg.coefficient_method not in {"fixed", "equal_weight"}:
                coefficient_sources = rows.apply(
                    lambda row: (
                        (row.get("metadata_json") or {}).get("coefficient_source_observation_time")
                        or row.get("source_observation_time")
                    ),
                    axis=1,
                )
                coefficient_sources.index = pd.DatetimeIndex(rows["time_index"])
                source_times[leg.leg_key] = coefficient_sources
        return result, source_times or None

    def repair_after(
        self,
        after_date: datetime.datetime | str | None,
        *,
        index_identifiers: Sequence[str],
    ) -> Any:
        """Delete scoped canonical tails before a controlled repair/backfill run."""

        if not index_identifiers:
            raise ValueError("repair_after requires at least one index identifier")
        return self.storage_table.get_time_index_meta_table().delete_after_date(
            after_date,
            dimension_filters={"index_identifier": list(index_identifiers)},
        )


def _dependency_key(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()


def _flat_source_frame(frame: pd.DataFrame) -> pd.DataFrame:
    flat = frame.reset_index() if any(frame.index.names) else frame.copy()
    if "time_index" not in flat:
        raise IndexCalculationError("source storage frame is missing time_index")
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
    return flat.sort_values("time_index")


def _identity_column(frame: pd.DataFrame) -> str | None:
    for column in (
        "asset_identifier",
        "index_identifier",
        "unique_identifier",
        "component_key",
        "resolved_component_key",
    ):
        if column in frame:
            return column
    return None


def _fixed_component_identifier(leg: IndexCalculationLeg) -> str:
    from msm.api.assets import Asset

    if leg.asset_uid is not None:
        asset = Asset.get_by_uid(leg.asset_uid)
        if asset is None:
            raise LookupError(f"asset leg {leg.leg_key!r} references an unavailable Asset")
        return asset.unique_identifier
    if leg.component_index_uid is not None:
        index = Index.get_by_uid(leg.component_index_uid)
        if index is None:
            raise LookupError(f"index leg {leg.leg_key!r} references an unavailable Index")
        return index.unique_identifier
    raise ValueError("fixed component identifier requested for selector leg")


def _fixed_observation_series(
    frame: pd.DataFrame,
    *,
    component_key: str | None,
    observable_code: str,
) -> pd.Series:
    if observable_code not in frame:
        raise IndexCalculationError(f"source frame is missing observable {observable_code!r}")
    identity_column = _identity_column(frame)
    selected = frame
    if component_key is not None and identity_column is not None:
        selected = selected.loc[selected[identity_column].astype(str) == component_key]
    if selected.empty:
        raise IndexCalculationError(
            f"source frame contains no observations for component {component_key!r}"
        )
    if selected["time_index"].duplicated().any():
        raise IndexCalculationError("source frame contains duplicate component timestamps")
    return selected.set_index("time_index")[observable_code].sort_index()


def _selected_observation_series(
    frame: pd.DataFrame,
    selected: pd.DataFrame,
    *,
    observable_code: str,
) -> pd.Series:
    identity_column = _identity_column(frame)
    if identity_column is None:
        raise IndexCalculationError("selector source frame is missing a component identity column")
    if observable_code not in frame:
        raise IndexCalculationError(f"selector source is missing observable {observable_code!r}")
    values: dict[pd.Timestamp, float] = {}
    for row in selected.itertuples(index=False):
        calculation_time = pd.Timestamp(row.time_index)
        eligible = frame.loc[
            (frame[identity_column].astype(str) == str(row.resolved_component_key))
            & (frame["time_index"] <= calculation_time)
        ]
        if eligible.empty:
            continue
        observation = eligible.sort_values("time_index").iloc[-1]
        values[calculation_time] = float(observation[observable_code])
    return pd.Series(values, dtype=float).sort_index()


def _calculation_times(frames: Sequence[pd.DataFrame]) -> pd.DatetimeIndex:
    values: list[pd.Timestamp] = []
    for frame in frames:
        flat = _flat_source_frame(frame)
        values.extend(flat["time_index"].tolist())
    return pd.DatetimeIndex(sorted(set(values)), dtype="datetime64[ns, UTC]")


def _calculation_times_from_series(series: Sequence[pd.Series]) -> pd.DatetimeIndex:
    values = sorted({timestamp for value in series for timestamp in value.index})
    return pd.DatetimeIndex(values, dtype="datetime64[ns, UTC]")


def _times_for_definition(
    times: pd.DatetimeIndex,
    definition: IndexCalculationDefinition,
    *,
    start: datetime.datetime | None,
) -> pd.DatetimeIndex:
    lower = pd.Timestamp(definition.effective_from)
    if start is not None:
        lower = max(lower, pd.Timestamp(start))
    selected = times[times >= lower]
    if definition.effective_to is not None:
        selected = selected[selected < pd.Timestamp(definition.effective_to)]
    return selected


def _definition_completed_before(
    definition: IndexCalculationDefinition,
    *,
    publication_start: datetime.datetime | None,
) -> bool:
    return (
        publication_start is not None
        and definition.effective_to is not None
        and definition.effective_to <= publication_start
    )


def _trim_publication_frame(
    frame: pd.DataFrame,
    publication_start: datetime.datetime | None,
) -> pd.DataFrame:
    if frame.empty or publication_start is None:
        return frame
    if "time_index" in frame.index.names:
        times = pd.DatetimeIndex(frame.index.get_level_values("time_index"))
        return frame.loc[times >= pd.Timestamp(publication_start)]
    if "time_index" in frame:
        return frame.loc[pd.to_datetime(frame["time_index"], utc=True) >= publication_start]
    raise IndexCalculationError("calculation output is missing time_index")


def _empty_values_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "time_index",
            "index_identifier",
            "value",
            "unit",
            "definition_uid",
            "observation_status",
            "source_as_of",
            "metadata_json",
        ]
    )


def _validate_derived_values_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    values = frame.reset_index()
    if values["definition_uid"].isna().any():
        raise IndexCalculationError(
            "derived Index values require the exact effective definition_uid"
        )
    if values["observation_status"].isna().any():
        raise IndexCalculationError("derived Index values require an observation_status")
    return frame


def _empty_resolved_frame() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "time_index",
            "index_identifier",
            "definition_uid",
            "leg_key",
            "resolved_component_key",
            "component_kind",
            "resolved_coefficient",
            "coefficient_method",
            "observable_code",
            "source_observation_time",
            "resolution_status",
            "metadata_json",
        ]
    )


__all__ = [
    "DerivedIndexDataNode",
    "DerivedIndexDataNodeConfiguration",
    "DerivedIndexResolvedLegsDataNode",
]
