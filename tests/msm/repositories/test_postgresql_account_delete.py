"""The account delete, alone and with its portfolios, on PostgreSQL (issue 91).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run these tests; they are skipped otherwise. The statements run
through psycopg as the MetaTables API binds them, a statement list in one transaction with
a row guard checked after each statement (see ``test_postgresql_account_registration``).
The account's guarded statement sits in the middle of the list when the portfolios'
statements, which `msm_portfolios` adds, follow it.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from msm.models import AccountTable
from msm.repositories.accounts import replace_account_target_positions_snapshot
from msm.services import AccountDeleteConflictError, delete_account
from msm.services.accounts import deletion
from msm_portfolios.repositories import account_portfolio_deletion as portfolio_repository
from msm_portfolios.services import delete_account_with_portfolios
from msm_portfolios.services.account_portfolio_deletion import PORTFOLIO_CHANGED_REASON
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.postgresql_markets import (
    _count,
    _dataset_rows,
    _datasets,
    _exists,
    _insert,
    _portfolio,
    _rows_in,
    dataset_reads,
    explain,
    series_indexes,
)

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}
PROVIDER_TABLE = "provider_ns__portfolioeventledgerts__copy"
PROVIDER_CONSTRAINT = "fk_provider_ns_portfolioeventledgerts_copy_portfolio"
ACCOUNT_STATEMENTS = 14
PORTFOLIO_STATEMENTS = len(DATASETS) + 1


@pytest.fixture
def markets(postgresql_markets, monkeypatch):
    def no_impact():
        raise AssertionError("The account delete must not ask MetaTables for its impact.")

    monkeypatch.setattr(deletion, "account_delete_impact", no_impact)
    monkeypatch.setattr(AccountTable, "get_meta_table", classmethod(lambda cls: None))
    engine, context, operations = postgresql_markets
    _insert(engine, "ms_markets__asset", unique_identifier="AAA")
    return engine, context, operations


def _account(engine, context, *portfolios: uuid.UUID) -> uuid.UUID:
    """An account whose target rows name each portfolio, with a virtual fund on the first."""

    account = _insert(engine, "ms_markets__account", is_paper=True, account_is_active=True)
    written = replace_account_target_positions_snapshot(
        context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account["uid"],
        account_name="PostgreSQL account",
        target_positions_date=WHEN,
        positions=[
            {
                "target_type": "portfolio",
                "target_uid": portfolio,
                "portfolio_uid": portfolio,
                "constant_notional_exposure": 1000.0,
                "metadata_json": {},
            }
            for portfolio in portfolios
        ],
        overwrite=False,
    )
    assert len(written["rows"]) == len(portfolios)
    _insert(
        engine,
        "ms_markets__virtualfund",
        account_uid=account["uid"],
        target_portfolio_uid=portfolios[0],
    )
    return account["uid"]


def _accounts(engine) -> int:
    return _count(engine, "SELECT count(*) FROM ms_markets__account")


def test_the_account_and_its_portfolios_go_in_one_transaction(markets) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)
    account = _account(engine, context, portfolio)
    operations.clear()

    deleted = delete_account_with_portfolios(context, uid=account)

    assert operations == ["read", "transaction"]
    assert deleted["deleted_portfolios"] == [
        {"uid": str(portfolio), "unique_identifier": identifier, "deleted_rows": {key: 1 for key in DATASETS}}
    ]
    assert deleted["kept_portfolios"] == []
    assert deleted["deleted_rows"]["virtual_funds"] == 1
    assert deleted["deleted_rows"]["target_positions"] == 1
    assert _accounts(engine) == 0
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier) == {key: 1 for key in DATASETS}


def test_a_restrict_key_of_another_application_keeps_the_portfolio_and_names_it(markets) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    account = _account(engine, context, portfolio)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {PROVIDER_TABLE} (time_index timestamptz NOT NULL, "
            f"portfolio_identifier varchar(255) NOT NULL CONSTRAINT {PROVIDER_CONSTRAINT} "
            "REFERENCES ms_markets__portfolio (unique_identifier) ON DELETE RESTRICT)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO {PROVIDER_TABLE} VALUES (%(time)s, %(identifier)s)",
            {"time": WHEN, "identifier": identifier},
        )
    operations.clear()

    deleted = delete_account_with_portfolios(context, uid=account)

    # The first transaction deleted nothing; the second deleted the account alone.
    assert operations == ["read", "transaction", "transaction"]
    (kept,) = deleted["kept_portfolios"]
    assert kept["uid"] == str(portfolio)
    assert PROVIDER_CONSTRAINT in kept["reason"]
    assert deleted["deleted_portfolios"] == []
    assert _accounts(engine) == 0
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_the_accounts_guard_in_the_middle_of_the_list_stops_everything(markets, monkeypatch) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    account = _account(engine, context, portfolio)
    read = portfolio_repository.read_account_with_portfolios

    def read_then_rename(context, **kwargs):
        result = read(context, **kwargs)
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE ms_markets__account SET unique_identifier = 'renamed' WHERE uid = :uid"),
                {"uid": account},
            )
        return result

    monkeypatch.setattr(portfolio_repository, "read_account_with_portfolios", read_then_rename)
    operations.clear()

    with pytest.raises(AccountDeleteConflictError, match="changed while it was being deleted"):
        delete_account_with_portfolios(context, uid=account)

    # The read, the refused transaction, and the read that tells a rename from a delete.
    assert operations == ["read", "transaction", "read"]
    assert _accounts(engine) == 1
    assert _count(engine, "SELECT count(*) FROM ms_markets__virtualfund") == 1
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_a_portfolio_referenced_in_between_stops_its_guard_and_the_account_goes_alone(
    markets, monkeypatch
) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    account = _account(engine, context, portfolio)
    other = _insert(engine, "ms_markets__account", is_paper=True, account_is_active=True)
    read = portfolio_repository.read_account_with_portfolios

    def read_then_reference(context, **kwargs):
        result = read(context, **kwargs)
        _insert(engine, "ms_markets__virtualfund", account_uid=other["uid"], target_portfolio_uid=portfolio)
        return result

    monkeypatch.setattr(portfolio_repository, "read_account_with_portfolios", read_then_reference)
    operations.clear()

    deleted = delete_account_with_portfolios(context, uid=account)

    assert operations == ["read", "transaction", "transaction"]
    assert deleted["kept_portfolios"] == [
        {"uid": str(portfolio), "unique_identifier": identifier, "reason": PORTFOLIO_CHANGED_REASON}
    ]
    assert _accounts(engine) == 1  # the other account
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_the_account_alone_goes_with_its_orders_trades_and_events(markets) -> None:
    engine, context, operations = markets
    portfolio, _identifier = _portfolio(engine)
    account = _account(engine, context, portfolio)
    with engine.connect() as connection:
        account_identifier = connection.execute(
            sa.text("SELECT unique_identifier FROM ms_markets__account WHERE uid = :uid"), {"uid": account}
        ).scalar_one()
    _insert(
        engine,
        "ms_markets__ordersts",
        order_time=WHEN,
        order_identifier="order-1",
        account_identifier=account_identifier,
        order_manager_identifier=None,
        asset_identifier="AAA",
    )
    _insert(
        engine,
        "ms_markets__tradests",
        trade_time=WHEN,
        trade_identifier="trade-1",
        account_identifier=account_identifier,
        order_identifier="order-1",
        asset_identifier="AAA",
        commission_asset_identifier=None,
        settlement_asset_identifier=None,
    )
    _insert(engine, "ms_markets__ordereventsts", event_time=WHEN, order_identifier="order-1")
    operations.clear()

    deleted = delete_account(context, uid=account)

    assert operations == ["read", "transaction"]
    assert {key: deleted["deleted_rows"][key] for key in ("orders", "trades", "order_events")} == {
        "orders": 1,
        "trades": 1,
        "order_events": 1,
    }
    assert _accounts(engine) == 0
    # The portfolio its history named stays, with its row.
    assert _exists(engine, portfolio)


def test_the_read_counts_each_portfolio_through_the_series_index(markets) -> None:
    engine, context, operations = markets
    funded, funded_identifier = _portfolio(engine)
    _rows_in(engine, funded_identifier, weights=2, values=1)
    targeted, targeted_identifier = _portfolio(engine)
    _rows_in(engine, targeted_identifier, event_ledger=3)
    empty, _empty_identifier = _portfolio(engine)
    _other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)  # No account names it: none of its rows is counted.
    account = _account(engine, context, funded, targeted, empty)
    operations.clear()

    read = portfolio_repository.read_account_with_portfolios(context, uid=account)
    plan = explain(engine, portfolio_repository.build_read_account_with_portfolios_operation(context, uid=account))

    assert operations == ["read"]
    assert {item["uid"]: item["row_counts"] for item in read["portfolios"]} == {
        str(funded): {key: {"weights": 2, "values": 1}.get(key, 0) for key in DATASETS},
        str(targeted): {key: {"event_ledger": 3}.get(key, 0) for key in DATASETS},
        str(empty): {key: 0 for key in DATASETS},
    }
    # Each dataset count reads the portfolio's rows through the series index (issue 96).
    assert dataset_reads(plan) == series_indexes()
