"""Account registration on PostgreSQL, the hosted dialect (ADR 0051, #63).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run these tests; they are skipped otherwise. Each test migrates
the database to head, runs ``msm.services.register_account`` and sends every compiled
statement the way MetaTables' PostgreSQL backend does: values bound by its
``parameters_for``, each statement executed with ``prepare=True``, a statement list in one
transaction with its row guards, and the rows answered in their wire form.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from msm.services import AccountHoldingsSnapshotExistsError, get_or_create_currency_asset, register_account
from tests.support.postgresql_markets import _scalar_rows

DAY_1 = dt.datetime(2026, 11, 10, 21, 0, tzinfo=dt.UTC)
DAY_2 = dt.datetime(2026, 11, 11, 21, 0, tzinfo=dt.UTC)


def _request(*, holdings_date=DAY_1, positions=None, overwrite=False, account_name="Venue account"):
    return {
        "account": {"unique_identifier": "venue::account-1", "account_name": account_name},
        "assets": [
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "venue_equity"},
                "snapshot": {"name": "Apple Inc.", "ticker": "AAPL"},
            }
        ],
        "cash_currency": "USD",
        "holdings_date": holdings_date.isoformat(),
        "overwrite": overwrite,
        "positions": positions
        or [
            {"asset_identifier": "venue::AAPL", "quantity": "3", "extra_details": {"lot": 1, "src": "x"}},
            {"asset_identifier": "USD", "quantity": "100", "direction": -1},
        ],
    }


def test_registration_runs_on_postgresql_and_repeats_idempotently(postgresql_markets) -> None:
    engine, context, operations = postgresql_markets

    first = register_account(context, _request())

    assert operations == ["read", "read", "transaction"]
    assert first.response["written"]["assets"] == {"created": 2, "changed": 0}
    assert first.response["written"]["asset_types"] == {"created": 2, "changed": 0}
    assert first.response["written"]["holdings"] == {"created": 2, "changed": 0}
    assert _scalar_rows(
        engine,
        "SELECT asset_identifier, quantity, direction, extra_details, time_index = target_trade_time "
        "FROM ms_markets__accountholdingsts ORDER BY asset_identifier",
    ) == [("USD", 100.0, -1, {}, True), ("venue::AAPL", 3.0, 1, {"lot": 1, "src": "x"}, True)]
    assert _scalar_rows(
        engine, "SELECT asset_identifier, name, ticker, exchange_code FROM ms_markets__assetsnapshotsts"
    ) == [("venue::AAPL", "Apple Inc.", "AAPL", "")]

    operations.clear()
    repeat = register_account(context, _request())
    assert operations == ["read", "read"]
    assert repeat.response["holdings_set_uid"] == first.response["holdings_set_uid"]

    operations.clear()
    sync = register_account(
        context,
        _request(holdings_date=DAY_2, positions=[{"asset_identifier": "venue::AAPL", "quantity": "4"}]),
    )
    assert operations == ["read", "read", "transaction"]
    assert sync.response["written"]["holdings_sets"] == {"created": 1, "changed": 0}
    assert sync.response["written"]["assets"] == {"created": 0, "changed": 0}

    with pytest.raises(AccountHoldingsSnapshotExistsError):
        register_account(context, _request(account_name="Renamed", positions=[{"asset_identifier": "USD", "quantity": "1"}]))
    assert _scalar_rows(engine, "SELECT account_name FROM ms_markets__account") == [("Venue account",)]

    replaced = register_account(
        context,
        _request(account_name="Renamed", overwrite=True, positions=[{"asset_identifier": "USD", "quantity": "1"}]),
    )
    assert replaced.response["written"]["holdings_sets"] == {"created": 0, "changed": 1}
    assert replaced.response["written"]["accounts"] == {"created": 0, "changed": 1}
    assert _scalar_rows(
        engine,
        "SELECT h.asset_identifier, h.quantity FROM ms_markets__accountholdingsts h "
        "JOIN ms_markets__accountholdingsset s ON s.uid = h.holdings_set_uid "
        f"WHERE s.uid = '{first.response['holdings_set_uid']}'",
    ) == [("USD", 1.0)]


def test_currency_get_or_create_runs_on_postgresql(postgresql_markets) -> None:
    engine, context, operations = postgresql_markets

    created = get_or_create_currency_asset(context, code="EUR")
    again = get_or_create_currency_asset(context, code="EUR")

    assert operations == ["transaction", "transaction"]
    assert uuid.UUID(str(created["uid"])) == uuid.UUID(str(again["uid"]))
    assert _scalar_rows(engine, "SELECT asset_type FROM ms_markets__assettype") == [("currency",)]
