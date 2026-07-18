from __future__ import annotations

import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from msm.data_nodes.indices import (
    DerivedIndexDataNode,
    DerivedIndexDataNodeConfiguration,
    IndexResolvedLegsStorage,
    IndexValuesStorage,
)
from msm.data_nodes.indices import derived as derived_nodes


def _config(**updates) -> DerivedIndexDataNodeConfiguration:
    values = {
        "index_identifiers": ("TEST_DERIVED_INDEX",),
        "source_bindings": {"price": IndexValuesStorage},
    }
    values.update(updates)
    return DerivedIndexDataNodeConfiguration(**values)


def test_configuration_keeps_source_storage_bindings_in_hashed_payload() -> None:
    config = _config(offset_start="2025-01-01T00:00:00Z")

    payload = config.model_dump(mode="python")
    assert payload["index_identifiers"] == ("TEST_DERIVED_INDEX",)
    assert payload["source_bindings"] == {"price": IndexValuesStorage}
    assert payload["offset_start"] == datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC)


def test_configuration_requires_dynamic_provenance_storage_and_unique_dependencies() -> None:
    with pytest.raises(ValidationError, match="requires resolved_legs_storage"):
        _config(requires_resolved_legs=True)
    with pytest.raises(ValidationError, match="only valid"):
        _config(resolved_legs_storage=IndexResolvedLegsStorage)
    with pytest.raises(ValidationError, match="dependency normalization"):
        _config(source_bindings={"price-a": IndexValuesStorage, "price a": IndexValuesStorage})

    config = _config(
        requires_resolved_legs=True,
        resolved_legs_storage=IndexResolvedLegsStorage,
    )
    assert config.requires_resolved_legs is True


def test_source_dependencies_are_built_once_in_sorted_deterministic_order(monkeypatch) -> None:
    meta_table = SimpleNamespace(identifier="source")
    monkeypatch.setattr(
        IndexValuesStorage,
        "get_time_index_meta_table",
        classmethod(lambda _cls: meta_table),
    )
    built: list[object] = []

    def _build(value):
        built.append(value)
        return f"dependency-{len(built)}"

    monkeypatch.setattr(derived_nodes.APIDataNode, "build_from_meta_table", _build)
    node = object.__new__(DerivedIndexDataNode)
    dependencies = node._build_source_dependencies(
        _config(source_bindings={"z source": IndexValuesStorage, "a/source": IndexValuesStorage})
    )

    assert list(dependencies) == ["source_a_source", "source_z_source"]
    assert built == [meta_table, meta_table]


def test_incremental_start_advances_past_last_published_coordinate() -> None:
    node = object.__new__(DerivedIndexDataNode)
    node.config = _config(offset_start="2024-01-01T00:00:00Z")
    node.update_statistics = SimpleNamespace(
        get_last_update_for_identity=lambda _identity: datetime.datetime(2025, 1, 1)
    )

    assert node._incremental_start("TEST_DERIVED_INDEX") == datetime.datetime(
        2025,
        1,
        1,
        0,
        0,
        0,
        1,
        tzinfo=datetime.UTC,
    )


def test_definition_time_filter_supports_backfill_and_exclusive_version_end() -> None:
    definition = SimpleNamespace(
        effective_from=datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
        effective_to=datetime.datetime(2025, 1, 4, tzinfo=datetime.UTC),
    )
    times = pd.date_range("2025-01-01", periods=5, tz="UTC")

    selected = derived_nodes._times_for_definition(times, definition, start=None)
    assert selected.tolist() == [times[1], times[2]]
    repaired = derived_nodes._times_for_definition(
        times,
        definition,
        start=datetime.datetime(2025, 1, 3, tzinfo=datetime.UTC),
    )
    assert repaired.tolist() == [times[2]]


def test_scoped_repair_uses_index_dimension_filter() -> None:
    calls: list[tuple[object, dict]] = []
    meta_table = SimpleNamespace(
        delete_after_date=lambda after_date, *, dimension_filters: (
            calls.append((after_date, dimension_filters)) or "deleted"
        )
    )
    storage = type(
        "RepairStorage",
        (),
        {"get_time_index_meta_table": classmethod(lambda _cls: meta_table)},
    )
    node = object.__new__(DerivedIndexDataNode)
    node._storage_table = storage

    result = node.repair_after("2025-01-01T00:00:00Z", index_identifiers=["A", "B"])

    assert result == "deleted"
    assert calls == [
        (
            "2025-01-01T00:00:00Z",
            {"index_identifier": ["A", "B"]},
        )
    ]
    with pytest.raises(ValueError, match="at least one"):
        node.repair_after(None, index_identifiers=[])
