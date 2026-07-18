from __future__ import annotations

from types import SimpleNamespace

from msm.api import (
    DerivedIndex,
    IndexCalculationDefinition,
    IndexCalculationError,
    IndexCalculationLeg,
    calculate_index,
)
from msm.api.indices import compute_definition_hash
from msm.models import (
    IndexCalculationDefinitionTable,
    IndexCalculationLegTable,
    IndexTable,
    IndexTypeTable,
)


def test_index_public_surface_reexports_derived_contracts() -> None:
    assert DerivedIndex.__name__ == "DerivedIndex"
    assert IndexCalculationDefinition.__name__ == "IndexCalculationDefinition"
    assert IndexCalculationLeg.__name__ == "IndexCalculationLeg"
    assert issubclass(IndexCalculationError, ValueError)
    assert callable(calculate_index)
    assert callable(compute_definition_hash)


def test_derived_index_start_engine_requests_only_minimal_relational_graph(monkeypatch) -> None:
    runtime = SimpleNamespace(context=object())
    calls: list[dict] = []

    def _start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.start_engine", _start_engine)

    assert DerivedIndex.start_engine(namespace="mainsequence.test") is runtime
    assert calls == [
        {
            "models": [
                IndexTypeTable,
                IndexTable,
                IndexCalculationDefinitionTable,
                IndexCalculationLegTable,
            ],
            "namespace": "mainsequence.test",
        }
    ]
