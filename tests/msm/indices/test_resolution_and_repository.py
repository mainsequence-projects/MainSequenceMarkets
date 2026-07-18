from __future__ import annotations

import datetime
import uuid

import pandas as pd
import pytest

from msm.analytics.indices import (
    IndexCalculationDefinition,
    IndexCalculationError,
    IndexCalculationLeg,
    resolve_selector,
)
from msm.repositories import indices as repository


def _definition(
    *,
    index_uid: uuid.UUID,
    version: int,
    status: str,
    effective_from: datetime.datetime,
    effective_to: datetime.datetime | None = None,
) -> IndexCalculationDefinition:
    return IndexCalculationDefinition(
        uid=uuid.uuid4(),
        index_uid=index_uid,
        definition_version=version,
        status=status,
        effective_from=effective_from,
        effective_to=effective_to,
        calculation_kind="linear_combination",
        calculation_family="spread",
        output_unit="usd",
        composition_mode="fixed",
        definition_hash="0" * 64,
    )


def _index_leg(component_index_uid: uuid.UUID) -> IndexCalculationLeg:
    return IndexCalculationLeg(
        leg_key="component",
        leg_order=0,
        component_kind="index",
        component_index_uid=component_index_uid,
        observable_code="value",
        input_unit="usd",
        coefficient_method="fixed",
        coefficient=1.0,
    )


def test_nearest_tenor_selector_is_deterministic_and_never_reads_future_rows() -> None:
    calculation_times = pd.DatetimeIndex(["2025-01-02T00:00:00Z", "2025-01-04T00:00:00Z"])
    candidates = pd.DataFrame(
        [
            {"time_index": "2025-01-01T00:00:00Z", "component_key": "B", "tenor_years": 4.9},
            {"time_index": "2025-01-01T00:00:00Z", "component_key": "A", "tenor_years": 5.1},
            {"time_index": "2025-01-03T00:00:00Z", "component_key": "C", "tenor_years": 5.0},
            {"time_index": "2025-01-05T00:00:00Z", "component_key": "FUTURE", "tenor_years": 5.0},
        ]
    )

    resolved = resolve_selector(
        "nearest_tenor",
        candidates,
        calculation_times,
        parameters={"target_tenor_years": 5.0},
    )

    assert resolved["resolved_component_key"].tolist() == ["A", "C"]
    assert (resolved["source_observation_time"] <= resolved["time_index"]).all()


def test_monthly_selector_rebalances_only_on_first_calculation_time_in_period() -> None:
    calculation_times = pd.DatetimeIndex(
        [
            "2025-01-30T00:00:00Z",
            "2025-01-31T00:00:00Z",
            "2025-02-01T00:00:00Z",
            "2025-02-02T00:00:00Z",
        ]
    )
    candidates = pd.DataFrame(
        {
            "time_index": calculation_times,
            "component_key": ["JAN_FIRST", "JAN_LATER", "FEB_FIRST", "FEB_LATER"],
            "tenor_years": [5.0, 5.0, 5.0, 5.0],
        }
    )

    resolved = resolve_selector(
        "nearest_tenor",
        candidates,
        calculation_times,
        parameters={"target_tenor_years": 5.0},
        rebalance_policy="monthly",
        rebalance_parameters={"timezone": "UTC"},
    )

    assert resolved["resolved_component_key"].tolist() == [
        "JAN_FIRST",
        "JAN_FIRST",
        "FEB_FIRST",
        "FEB_FIRST",
    ]
    assert resolved["source_observation_time"].tolist() == [
        calculation_times[0],
        calculation_times[0],
        calculation_times[2],
        calculation_times[2],
    ]


def test_event_selector_uses_first_calculation_time_at_or_after_declared_event() -> None:
    calculation_times = pd.date_range("2025-01-01", periods=4, tz="UTC")
    candidates = pd.DataFrame(
        {
            "time_index": calculation_times,
            "component_key": ["BEFORE", "EVENT_ONE", "BETWEEN", "EVENT_TWO"],
            "tenor_years": [5.0, 5.0, 5.0, 5.0],
        }
    )

    resolved = resolve_selector(
        "nearest_tenor",
        candidates,
        calculation_times,
        parameters={"target_tenor_years": 5.0},
        rebalance_policy="event",
        rebalance_parameters={
            "event_times": [
                "2025-01-01T12:00:00Z",
                "2025-01-03T12:00:00Z",
            ]
        },
    )

    assert resolved["time_index"].tolist() == calculation_times[1:].tolist()
    assert resolved["resolved_component_key"].tolist() == [
        "EVENT_ONE",
        "EVENT_ONE",
        "EVENT_TWO",
    ]


def test_selector_contract_rejects_future_provenance(monkeypatch) -> None:
    from msm.analytics.indices.registries import SELECTOR_REGISTRY

    def _future_selector(_candidates, calculation_times, _parameters):
        return pd.DataFrame(
            {
                "time_index": calculation_times,
                "resolved_component_key": ["FUTURE"],
                "component_kind": ["asset"],
                "source_observation_time": [calculation_times[0] + pd.Timedelta(days=1)],
            }
        )

    SELECTOR_REGISTRY.register("test_future", _future_selector)
    try:
        with pytest.raises(IndexCalculationError, match="future observation"):
            resolve_selector(
                "test_future",
                pd.DataFrame({"time_index": ["2025-01-01T00:00:00Z"]}),
                ["2025-01-01T00:00:00Z"],
            )
    finally:
        SELECTOR_REGISTRY._entries.pop("test_future")


def test_effective_definition_uses_inclusive_start_and_exclusive_end(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    first = _definition(
        index_uid=index_uid,
        version=1,
        status="retired",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        effective_to=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
    )
    second = _definition(
        index_uid=index_uid,
        version=2,
        status="active",
        effective_from=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
    )
    monkeypatch.setattr(repository, "definition_history", lambda *_args, **_kwargs: [first, second])

    assert (
        repository.effective_definition(object(), index_uid=index_uid, at="2025-01-31T23:59:59Z")
        == first
    )
    assert (
        repository.effective_definition(object(), index_uid=index_uid, at="2025-02-01T00:00:00Z")
        == second
    )


def test_activation_closes_prior_open_version_and_activates_new_one(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    prior = _definition(
        index_uid=index_uid,
        version=1,
        status="active",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
    )
    draft = _definition(
        index_uid=index_uid,
        version=2,
        status="draft",
        effective_from=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
    )
    calls: list[tuple[uuid.UUID, dict]] = []

    monkeypatch.setattr(repository, "get_definition", lambda *_args, **_kwargs: draft)
    monkeypatch.setattr(repository, "definition_history", lambda *_args, **_kwargs: [prior, draft])

    def _update(_context, *, model, uid, values):
        calls.append((uid, values))
        current = draft if uid == draft.uid else prior
        return {"row": current.model_copy(update=values).model_dump(mode="python")}

    monkeypatch.setattr(repository, "update_model", _update)

    activated = repository.activate_definition(object(), definition_uid=draft.uid)

    assert calls == [
        (prior.uid, {"status": "retired", "effective_to": draft.effective_from}),
        (draft.uid, {"status": "active"}),
    ]
    assert activated.status == "active"


def test_activation_rejects_overlapping_closed_interval(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    existing = _definition(
        index_uid=index_uid,
        version=1,
        status="retired",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        effective_to=datetime.datetime(2025, 3, 1, tzinfo=datetime.UTC),
    )
    draft = _definition(
        index_uid=index_uid,
        version=2,
        status="draft",
        effective_from=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
    )
    monkeypatch.setattr(repository, "get_definition", lambda *_args, **_kwargs: draft)
    monkeypatch.setattr(
        repository, "definition_history", lambda *_args, **_kwargs: [existing, draft]
    )

    with pytest.raises(ValueError, match="overlaps"):
        repository.activate_definition(object(), definition_uid=draft.uid)


def test_retired_definition_cannot_be_reactivated(monkeypatch) -> None:
    retired = _definition(
        index_uid=uuid.uuid4(),
        version=1,
        status="retired",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
        effective_to=datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC),
    )
    monkeypatch.setattr(repository, "get_definition", lambda *_args, **_kwargs: retired)

    with pytest.raises(ValueError, match="cannot be reactivated"):
        repository.activate_definition(object(), definition_uid=retired.uid)


def test_retirement_closes_the_effective_interval(monkeypatch) -> None:
    active = _definition(
        index_uid=uuid.uuid4(),
        version=1,
        status="active",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
    )
    effective_to = datetime.datetime(2025, 2, 1, tzinfo=datetime.UTC)
    calls: list[dict] = []
    monkeypatch.setattr(repository, "get_definition", lambda *_args, **_kwargs: active)

    def _update(_context, *, model, uid, values):
        calls.append(values)
        return {"row": active.model_copy(update=values).model_dump(mode="python")}

    monkeypatch.setattr(repository, "update_model", _update)

    retired = repository.retire_definition(
        object(),
        definition_uid=active.uid,
        effective_to=effective_to,
    )

    assert calls == [{"status": "retired", "effective_to": effective_to}]
    assert retired.status == "retired"
    assert retired.effective_to == effective_to


def test_cycle_detection_rejects_direct_and_transitive_dependencies(monkeypatch) -> None:
    index_a = uuid.uuid4()
    index_b = uuid.uuid4()

    monkeypatch.setattr(repository, "search_model", lambda *_args, **_kwargs: [])
    with pytest.raises(ValueError, match="dependency cycle"):
        repository.validate_no_index_cycle(
            object(),
            index_uid=index_a,
            legs=[_index_leg(index_a)],
        )

    definition_b = _definition(
        index_uid=index_b,
        version=1,
        status="active",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
    )
    existing_leg = _index_leg(index_a).model_copy(update={"definition_uid": definition_b.uid})
    responses = iter(
        [
            [definition_b.model_dump(mode="python")],
            [existing_leg.model_dump(mode="python")],
        ]
    )
    monkeypatch.setattr(repository, "search_model", lambda *_args, **_kwargs: next(responses))

    with pytest.raises(ValueError, match="dependency cycle"):
        repository.validate_no_index_cycle(
            object(),
            index_uid=index_a,
            legs=[_index_leg(index_b)],
        )


def test_definition_and_leg_creation_compensates_on_partial_failure(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    definition = _definition(
        index_uid=index_uid,
        version=1,
        status="draft",
        effective_from=datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
    )
    legs = [
        IndexCalculationLeg(
            uid=uuid.uuid4(),
            leg_key="a",
            leg_order=0,
            component_kind="asset",
            asset_uid=uuid.uuid4(),
            observable_code="price",
            input_unit="usd",
            coefficient_method="fixed",
            coefficient=1.0,
        ),
        IndexCalculationLeg(
            uid=uuid.uuid4(),
            leg_key="b",
            leg_order=1,
            component_kind="asset",
            asset_uid=uuid.uuid4(),
            observable_code="price",
            input_unit="usd",
            coefficient_method="fixed",
            coefficient=-1.0,
        ),
    ]
    create_count = 0
    deleted: list[tuple[type, uuid.UUID]] = []

    def _create(_context, *, model, values):
        nonlocal create_count
        create_count += 1
        if create_count == 3:
            raise RuntimeError("second leg failed")
        return {"row": values}

    monkeypatch.setattr(repository, "create_model", _create)
    monkeypatch.setattr(
        repository,
        "delete_model",
        lambda _context, *, model, uid: deleted.append((model, uid)),
    )

    with pytest.raises(RuntimeError, match="second leg failed"):
        repository.create_definition_and_legs(
            object(),
            definition=definition,
            legs=legs,
        )

    assert deleted == [
        (repository.IndexCalculationLegTable, legs[0].uid),
        (repository.IndexCalculationDefinitionTable, definition.uid),
    ]
