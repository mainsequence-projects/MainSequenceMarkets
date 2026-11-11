"""How the account delete reports tables of other namespaces (ADR 0050)."""

from __future__ import annotations

from msm.api.http import TableImpact
from msm.services import account_delete_impact
from msm.services.table_impact import DeleteRowsImpact


def _node(node_id, *, namespace="mainsequence.markets", node_type="meta_table", effects=()):
    return {
        "id": node_id,
        "type": node_type,
        "identifier": None if node_type == "hidden" else node_id,
        "namespace": namespace,
        "effects": list(effects),
    }


def _impact() -> TableImpact:
    return TableImpact.model_validate(
        {
            "root_uid": "account",
            "action": "delete_rows",
            "allowed": True,
            "nodes": [
                _node("Account", effects=["delete"]),
                _node("AccountHoldingsSet", effects=["delete"]),
                _node("Orders"),
                _node("provider.AccountSidecar", namespace="provider", effects=["delete"]),
                _node("provider.Orders", namespace="provider"),
                _node("hidden-1", namespace=None, node_type="hidden", effects=["delete"]),
            ],
            "edges": [
                {"source": "AccountHoldingsSet", "target": "Account", "kind": "foreign_key",
                 "effect": "cascade_delete", "on_delete": "CASCADE"},
                {"source": "provider.AccountSidecar", "target": "Account", "kind": "foreign_key",
                 "effect": "cascade_delete", "on_delete": "CASCADE"},
                {"source": "hidden-1", "target": "AccountHoldingsSet", "kind": "foreign_key",
                 "effect": "cascade_delete", "on_delete": "CASCADE"},
                {"source": "Orders", "target": "Account", "kind": "foreign_key",
                 "effect": "restrict", "on_delete": "RESTRICT"},
                {"source": "provider.Orders", "target": "Account", "kind": "foreign_key",
                 "effect": "restrict", "on_delete": "RESTRICT"},
            ],
            "blockers": [],
        }
    )


def test_only_tables_outside_markets_are_reported(monkeypatch) -> None:
    monkeypatch.setattr(
        "msm.services.table_impact.delete_rows_impact",
        lambda model: DeleteRowsImpact(impact=_impact(), warnings=["cascade summary"]),
    )

    impact = account_delete_impact()

    assert impact.other_namespace_cascades == ["provider.AccountSidecar", "A table you cannot view"]
    assert impact.other_namespace_restricts == ["provider.Orders"]
    assert impact.warnings[0] == "cascade summary"
    assert any("provider.AccountSidecar: its rows" in warning and "CASCADE" in warning for warning in impact.warnings)
    assert any("provider.Orders: its rows" in warning and "RESTRICT" in warning for warning in impact.warnings)
    assert not any(warning.startswith("Orders:") for warning in impact.warnings)


def test_an_unavailable_impact_reports_nothing_outside_markets(monkeypatch) -> None:
    monkeypatch.setattr(
        "msm.services.table_impact.delete_rows_impact",
        lambda model: DeleteRowsImpact(impact=None, warnings=["unavailable"]),
    )

    impact = account_delete_impact()

    assert impact.impact is None
    assert impact.other_namespace_cascades == []
    assert impact.other_namespace_restricts == []
    assert impact.warnings == ["unavailable"]
