"""The core account delete leaves the portfolios its history names, with their datasets.

Split from ``tests/msm/repositories/test_sqlite_account_delete.py``, whose harness and data
it shares through ``tests/support/account_delete.py``.
"""

from __future__ import annotations

import pytest

from msm.services import delete_account
from tests.support.account_delete import (
    _exists,
    _history,
    account_markets,
)
from tests.support.account_portfolio_delete import DATASETS, _dataset_rows, _portfolio_with_data
from tests.support.sqlite_markets import (
    _account,
    _rows,
)


@pytest.fixture
def sqlite_markets(sqlite_markets, monkeypatch):
    return account_markets(sqlite_markets, monkeypatch)


def test_the_portfolios_its_history_names_stay_with_their_data(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, account, portfolio)

    deleted = delete_account(sqlite_markets.context, uid=account)

    assert "deleted_portfolios" not in deleted
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert not _rows(engine, "SELECT uid FROM ms_markets__account WHERE uid = :uid", uid=account.hex)
