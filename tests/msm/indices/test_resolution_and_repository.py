from __future__ import annotations

import datetime
import uuid

import pytest

from msm.analytics.indices import IndexFormulaDefinition
from msm.repositories import indices as repository


def _definition(*, uid: uuid.UUID, index_uid: uuid.UUID, version: int) -> dict:
    return IndexFormulaDefinition(
        uid=uid,
        index_uid=index_uid,
        version=version,
        status="active",
        valid_from=datetime.datetime(2026, version, 1, tzinfo=datetime.UTC),
        formula='asset["A"].price',
        definition_hash=f"{version:064x}",
    ).model_dump(mode="python")


def test_formula_history_orders_versions(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    rows = [
        _definition(uid=uuid.uuid4(), index_uid=index_uid, version=2),
        _definition(uid=uuid.uuid4(), index_uid=index_uid, version=1),
    ]
    monkeypatch.setattr(repository, "search_model", lambda *_args, **_kwargs: {"rows": rows})

    result = repository.formula_history(object(), index_uid=index_uid)

    assert [item.version for item in result] == [1, 2]


def test_formula_cycle_detection_uses_component_index_uids(monkeypatch) -> None:
    first = uuid.uuid4()
    second = uuid.uuid4()
    definition_uid = uuid.uuid4()

    def fake_search(_context, *, model, **_kwargs):
        if model.__name__ == "IndexFormulaDefinitionTable":
            return {"rows": [_definition(uid=definition_uid, index_uid=second, version=1)]}
        return {
            "rows": [
                {
                    "uid": uuid.uuid4(),
                    "definition_uid": definition_uid,
                    "asset_uid": None,
                    "component_index_uid": first,
                    "meta_table_uid": uuid.uuid4(),
                    "observable": "price",
                }
            ]
        }

    monkeypatch.setattr(repository, "search_model", fake_search)

    with pytest.raises(ValueError, match="dependency cycle"):
        repository.validate_no_formula_cycle(
            object(),
            index_uid=first,
            component_index_uids=[second],
        )
