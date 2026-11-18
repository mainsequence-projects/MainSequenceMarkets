"""A PATCH whose update is refused before it is sent answers 400 (MainSequenceMarkets#87).

``update_model`` refuses an update that names no column, or that sets a ``NOT NULL``
column to ``NULL``, with a ``ValueError``; the PATCH routes answer it as a bad request.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app

REFUSAL = "Update of CalendarTable 1 cannot set display_name to NULL; the column is NOT NULL."


@pytest.mark.parametrize(
    ("target", "route"),
    [
        ("apps.v1.routers.calendars.update_calendar", "/api/v1/calendar/{uid}/"),
        ("apps.v1.routers.portfolio_groups.update_portfolio_group", "/api/v1/portfolio-group/{uid}/"),
        ("apps.v1.routers.asset_categories.update_asset_category", "/api/v1/asset-category/{uid}/"),
    ],
)
def test_a_refused_update_answers_400(monkeypatch, target: str, route: str) -> None:
    received: list[dict] = []

    def refuse(*, uid, payload):
        received.append(dict(payload))
        raise ValueError(REFUSAL)

    monkeypatch.setattr(target, refuse)

    response = TestClient(app).patch(route.format(uid=uuid.uuid4()), json={"display_name": None})

    assert response.status_code == 400
    assert response.json()["detail"] == REFUSAL
    # The explicit null reaches the update; an unset field would not.
    assert received == [{"display_name": None}]
