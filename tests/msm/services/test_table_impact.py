from __future__ import annotations

from typing import Any

import pytest
from metatables import MetaTableImpact

from msm.api.http import TableImpact
from msm.services.table_impact import IMPACT_UNAVAILABLE_WARNING, delete_rows_impact

GROUP = "6d3c1a52-0f0e-4f43-9c31-1f2a3b4c5d01"
MEMBERSHIP = "6d3c1a52-0f0e-4f43-9c31-1f2a3b4c5d02"
AUDIT = "6d3c1a52-0f0e-4f43-9c31-1f2a3b4c5d03"
INDEX = "6d3c1a52-0f0e-4f43-9c31-1f2a3b4c5d04"
PORTFOLIO = "6d3c1a52-0f0e-4f43-9c31-1f2a3b4c5d05"


def _table(uid: str, identifier: str, effects: list[str]) -> dict[str, Any]:
    return {
        "id": uid,
        "type": "meta_table",
        "uid": uid,
        "identifier": identifier,
        "namespace": "mainsequence.markets",
        "table_kind": "relational",
        "physical_table_name": f"ms_markets__{identifier.lower()}",
        "effects": effects,
        "can_write": True,
    }


def _model(*, impact: dict[str, Any] | None = None, error: Exception | None = None):
    calls: list[str] = []

    class FakeMetaTable:
        def get_impact(self, *, action: str) -> MetaTableImpact:
            calls.append(action)
            if error is not None:
                raise error
            return MetaTableImpact.model_validate(impact)

    class Model:
        @classmethod
        def get_meta_table(cls):
            return FakeMetaTable()

    return Model, calls


def test_cascading_foreign_keys_become_preflight_warnings() -> None:
    impact = {
        "root_uid": GROUP,
        "action": "delete_rows",
        "allowed": True,
        "nodes": [
            _table(GROUP, "PortfolioGroup", ["delete"]),
            _table(MEMBERSHIP, "PortfolioGroupMembership", ["delete"]),
            _table(AUDIT, "PortfolioGroupAudit", []),
            {
                "id": "update:7",
                "type": "update",
                "uid": "7",
                "output_table_uid": AUDIT,
                "effects": ["input_changed"],
            },
        ],
        "edges": [
            {
                "source": MEMBERSHIP,
                "target": GROUP,
                "kind": "foreign_key",
                "effect": "cascade_delete",
                "on_delete": "cascade",
                "on_update": "no action",
            },
            {
                "source": AUDIT,
                "target": GROUP,
                "kind": "foreign_key",
                "effect": "restrict",
                "name": "fk_audit_group",
                "on_delete": "restrict",
            },
            {"source": GROUP, "target": "update:7", "kind": "reads", "effect": "reads"},
        ],
        "blockers": [],
    }
    model, calls = _model(impact=impact)

    result = delete_rows_impact(model)

    assert calls == ["delete_rows"]
    assert result.impact == TableImpact.model_validate(impact)
    # RESTRICT and update reads are in the impact graph but are not cascades.
    assert result.warnings == [
        "PortfolioGroupMembership rows that reference deleted PortfolioGroup rows "
        "are deleted too (ON DELETE CASCADE)."
    ]
    assert result.blockers == []


def test_set_null_updates_and_hidden_tables_are_described() -> None:
    impact = {
        "root_uid": INDEX,
        "action": "delete_rows",
        "allowed": False,
        "nodes": [
            {"id": "hidden:1", "type": "hidden", "effects": ["update"], "can_write": False},
            _table(INDEX, "Index", ["delete"]),
            _table(PORTFOLIO, "Portfolio", ["update"]),
            {
                "id": "relation:public.legacy_notes",
                "type": "relation",
                "physical_schema": "public",
                "physical_table_name": "legacy_notes",
                "effects": ["delete"],
                "can_write": False,
            },
        ],
        "edges": [
            {
                "source": PORTFOLIO,
                "target": INDEX,
                "kind": "foreign_key",
                "effect": "set_null",
                "on_delete": "set null",
                "on_update": "no action",
            },
            {
                "source": "hidden:1",
                "target": PORTFOLIO,
                "kind": "foreign_key",
                "effect": "cascade_update",
                "on_delete": "restrict",
                "on_update": "cascade",
            },
            {
                "source": "relation:public.legacy_notes",
                "target": INDEX,
                "kind": "foreign_key",
                "effect": "cascade_delete",
                "on_delete": "cascade",
                "on_update": "no action",
            },
        ],
        # Cascades never block; only the table itself and its DataSource do.
        "blockers": [
            {"code": "data_source_read_only", "message": "The DataSource does not accept writes."},
            {
                "code": "table_not_writable",
                "message": "You cannot write this table.",
                "node": INDEX,
            },
        ],
    }
    model, _ = _model(impact=impact)

    result = delete_rows_impact(model)

    assert result.warnings == [
        "Portfolio rows that reference deleted Index rows have that reference set to NULL "
        "(ON DELETE SET NULL).",
        "Rows in a table you cannot view that reference changed Portfolio rows are updated "
        "too (ON UPDATE CASCADE).",
        "public.legacy_notes rows that reference deleted Index rows are deleted too "
        "(ON DELETE CASCADE).",
    ]
    assert result.blockers == [
        "The DataSource does not accept writes.",
        "Index: You cannot write this table.",
    ]


def test_unbound_model_reports_impact_as_unavailable() -> None:
    class Model:
        @classmethod
        def get_meta_table(cls):
            return None

    result = delete_rows_impact(Model)

    assert result.impact is None
    assert result.warnings == [IMPACT_UNAVAILABLE_WARNING]
    assert result.blockers == []


@pytest.mark.parametrize("error", [RuntimeError("API unavailable"), ValueError("bad payload")])
def test_failed_impact_request_does_not_block_the_delete(error: Exception) -> None:
    model, calls = _model(error=error)

    result = delete_rows_impact(model)

    assert calls == ["delete_rows"]
    assert result.impact is None
    assert result.warnings == [IMPACT_UNAVAILABLE_WARNING]
    assert result.blockers == []
