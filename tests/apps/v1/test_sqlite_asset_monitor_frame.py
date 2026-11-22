"""The asset monitor frame pages in the database on SQLite, past 500 assets (#116).

It read the first 500 assets and filtered ``asset_type`` and sliced the page in Python, so
with 1,101 assets ``limit=200`` answered 100 rows at offset 400 and none at offset 600.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from tests.support.asset_master_lists import seed_assets


@pytest.fixture
def client(sqlite_markets, monkeypatch) -> TestClient:
    monkeypatch.setattr(
        "apps.v1.services.assets._get_runtime",
        lambda: SimpleNamespace(context=sqlite_markets.context),
    )
    return TestClient(app)


def _frame_pages(client: TestClient, **params) -> list[list[str]]:
    pages = []
    for offset in range(0, 1_400, 200):
        response = client.get(
            "/api/v1/asset/monitor/frame/", params={**params, "limit": 200, "offset": offset}
        )
        assert response.status_code == 200, response.text
        pages.append([row["unique_identifier"] for row in response.json()["rows"]])
    return pages


@pytest.mark.parametrize("asset_type", [None, "equity"])
def test_the_monitor_frame_reaches_every_asset(sqlite_markets, client, asset_type) -> None:
    equities = seed_assets(sqlite_markets.engine, 1_101, prefix="eq", asset_type="equity")
    bonds = seed_assets(sqlite_markets.engine, 99, prefix="bond", asset_type="bond")
    expected = [
        asset["unique_identifier"] for asset in (equities if asset_type else bonds + equities)
    ]

    pages = _frame_pages(client, **({"asset_type": asset_type} if asset_type else {}))

    assert [len(page) for page in pages] == [
        len(expected[offset : offset + 200]) for offset in range(0, 1_400, 200)
    ]
    assert [identifier for page in pages for identifier in page] == expected
