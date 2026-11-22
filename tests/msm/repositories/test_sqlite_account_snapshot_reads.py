"""An account's target, holdings and holdings by fund, each in as few reads as it can.

Each MetaTables request is a round trip (issue 94). A target read and a holdings read are
one statement; holdings by fund are two, the account's set and then its funds; a target
write reads the account, writes, and reads the snapshot back.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from metatables.api.backend.backends.restricted_sql import parameters_for
from msm.repositories.accounts import (
    replace_account_holdings_snapshot,
    replace_account_target_positions_snapshot,
)
from msm.services import (
    add_account_target_positions_snapshot_response,
    get_account_target_positions_snapshot_response,
)
from msm.services.accounts import (
    get_account_holdings_by_fund_response,
    get_account_holdings_snapshot_response,
)
from msm.services.accounts.account_virtual_allocations import (
    allocate_account_virtual_funds_in_context,
)
from tests.support.account_registration import _record_operations
from tests.support.account_snapshots import account_read_operations, seed_account_snapshots
from tests.support.sqlite_markets import WHEN, _account, _asset, _insert, _portfolio, _rows

EARLIER = WHEN - dt.timedelta(days=1)


def _target(sqlite_markets, account, positions, *, when=WHEN):
    return replace_account_target_positions_snapshot(
        sqlite_markets.context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account,
        account_name="SQLite account",
        target_positions_date=when,
        positions=positions,
        overwrite=False,
    )


def _holdings(sqlite_markets, account, positions, *, when=WHEN):
    return replace_account_holdings_snapshot(
        sqlite_markets.context,
        holdings_set_uid=uuid.uuid4(),
        account_uid=account,
        holdings_date=when,
        positions=[{"asset_identifier": name, "quantity": quantity} for name, quantity in positions],
        overwrite=False,
    )


def _in_portfolio(portfolio, weight):
    return {
        "target_type": "portfolio",
        "target_uid": portfolio,
        "portfolio_uid": portfolio,
        "weight_notional_exposure": weight,
        "metadata_json": {},
    }


def _in_asset(asset, quantity):
    return {
        "target_type": "asset",
        "target_uid": asset,
        "asset_uid": asset,
        "single_asset_quantity": quantity,
        "metadata_json": {},
    }


def _copies(engine, table_name, template, rows):
    """Insert ``rows``, each ``template`` with its own values, in one statement."""

    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)
    with engine.begin() as connection:
        connection.execute(table.insert(), [{**template, **row} for row in rows])


def _snapshot(engine, name, when, label, ticker):
    _insert(
        engine,
        "ms_markets__assetsnapshotsts",
        time_index=when,
        asset_identifier=name,
        name=label,
        ticker=ticker,
    )


def test_a_target_read_is_one_statement_with_its_labels(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    asset = _asset(engine, "AAPL")
    _snapshot(engine, "AAPL", EARLIER - dt.timedelta(days=9), "Apple old", "AAPL0")
    _snapshot(engine, "AAPL", EARLIER, "Apple Inc.", "AAPL")
    portfolio = _portfolio(engine)
    (identifier,) = _rows(
        engine,
        "SELECT unique_identifier FROM ms_markets__portfolio WHERE uid = :uid",
        uid=portfolio.hex,
    )
    _target(sqlite_markets, account, [_in_portfolio(portfolio, 0.5)], when=EARLIER)
    _target(sqlite_markets, account, [_in_portfolio(portfolio, 0.4), _in_asset(asset, 10.0)])
    operations = _record_operations(monkeypatch)

    def read(**kwargs):
        return get_account_target_positions_snapshot_response(
            sqlite_markets.context, account_uid=str(account), **kwargs
        )

    latest, earliest, at_earlier, without_detail = (
        read(),
        read(order="asc"),
        read(target_positions_date=EARLIER),
        read(include_asset_detail=False),
    )

    assert operations == ["read"] * 4
    assert latest["target_positions_date"] == WHEN
    asset_row, portfolio_row = latest["positions"]
    assert (asset_row["unique_identifier"], asset_row["single_asset_quantity"]) == ("AAPL", "10.0")
    assert uuid.UUID(asset_row["asset"]["uid"]) == asset
    assert asset_row["asset"]["unique_identifier"] == "AAPL"
    assert asset_row["asset"]["current_snapshot"] == {"name": "Apple Inc.", "ticker": "AAPL"}
    assert portfolio_row["unique_identifier"] == identifier["unique_identifier"]
    assert uuid.UUID(portfolio_row["portfolio"]["uid"]) == portfolio
    assert portfolio_row["weight_notional_exposure"] == "0.4"
    assert earliest == at_earlier
    assert earliest["target_positions_date"] == EARLIER
    assert [row["weight_notional_exposure"] for row in earliest["positions"]] == ["0.5"]
    # Without asset detail an asset row keeps its uid as its identifier, as before.
    assert without_detail["positions"][0]["asset"] is None
    assert uuid.UUID(without_detail["positions"][0]["unique_identifier"]) == asset


def test_a_target_read_without_a_snapshot_is_empty_and_without_the_account_none(
    sqlite_markets, monkeypatch
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _target(sqlite_markets, account, [_in_portfolio(_portfolio(engine), 0.5)])
    no_target = _account(engine)
    operations = _record_operations(monkeypatch)

    def read(account_uid, **kwargs):
        return get_account_target_positions_snapshot_response(
            sqlite_markets.context, account_uid=account_uid, **kwargs
        )

    empty = {"target_positions_date": None, "position_set_uid": None, "positions": []}
    for owner, answer in (
        (no_target, read(str(no_target))),
        (account, read(str(account), target_positions_date=EARLIER)),
    ):
        assert uuid.UUID(answer.pop("related_account_uid")) == owner
        assert answer == empty
    assert read(str(uuid.uuid4())) is None
    assert operations == ["read"] * 3


def test_a_target_read_finds_the_latest_of_many_snapshots(sqlite_markets) -> None:
    # The latest snapshot is the 502nd row of the table: a scan of 500 rows in
    # storage order, then a choice in Python, would miss it.
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    _target(sqlite_markets, account, [_in_portfolio(portfolio, 0.1)], when=EARLIER)
    (template,) = _rows(engine, "SELECT * FROM ms_markets__positionset")
    _copies(
        engine,
        "ms_markets__positionset",
        template,
        [
            {"uid": uuid.uuid4().hex, "position_set_time": EARLIER - dt.timedelta(minutes=minute)}
            for minute in range(1, 501)
        ],
    )
    _target(sqlite_markets, account, [_in_portfolio(portfolio, 0.9)])

    latest = get_account_target_positions_snapshot_response(
        sqlite_markets.context, account_uid=str(account)
    )

    assert latest["target_positions_date"] == WHEN
    assert [row["weight_notional_exposure"] for row in latest["positions"]] == ["0.9"]


def test_a_target_read_labels_a_portfolio_whatever_the_number_of_portfolios(
    sqlite_markets,
) -> None:
    # Labels used to come from the first 500 portfolios in storage order.
    engine = sqlite_markets.engine
    account = _account(engine)
    first = _portfolio(engine)
    (template,) = _rows(engine, "SELECT * FROM ms_markets__portfolio WHERE uid = :uid", uid=first.hex)
    _copies(
        engine,
        "ms_markets__portfolio",
        template,
        [{"uid": uuid.uuid4().hex, "unique_identifier": f"filler-{index}"} for index in range(500)],
    )
    named = _portfolio(engine)
    _target(sqlite_markets, account, [_in_portfolio(named, 1.0)])

    (position,) = get_account_target_positions_snapshot_response(
        sqlite_markets.context, account_uid=str(account)
    )["positions"]

    assert uuid.UUID(position["portfolio"]["uid"]) == named
    assert position["unique_identifier"] == f"portfolio-{named.hex[:8]}"


def test_a_target_write_reads_the_account_and_then_the_snapshot_once(
    sqlite_markets, monkeypatch
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    asset = _asset(engine, "AAPL")
    portfolio = _portfolio(engine)
    operations = _record_operations(monkeypatch)

    written = add_account_target_positions_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        target_positions_date=WHEN,
        positions=[
            {"target_type": "portfolio", "target_uid": str(portfolio), "portfolio_uid": str(portfolio),
             "weight_notional_exposure": 0.6},
            {"target_type": "asset", "target_uid": str(asset), "asset_uid": str(asset),
             "single_asset_quantity": 5},
        ],
    )
    missing = add_account_target_positions_snapshot_response(
        sqlite_markets.context,
        account_uid=str(uuid.uuid4()),
        target_positions_date=WHEN,
        positions=[],
    )

    assert operations == ["read", "transaction", "read", "read"]
    assert missing is None
    assert written == get_account_target_positions_snapshot_response(
        sqlite_markets.context, account_uid=str(account)
    )
    assert [row["target_type"] for row in written["positions"]] == ["asset", "portfolio"]


def test_a_holdings_read_is_one_statement(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    asset = _asset(engine, "AAPL")
    _asset(engine, "MSFT")
    _snapshot(engine, "AAPL", EARLIER - dt.timedelta(days=9), "Apple old", "AAPL0")
    _snapshot(engine, "AAPL", EARLIER, "Apple Inc.", "AAPL")
    _holdings(sqlite_markets, account, [("AAPL", 3.0)], when=EARLIER)
    _holdings(sqlite_markets, account, [("AAPL", 5.0), ("MSFT", 2.0)])
    no_holdings = _account(engine)
    operations = _record_operations(monkeypatch)

    def read(account_uid=str(account), **kwargs):
        return get_account_holdings_snapshot_response(
            sqlite_markets.context, account_uid=account_uid, **kwargs
        )

    latest, earliest, at_earlier, without_detail = (
        read(),
        read(order="asc"),
        read(holdings_date=EARLIER),
        read(include_asset_detail=False),
    )
    empty, missing = read(str(no_holdings)), read(str(uuid.uuid4()))

    assert operations == ["read"] * 6
    assert latest["holdings_date"] == WHEN
    assert [(row["asset_identifier"], row["quantity"]) for row in latest["holdings"]] == [
        ("AAPL", "5.0"),
        ("MSFT", "2.0"),
    ]
    assert uuid.UUID(latest["holdings"][0]["asset"]["uid"]) == asset
    assert latest["holdings"][0]["asset"]["current_snapshot"] == {
        "name": "Apple Inc.",
        "ticker": "AAPL",
    }
    assert latest["holdings"][1]["asset"]["current_snapshot"] == {"name": None, "ticker": None}
    assert earliest == at_earlier
    assert [(row["asset_identifier"], row["quantity"]) for row in earliest["holdings"]] == [
        ("AAPL", "3.0")
    ]
    assert [row["asset"] for row in without_detail["holdings"]] == [None, None]
    assert empty == {"holdings_set_uid": None, "holdings_date": None, "holdings": []}
    assert missing is None


def test_holdings_by_fund_are_the_account_set_then_its_funds(sqlite_markets, monkeypatch) -> None:
    # Two funds of two assets each share MSFT; the account also holds TSLA, in no fund.
    engine = sqlite_markets.engine
    account = _account(engine)
    assets = {name: _asset(engine, name) for name in ("AAPL", "MSFT", "JNJ", "TSLA")}
    fund_a, fund_b = _portfolio(engine), _portfolio(engine)
    _holdings(
        sqlite_markets,
        account,
        [("AAPL", 1_100.0), ("MSFT", 600.0), ("JNJ", 750.0), ("TSLA", 1_100.0)],
    )
    target = _target(
        sqlite_markets, account, [_in_portfolio(fund_a, 0.4), _in_portfolio(fund_b, 0.3)]
    )
    allocate_account_virtual_funds_in_context(
        sqlite_markets.context,
        account_uid=account,
        position_set_uid=uuid.UUID(str(target["rows"][0]["position_set_uid"])),
        valuation_time=WHEN,
        sized_targets=[
            {
                "target_type": "portfolio",
                "target_uid": str(fund),
                "positions": [
                    {"asset_uid": str(assets[name]), "quantity": quantity, "direction": 1}
                    for name, quantity in positions
                ],
            }
            for fund, positions in (
                (fund_a, [("AAPL", 1_000.0), ("MSFT", 500.0)]),
                (fund_b, [("MSFT", 100.0), ("JNJ", 750.0)]),
            )
        ],
    )
    no_holdings = _account(engine)
    operations = _record_operations(monkeypatch)

    by_fund = get_account_holdings_by_fund_response(
        sqlite_markets.context, account_uid=str(account)
    )
    empty = get_account_holdings_by_fund_response(
        sqlite_markets.context, account_uid=str(no_holdings)
    )
    missing = get_account_holdings_by_fund_response(
        sqlite_markets.context, account_uid=str(uuid.uuid4())
    )

    assert operations == ["read", "read", "read", "read"]
    assert by_fund["holdings_date"] == WHEN
    funds = {
        uuid.UUID(group["target_portfolio_uid"]): [
            (row["asset_identifier"], row["quantity"]) for row in group["holdings"]
        ]
        for group in by_fund["funds"]
    }
    assert funds == {
        fund_a: [("AAPL", "1000.0"), ("MSFT", "500.0")],
        fund_b: [("JNJ", "750.0"), ("MSFT", "100.0")],
    }
    assert [
        (row["asset_identifier"], row["residual_signed_quantity"]) for row in by_fund["residuals"]
    ] == [("AAPL", "100.0"), ("TSLA", "1100.0")]
    (apple,) = (
        row for group in by_fund["funds"] for row in group["holdings"] if row["asset_identifier"] == "AAPL"
    )
    assert uuid.UUID(apple["asset"]["uid"]) == assets["AAPL"]
    assert empty["funds"] == empty["residuals"] == []
    assert empty["source_account_holdings_set_uid"] is None
    assert missing is None


def test_holdings_by_fund_find_the_latest_of_many_holdings_sets(sqlite_markets) -> None:
    # The latest holdings set is the 502nd row of its table (see the target test).
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAPL")
    _holdings(sqlite_markets, account, [("AAPL", 1.0)], when=EARLIER)
    (template,) = _rows(engine, "SELECT * FROM ms_markets__accountholdingsset")
    _copies(
        engine,
        "ms_markets__accountholdingsset",
        template,
        [
            {"uid": uuid.uuid4().hex, "time_index": EARLIER - dt.timedelta(minutes=minute)}
            for minute in range(1, 501)
        ],
    )
    _holdings(sqlite_markets, account, [("AAPL", 2.0)])

    by_fund = get_account_holdings_by_fund_response(
        sqlite_markets.context, account_uid=str(account)
    )

    assert by_fund["holdings_date"] == WHEN
    assert [(row["asset_identifier"], row["residual_signed_quantity"]) for row in by_fund["residuals"]] == [
        ("AAPL", "2.0")
    ]


@pytest.mark.parametrize(
    ("idle", "set_only", "holders", "held"),
    [(30, 0, 1, 480), (0, 30, 1, 480), (100, 500, 1, 500), (0, 5, 3, 367)],
    ids=["idle funds", "funds with a set alone", "both at their caps", "past the rows' cap"],
)
def test_holdings_by_fund_keep_a_place_for_allocations_and_for_funds(
    sqlite_markets, idle, set_only, holders, held
) -> None:
    # Funds without rows once took their places among the 500 allocation rows, which
    # then answered as unallocated.
    account = seed_account_snapshots(
        sqlite_markets.engine, held=held, holders=holders, idle=idle, set_only=set_only
    )

    by_fund = get_account_holdings_by_fund_response(
        sqlite_markets.context, account_uid=str(account)
    )

    allocated = [len(group["holdings"]) for group in by_fund["funds"]]
    # Every fund with a set, also one whose rows are past the cap; no fund with nothing.
    assert len(allocated) == set_only + holders
    assert sum(allocated) >= min(holders * held, 500)
    if holders * held <= 500:
        assert by_fund["residuals"] == []


def test_the_asset_snapshots_are_not_read_once_per_asset(sqlite_markets, monkeypatch) -> None:
    # 100 assets held and 5,000 snapshots: one lookup an asset reads 500,000 entries.
    account = seed_account_snapshots(sqlite_markets.engine, held=100, other_snapshots=5_000)

    for operation in account_read_operations(monkeypatch, sqlite_markets.context, account):
        assert _instructions(sqlite_markets.engine, operation) < 500_000


def _instructions(engine, operation) -> int:
    """SQLite's virtual machine instructions for a compiled read, to the thousand."""

    statement = operation.statement
    values = parameters_for(statement.parameters, statement.parameter_types, "sqlite")
    steps = []
    connection = engine.raw_connection()
    try:
        connection.driver_connection.set_progress_handler(lambda: steps.append(1) and None, 1_000)
        cursor = connection.cursor()
        cursor.execute(statement.sql, tuple(values) if isinstance(values, list) else values)
        cursor.fetchall()
    finally:
        connection.driver_connection.set_progress_handler(None, 0)
        connection.close()
    return 1_000 * len(steps)
