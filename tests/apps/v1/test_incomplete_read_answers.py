"""A read that cannot answer every row reaches an API caller typed, not as a bare 500 (#115).

A read answers ``503`` with ``error_type`` ``IncompleteReadError``, which a caller may
retry. A write whose answer is read after its commit answers ``500`` with
``IncompleteReadAfterWriteError``: the write is stored, so it must not be sent again.
``msm.client`` raises ``IncompleteReadError`` for both, ``written`` telling them apart.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm.client import MarketsClient
from msm.models import AssetTable
from msm.repositories import complete_reads
from msm.repositories.complete_reads import IncompleteReadError
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from tests.support.account_snapshots import WHEN, seed_account_snapshots


@pytest.fixture
def account(sqlite_markets, monkeypatch):
    for runtime in ("_get_holdings_runtime", "_get_target_positions_runtime"):
        monkeypatch.setattr(
            f"apps.v1.services.accounts.{runtime}",
            lambda: SimpleNamespace(context=sqlite_markets.context),
        )
    return seed_account_snapshots(sqlite_markets.engine, held=6)


@pytest.fixture
def reads_never_agree(monkeypatch):
    monkeypatch.setattr(complete_reads, "READ_PAGE_ROWS", 4)
    monkeypatch.setattr(complete_reads, "_read_pages", lambda *args, **kwargs: (None, False))


def _stored(engine, model) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.select(sa.func.count()).select_from(model.__table__)).scalar_one()


def test_a_read_that_never_agrees_answers_503_to_retry(account, reads_never_agree) -> None:
    response = TestClient(app).get(f"/api/v1/account/{account}/holdings/")

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    body = response.json()
    assert body["error_type"] == "IncompleteReadError"
    assert "Try again" in body["detail"]


def test_a_target_write_read_back_after_its_commit_says_it_is_stored(
    sqlite_markets, account, reads_never_agree
) -> None:
    with sqlite_markets.engine.connect() as connection:
        assets = [str(uid) for uid in connection.execute(sa.select(AssetTable.__table__.c.uid)).scalars()]
    before = _stored(sqlite_markets.engine, TargetPositionsStorage)

    response = TestClient(app).post(
        f"/api/v1/account/{account}/add-target-positions/",
        json={
            "target_positions_date": (WHEN + dt.timedelta(days=1)).isoformat(),
            "overwrite": False,
            "positions": [
                {"target_type": "asset", "target_uid": uid, "asset_uid": uid, "single_asset_quantity": "1"}
                for uid in assets
            ],
        },
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error_type"] == "IncompleteReadAfterWriteError"
    assert "stored" in body["detail"]
    assert "not send the write again" in body["detail"]
    assert _stored(sqlite_markets.engine, TargetPositionsStorage) == before + len(assets)


def test_a_holdings_write_read_back_after_its_commit_says_it_is_stored(
    sqlite_markets, account, monkeypatch
) -> None:
    from msm.repositories import accounts as account_repository

    write = account_repository.replace_account_holdings_snapshot

    def answers_one_row(context, **kwargs):
        # As MetaTables answers a write over its row cap: fewer rows than written.
        result = write(context, **kwargs)
        return {**result, "rows": result["rows"][:1]}

    monkeypatch.setattr(account_repository, "replace_account_holdings_snapshot", answers_one_row)
    monkeypatch.setattr(complete_reads, "_read_pages", lambda *args, **kwargs: (None, False))
    before = _stored(sqlite_markets.engine, AccountHoldingsStorage)

    response = TestClient(app).post(
        f"/api/v1/account/{account}/add-holdings/",
        json={
            "holdings_date": (WHEN + dt.timedelta(days=1)).isoformat(),
            "overwrite": False,
            "positions": [{"asset_identifier": f"held-{index}", "quantity": "2"} for index in range(3)],
        },
    )

    assert response.status_code == 500
    assert response.json()["error_type"] == "IncompleteReadAfterWriteError"
    assert _stored(sqlite_markets.engine, AccountHoldingsStorage) == before + 3


@pytest.mark.parametrize("written", [False, True])
def test_the_client_raises_the_error_the_runtime_raises(written) -> None:
    error = IncompleteReadError(written=written)
    served = SimpleNamespace(error=error)

    def fail(*args, **kwargs):
        raise served.error

    client = MarketsClient(base_url="http://testserver", session=TestClient(app))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("apps.v1.routers.accounts.get_account_target_positions", fail)
        with pytest.raises(IncompleteReadError) as raised:
            client.account_target_positions("some-account")

    assert raised.value.written is written
    assert str(raised.value) == str(error)
