"""The portfolio delete on PostgreSQL, the hosted dialect (issue 93, ADR 0049).

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to an empty, disposable ``markets_*``
database on localhost to run these tests; they are skipped otherwise. The statements run
through psycopg as the MetaTables API binds them, a statement list in one transaction with
its row guards (see ``test_postgresql_account_registration``).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from msm.models import PortfolioTable
from msm_portfolios.repositories import portfolio_deletion as repository
from msm_portfolios.services import PortfolioDeleteConflictError, delete_portfolio_record
from tests.support.postgresql_markets import (
    DATASETS,
    WHEN,
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

PROVIDER_TABLE = "provider_ns__portfoliosts__copy"
PROVIDER_CONSTRAINT = "fk_provider_ns_portfoliosts_copy_portfolio"


@pytest.fixture
def markets(postgresql_markets, monkeypatch):
    from metatables import TimeIndexMetaTable

    def refuse_delete_after_date(self, *args, **kwargs):
        raise AssertionError("The portfolio delete must not call delete_after_date.")

    monkeypatch.setattr(TimeIndexMetaTable, "delete_after_date", refuse_delete_after_date)
    monkeypatch.setattr(PortfolioTable, "get_meta_table", classmethod(lambda cls: None))
    engine, context, operations = postgresql_markets
    _insert(engine, "ms_markets__asset", unique_identifier="AAA")
    return engine, context, operations


def test_the_portfolio_and_its_seven_datasets_go_in_one_transaction(markets, monkeypatch) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)
    _insert(
        engine,
        "ms_markets__portfoliodatasetavailability",
        portfolio_uid=portfolio,
        values_meta_table_uid="0a0a0a0a-0000-4000-8000-000000000001",
        weights_meta_table_uid=None,
        signal_meta_table_uid=None,
        population_state="unavailable",
        row_count=None,
        earliest_time_index=None,
        latest_time_index=None,
    )
    group = _insert(engine, "ms_markets__portfoliogroup")
    _insert(engine, "ms_markets__portfoliogroupmembership", portfolio_group_uid=group["uid"], portfolio_uid=portfolio)
    operations.clear()

    from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage

    # The catalog names the core values table: no other application's table to check.
    core = SimpleNamespace(uid="0a0a0a0a-0000-4000-8000-000000000001")
    monkeypatch.setattr(PortfoliosStorage, "get_time_index_meta_table", classmethod(lambda cls: core))

    deleted = delete_portfolio_record(context, uid=portfolio)

    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert operations == ["read", "transaction"]
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _count(engine, "SELECT count(*) FROM ms_markets__portfoliodatasetavailability") == 0
    assert _count(engine, "SELECT count(*) FROM ms_markets__portfoliogroupmembership") == 0
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier) == {key: 1 for key in DATASETS}


def test_a_restrict_key_of_another_application_refuses_everything_and_is_named(markets) -> None:
    engine, context, operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
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

    with pytest.raises(PortfolioDeleteConflictError, match="nothing was deleted") as refused:
        delete_portfolio_record(context, uid=portfolio)

    # MetaTables' impact is unavailable here, so the database refuses the last statement.
    assert PROVIDER_CONSTRAINT in str(refused.value)
    assert operations == ["read", "transaction", "read"]
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_account_history_written_in_between_stops_the_guard(markets, monkeypatch) -> None:
    engine, context, _operations = markets
    portfolio, identifier = _portfolio(engine)
    _datasets(engine, identifier)
    count = repository.count_portfolio_delete_rows
    calls: list[object] = []

    def counted(context, *, uids):
        result = count(context, uids=uids)
        if not calls:
            account = _insert(engine, "ms_markets__account", is_paper=True, account_is_active=True)
            _insert(engine, "ms_markets__virtualfund", account_uid=account["uid"], target_portfolio_uid=portfolio)
        calls.append(uids)
        return result

    monkeypatch.setattr(repository, "count_portfolio_delete_rows", counted)

    with pytest.raises(PortfolioDeleteConflictError, match=r"VirtualFundTable\.target_portfolio_uid"):
        delete_portfolio_record(context, uid=portfolio)

    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_one_read_counts_several_portfolios_in_each_dataset(markets) -> None:
    engine, context, operations = markets
    first, first_identifier = _portfolio(engine)
    _rows_in(engine, first_identifier, weights=2, rebalance_state=1)
    second, second_identifier = _portfolio(engine)
    _rows_in(engine, second_identifier, values=3, state=1, cash_flows=2)
    empty, _empty_identifier = _portfolio(engine)
    _other, other_identifier = _portfolio(engine)
    _datasets(engine, other_identifier)  # Not selected: none of its rows is counted.
    operations.clear()

    counted = repository.count_portfolio_delete_rows(context, uids=[first, second, empty, uuid.uuid4()])

    assert operations == ["read"]
    assert {uid: {key: row[key] for key in DATASETS} for uid, row in counted.items()} == {
        str(first): {key: {"weights": 2, "rebalance_state": 1}.get(key, 0) for key in DATASETS},
        str(second): {key: {"values": 3, "state": 1, "cash_flows": 2}.get(key, 0) for key in DATASETS},
        str(empty): {key: 0 for key in DATASETS},
    }


def test_each_count_reads_the_portfolios_rows_through_the_series_index(markets) -> None:
    engine, context, _operations = markets
    portfolios = []
    for _ in range(3):
        portfolio, identifier = _portfolio(engine)
        _datasets(engine, identifier)
        portfolios.append(portfolio)

    plan = explain(engine, repository.build_count_portfolio_delete_rows_operation(context, uids=portfolios))

    # Each dataset count reads the portfolio's rows through the series index (issue 96).
    assert dataset_reads(plan) == series_indexes()
