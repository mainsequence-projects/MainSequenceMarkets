"""The bulk portfolio delete route on SQLite counts its selection once (issue 96).

Runs the route on the real ``apps.v1.services.portfolios`` services and a migrated
SQLite file. Split from ``tests/msm_portfolios/services/test_sqlite_portfolio_delete.py``,
whose harness and data it shares through ``tests/support/portfolio_delete.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.support.portfolio_delete import (
    DATASETS,
    _dataset_rows,
    _deletes,
    _exists,
    _portfolio_with,
    _reads,
    portfolio_markets,
)


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    """The harness, with no MetaTables impact and no delete-after-date call allowed."""

    return portfolio_markets(sqlite_markets, monkeypatch)


def test_the_bulk_delete_route_counts_the_selection_once(markets, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from apps.v1.main import app
    from apps.v1.services import portfolios as portfolio_service

    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, *DATASETS)
    second, second_identifier = _portfolio_with(engine, "values")
    monkeypatch.setattr(
        portfolio_service, "_get_delete_runtime", lambda: SimpleNamespace(context=markets.context)
    )
    markets.statements.clear()

    response = TestClient(app).post(
        "/api/v1/portfolio/bulk-delete/",
        json={"selection": {"mode": "explicit", "uids": [str(first), str(second)]}, "options": {}},
    )

    assert response.status_code == 200, response.text
    assert {item["uid"]: item["deleted_rows"] for item in response.json()["deleted"]} == {
        str(first): {key: 1 for key in DATASETS},
        str(second): {key: int(key == "values") for key in DATASETS},
    }
    # The preflight's read, then one transaction per portfolio.
    assert len(_reads(markets)) == 1
    assert len(_deletes(markets)) == 2 * (len(DATASETS) + 1)
    assert not _exists(engine, first) and set(_dataset_rows(engine, first_identifier).values()) == {0}
    assert not _exists(engine, second) and set(_dataset_rows(engine, second_identifier).values()) == {0}
