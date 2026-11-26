"""An account's virtual funds for given portfolios are one read (issue 157).

The funds are those of the account's stored target allocation, the one the target write
keeps; the read finds it in the same statement. The test runs on a SQLite DataSource
served by MetaTables' own server code for the local runtime (``sqlite_markets``).
"""

from __future__ import annotations

import uuid

import pytest

from msm.api.virtual_funds import VirtualFund
from msm.repositories.operation_count import counting_operations
from tests.support.sqlite_markets import (
    WHEN,
    _account,
    _insert,
    _portfolio,
    _rows,
    serve_row_operations,
)


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    return sqlite_markets


def test_the_funds_of_the_stored_target_allocation_are_one_read(markets) -> None:
    from msm.services import add_account_target_positions_snapshot_response

    engine = markets.engine
    account = _account(engine)
    first, second, unfunded = _portfolio(engine), _portfolio(engine), _portfolio(engine)
    add_account_target_positions_snapshot_response(
        markets.context,
        account_uid=str(account),
        target_positions_date=WHEN,
        positions=[
            {"target_type": "portfolio", "portfolio_uid": str(portfolio), "weight_notional_exposure": 0.3}
            for portfolio in (first, second)
        ],
    )
    (stored,) = _rows(
        engine, "SELECT uid, account_allocation_model_uid FROM ms_markets__accounttargetallocation"
    )
    # Another allocation of the same account, with a fund of the first portfolio.
    other = _insert(
        engine,
        "ms_markets__accounttargetallocation",
        uid=uuid.uuid4().hex,
        unique_identifier="another-allocation",
        account_uid=account.hex,
        account_allocation_model_uid=stored["account_allocation_model_uid"],
    )
    _insert(
        engine,
        "ms_markets__virtualfund",
        uid=uuid.uuid4().hex,
        unique_identifier="fund-of-another-allocation",
        account_uid=account.hex,
        account_target_allocation_uid=other["uid"],
        target_portfolio_uid=first.hex,
    )

    with counting_operations() as count:
        funds = VirtualFund.filter_by_account_target(account, [first, second, unfunded])

    assert count.operations == 1
    assert sorted((fund.target_portfolio_uid, fund.account_target_allocation_uid) for fund in funds) == sorted(
        (portfolio, uuid.UUID(stored["uid"])) for portfolio in (first, second)
    )
    assert {fund.account_uid for fund in funds} == {account}
    assert VirtualFund.filter_by_account_target(account, [unfunded]) == []
    assert VirtualFund.filter_by_account_target(uuid.uuid4(), [first, second]) == []
