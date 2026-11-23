"""The account delete with the portfolios only it used, on SQLite (ADR 0050, issue 91).

`msm_portfolios.services` owns this delete: it composes core's account read and
statements with the portfolios' own. The harness, its request log and the data come
from `tests/support/account_delete.py`, as in
`tests/msm/repositories/test_sqlite_account_delete.py`.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.sql.util import find_tables

from msm.repositories.account_deletion import ACCOUNT_DELETE_TABLES
from msm.services import AccountDeleteConflictError
from msm_portfolios.repositories import account_portfolio_deletion as repository
from msm_portfolios.repositories.account_portfolio_deletion import (
    account_with_portfolios_delete_statements,
)
from msm_portfolios.services import (
    bulk_delete_accounts_with_portfolios,
    delete_account_with_portfolios,
    preflight_account_delete_with_portfolios,
    preflight_bulk_delete_accounts_with_portfolios,
)
from msm_portfolios.services.account_portfolio_deletion import PORTFOLIO_CHANGED_REASON
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.account_delete import (
    EVERY_TABLE_COUNTS,
    MARKETS_TABLES,
    _account_rows,
    _create_provider_tables,
    _exists,
    _history,
    _identifier,
    _impact_unavailable,
    _order,
    _portfolio_identifier,
    _provider_statements,
    account_markets,
)
from tests.support.account_portfolio_delete import DATASETS, _dataset_rows, _portfolio_with_data
from tests.support.portfolio_delete import series_index
from tests.support.sqlite_markets import (
    WHEN,
    _account,
    _count,
    _insert,
    _portfolio,
    _portfolio_position,
    _write_holdings,
    _write_target,
    table_reads,
)

PORTFOLIO_TABLES = {
    *DATASETS.values(),
    "ms_markets__portfolio",
    "ms_markets__virtualfund",
    "ms_markets__targetpositionsts",
}
ACCOUNT_STATEMENTS = len(ACCOUNT_DELETE_TABLES)
WITH_PORTFOLIOS = ACCOUNT_STATEMENTS + len(DATASETS) + 1


@pytest.fixture
def sqlite_markets(sqlite_markets, monkeypatch):
    return account_markets(sqlite_markets, monkeypatch)


# Statements ------------------------------------------------------------------------------


def test_the_portfolios_follow_the_account_in_the_same_list() -> None:
    portfolios = [uuid.uuid4(), uuid.uuid4()]
    statements = account_with_portfolios_delete_statements(
        uid=uuid.uuid4(),
        unique_identifier="account-1",
        row_counts=EVERY_TABLE_COUNTS,
        portfolio_uids=portfolios,
    )

    assert len(statements) == WITH_PORTFOLIOS <= 32
    assert statements[ACCOUNT_STATEMENTS - 1].label == "account"
    assert [getattr(item, "statement", item).table.name for item in statements[:ACCOUNT_STATEMENTS]] == [
        table.model.__table__.name for table in ACCOUNT_DELETE_TABLES
    ]
    assert [getattr(item, "statement", item).table.name for item in statements[ACCOUNT_STATEMENTS:]] == [
        *DATASETS.values(),
        "ms_markets__portfolio",
    ]
    for item in statements[ACCOUNT_STATEMENTS:]:
        statement = getattr(item, "statement", item)
        assert {table.name for table in find_tables(statement, include_crud=True)} <= PORTFOLIO_TABLES
    assert statements[-1].label == "portfolios" and statements[-1].expect_rows == 2


# The delete ------------------------------------------------------------------------------


def test_a_missing_account_deletes_nothing(sqlite_markets) -> None:
    missing = uuid.uuid4()

    assert delete_account_with_portfolios(sqlite_markets.context, uid=missing) is None
    assert preflight_account_delete_with_portfolios(sqlite_markets.context, uid=missing) is None
    assert sqlite_markets.requests == ["read", "read"]


def test_a_portfolio_only_the_account_used_goes_with_all_its_data(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    history = _history(sqlite_markets, account, portfolio)
    # It belongs to a group: its membership goes by CASCADE.
    group = _insert(engine, "ms_markets__portfoliogroup")
    _insert(engine, "ms_markets__portfoliogroupmembership", portfolio_group_uid=group["uid"], portfolio_uid=portfolio.hex)
    other, other_identifier = _portfolio_with_data(engine)
    sqlite_markets.requests.clear()

    preflight = preflight_account_delete_with_portfolios(sqlite_markets.context, uid=account)
    deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    expected = {"uid": str(portfolio), "unique_identifier": identifier}
    assert preflight["portfolios"] == [{**expected, "row_counts": {key: 1 for key in DATASETS}}]
    assert preflight["kept_portfolios"] == []
    assert deleted["deleted_portfolios"] == [{**expected, "deleted_rows": {key: 1 for key in DATASETS}}]
    assert deleted["kept_portfolios"] == []
    assert deleted["detail"] == f"Account {history['identifier']!r} deleted with its history and 1 portfolio."
    assert deleted["deleted_rows"] == preflight["row_counts"]
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _count(engine, "ms_markets__portfoliogroupmembership") == 0
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier) == {key: 1 for key in DATASETS}
    assert sqlite_markets.requests == ["read", "read", f"transaction:{WITH_PORTFOLIOS}"]


def test_a_portfolio_only_named_by_the_accounts_targets_goes_too(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    funded, _funded_identifier = _portfolio_with_data(engine)
    targeted, targeted_identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, account, funded, also_targets=(targeted,))

    deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    assert {item["uid"] for item in deleted["deleted_portfolios"]} == {str(funded), str(targeted)}
    assert not _exists(engine, funded) and not _exists(engine, targeted)
    assert set(_dataset_rows(engine, targeted_identifier).values()) == {0}


def _portfolio_rows(engine, **rows: int) -> tuple[uuid.UUID, str]:
    """A portfolio with ``rows[key]`` rows in dataset ``key``, one a day."""

    portfolio = _portfolio(engine)
    identifier = _portfolio_identifier(engine, portfolio)
    for key, count in rows.items():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(DATASETS[key])
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        for day in range(count):
            _insert(
                engine,
                DATASETS[key],
                time_index=WHEN + dt.timedelta(days=day),
                portfolio_identifier=identifier,
                **assets,
            )
    return portfolio, identifier


def test_one_read_counts_each_named_portfolio_in_each_dataset(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    funded, funded_identifier = _portfolio_rows(engine, weights=1, values=2)
    targeted, targeted_identifier = _portfolio_rows(engine, event_ledger=1, cash_flows=3)
    empty, empty_identifier = _portfolio_rows(engine)
    _history(sqlite_markets, account, funded, also_targets=(targeted, empty))
    _portfolio_with_data(engine)  # No account names it: none of its rows is counted.
    sqlite_markets.requests.clear()

    read = repository.read_account_with_portfolios(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read"]
    assert {item["uid"]: item["row_counts"] for item in read["portfolios"]} == {
        str(funded): {key: {"weights": 1, "values": 2}.get(key, 0) for key in DATASETS},
        str(targeted): {key: {"event_ledger": 1, "cash_flows": 3}.get(key, 0) for key in DATASETS},
        str(empty): {key: 0 for key in DATASETS},
    }
    assert sorted(item["unique_identifier"] for item in read["portfolios"]) == sorted(
        [funded_identifier, targeted_identifier, empty_identifier]
    )


def test_each_count_reads_the_portfolios_rows_through_the_series_index(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolios = [_portfolio_with_data(engine)[0] for _ in range(3)]
    _history(sqlite_markets, account, portfolios[0], also_targets=tuple(portfolios[1:]))

    reads = table_reads(
        engine,
        repository.build_read_account_with_portfolios_operation(sqlite_markets.context, uid=account),
        DATASETS.values(),
    )

    # Each dataset count is one index search on the portfolio, never a scan (issue 96).
    for table in PORTFOLIO_DATASET_TABLES:
        (step,) = reads[table.table_name]
        assert step.startswith("SEARCH") and series_index(table) in step, step
        assert "(portfolio_identifier=?)" in step, step


def test_an_account_without_portfolios_is_deleted_alone(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])
    sqlite_markets.requests.clear()

    deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    assert deleted["deleted_portfolios"] == [] and deleted["kept_portfolios"] == []
    # Holdings, holdings sets and the account: the read found every other table empty.
    assert sqlite_markets.requests == ["read", "transaction:3"]


# Kept portfolios -------------------------------------------------------------------------


@pytest.mark.parametrize("reference", ["target_positions", "virtual_funds"])
def test_a_portfolio_another_account_uses_stays_with_its_data(sqlite_markets, reference: str) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    shared, shared_identifier = _portfolio_with_data(engine)
    own, own_identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, account, own, also_targets=(shared,))
    other = _account(engine)
    if reference == "target_positions":
        assert _write_target(sqlite_markets, other, [_portfolio_position(shared)])["rows"]
        reason = "1 target-position row of other accounts names it."
    else:
        _insert(engine, "ms_markets__virtualfund", unique_identifier="other-fund", account_uid=other.hex, target_portfolio_uid=shared.hex)
        reason = "1 virtual fund of other accounts targets it."

    preflight = preflight_account_delete_with_portfolios(sqlite_markets.context, uid=account)
    deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    kept = [{"uid": str(shared), "unique_identifier": shared_identifier, "reason": reason}]
    assert preflight["kept_portfolios"] == kept
    assert [item["uid"] for item in preflight["portfolios"]] == [str(own)]
    assert deleted["kept_portfolios"] == kept
    assert [item["uid"] for item in deleted["deleted_portfolios"]] == [str(own)]
    assert deleted["detail"].endswith("and 1 portfolio. 1 portfolio it used was kept.")
    assert _exists(engine, shared)
    assert _dataset_rows(engine, shared_identifier) == {key: 1 for key in DATASETS}
    assert not _exists(engine, own)
    assert set(_dataset_rows(engine, own_identifier).values()) == {0}


def test_a_portfolio_the_caller_does_not_manage_stays_and_is_reported(sqlite_markets) -> None:
    """ADR 0060, decision 4: through the Markets API a caller deletes only what it manages."""

    from msm.api.managers import Manager, acting_manager_scope

    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, account, portfolio)
    sqlite_markets.requests.clear()

    with acting_manager_scope(lambda: Manager("branch:00000000-0000-4000-8000-00000000000b")):
        deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    (kept,) = deleted["kept_portfolios"]
    assert kept["uid"] == str(portfolio)
    assert "has no manager" in kept["reason"]
    assert deleted["deleted_portfolios"] == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert sqlite_markets.requests == ["read", f"transaction:{ACCOUNT_STATEMENTS}"]


def test_a_key_the_read_cannot_see_keeps_the_portfolio_and_deletes_the_account_alone(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    history = _history(sqlite_markets, account, portfolio)
    _create_provider_tables(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__portfolioeventledgerts__copy VALUES (?, ?)",
            ("2026-11-10 15:30:00.000000", identifier),
        )
    sqlite_markets.requests.clear()

    deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    (kept,) = deleted["kept_portfolios"]
    assert kept["uid"] == str(portfolio)
    assert kept["reason"].startswith("A foreign key refused its delete, so the account was deleted alone:")
    assert deleted["deleted_portfolios"] == []
    assert set(_account_rows(engine, account, history["identifier"]).values()) == {0}
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert _count(engine, "provider_ns__portfolioeventledgerts__copy") == 1
    assert _provider_statements(sqlite_markets) == []
    # The refused transaction deleted nothing; the second deletes the account alone.
    assert sqlite_markets.requests == [
        "read",
        f"transaction:{WITH_PORTFOLIOS}",
        f"transaction:{ACCOUNT_STATEMENTS}",
    ]


# Races -----------------------------------------------------------------------------------


def _between(monkeypatch, change) -> None:
    """Run ``change`` after the read and before the transaction."""

    read = repository.read_account_with_portfolios

    def read_then_change(context, **kwargs):
        result = read(context, **kwargs)
        change()
        return result

    monkeypatch.setattr(repository, "read_account_with_portfolios", read_then_change)


def test_a_portfolio_referenced_in_between_stops_its_guard_and_is_kept(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    history = _history(sqlite_markets, account, portfolio)
    other = _account(engine)
    _between(
        monkeypatch,
        lambda: _insert(
            engine,
            "ms_markets__virtualfund",
            unique_identifier="late-fund",
            account_uid=other.hex,
            target_portfolio_uid=portfolio.hex,
        ),
    )

    deleted = delete_account_with_portfolios(sqlite_markets.context, uid=account)

    assert deleted["kept_portfolios"] == [
        {"uid": str(portfolio), "unique_identifier": identifier, "reason": PORTFOLIO_CHANGED_REASON}
    ]
    assert set(_account_rows(engine, account, history["identifier"]).values()) == {0}
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_an_account_changed_in_between_deletes_nothing(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, account, portfolio)

    def rename() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE ms_markets__account SET unique_identifier = 'renamed' WHERE uid = :uid"),
                {"uid": account.hex},
            )

    _between(monkeypatch, rename)
    sqlite_markets.requests.clear()

    # The account's guard sits in the middle of the list and still stops all of it.
    with pytest.raises(AccountDeleteConflictError, match="changed while it was being deleted"):
        delete_account_with_portfolios(sqlite_markets.context, uid=account)

    # No second transaction: a refused account is not a refused portfolio.
    assert sqlite_markets.requests == ["read", f"transaction:{WITH_PORTFOLIOS}", "read"]
    assert _account_rows(engine, account, "renamed")["accounts"] == 1
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


# Refusals --------------------------------------------------------------------------------


def test_another_accounts_order_blocks_the_delete_before_anything_is_sent(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    history = _history(sqlite_markets, account, portfolio)
    _order(engine, _identifier(engine, other), manager=history["manager"])
    sqlite_markets.requests.clear()

    with pytest.raises(AccountDeleteConflictError, match="orders of other accounts"):
        delete_account_with_portfolios(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read"]
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_a_restrict_key_on_the_account_refuses_everything(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    history = _history(sqlite_markets, account, portfolio)
    _create_provider_tables(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__ordersts__copy VALUES (?, ?)",
            ("2026-01-01 00:00:00", history["order"].hex),
        )
    before = _account_rows(engine, account, history["identifier"])

    with pytest.raises(AccountDeleteConflictError, match="nothing was deleted"):
        delete_account_with_portfolios(sqlite_markets.context, uid=account)

    assert _provider_statements(sqlite_markets) == []
    assert _account_rows(engine, account, history["identifier"]) == before
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


# Bulk ------------------------------------------------------------------------------------


def test_a_portfolio_only_the_selection_uses_goes_with_it_in_one_transaction(
    sqlite_markets, monkeypatch
) -> None:
    """Issue 128: each account is read counting the other selected accounts as deleted
    with it, so a portfolio only they use goes with them, in one transaction, reported
    with the first."""

    impact_calls = _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)
    shared, shared_identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, first, shared)
    _history(sqlite_markets, second, shared)

    preflight = preflight_bulk_delete_accounts_with_portfolios(sqlite_markets.context, uids=[first, second])
    sqlite_markets.requests.clear()
    result = bulk_delete_accounts_with_portfolios(sqlite_markets.context, uids=[first, second])

    assert preflight["allowed"] is True
    first_plan, second_plan = preflight["accounts"]
    assert [item["uid"] for item in first_plan["portfolios"]] == [str(shared)]
    assert second_plan["portfolios"] == [] and second_plan["kept_portfolios"] == []
    assert sum("is deleted with it" in warning for warning in preflight["warnings"]) == 1
    first_result, second_result = result["deleted"]
    assert [item["uid"] for item in first_result["deleted_portfolios"]] == [str(shared)]
    assert second_result["deleted_portfolios"] == [] and second_result["kept_portfolios"] == []
    assert result["detail"] == "Deleted 2 accounts with their history and 1 portfolio."
    assert result["failed"] == []
    assert [request.split(":")[0] for request in sqlite_markets.requests] == [
        "read",
        "read",
        "transaction",
    ]
    assert not _exists(engine, shared)
    assert set(_dataset_rows(engine, shared_identifier).values()) == {0}
    assert impact_calls == ["impact"]  # the preflight's; the bulk delete asks for none


def test_bulk_delete_reports_missing_and_refused_accounts(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    first, blocked, other = _account(engine), _account(engine), _account(engine)
    _history(sqlite_markets, first)
    blocked_history = _history(sqlite_markets, blocked)
    _order(engine, _identifier(engine, other), manager=blocked_history["manager"])
    missing = uuid.uuid4()

    result = bulk_delete_accounts_with_portfolios(sqlite_markets.context, uids=[first, blocked, missing])

    assert [item["uid"] for item in result["deleted"]] == [str(first)]
    assert [item["uid"] for item in result["failed"]] == [str(blocked), str(missing)]
    assert result["detail"] == "Deleted 1 account with its history and 1 portfolio. 2 could not be deleted."


def test_bulk_preflight_lists_what_each_account_takes(sqlite_markets, monkeypatch) -> None:
    impact_calls = _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)
    portfolio, identifier = _portfolio_with_data(engine)
    _history(sqlite_markets, first, portfolio)
    sqlite_markets.requests.clear()

    preflight = preflight_bulk_delete_accounts_with_portfolios(sqlite_markets.context, uids=[first, second])

    assert preflight["allowed"] is True
    assert preflight["detail"] == "2 accounts are ready for deletion with their history and 1 portfolio."
    assert preflight["accounts"][0]["portfolios"] == [
        {"uid": str(portfolio), "unique_identifier": identifier, "row_counts": {key: 1 for key in DATASETS}}
    ]
    assert preflight["accounts"][1]["portfolios"] == []
    assert f"portfolio {identifier!r} is deleted with it" in " ".join(preflight["warnings"])
    assert sqlite_markets.requests == ["read", "read"]  # one read per account
    assert impact_calls == ["impact"]


def test_the_preflight_counts_match_what_the_delete_removes(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _portfolio_with_data(engine)
    _history(sqlite_markets, account, _portfolio_with_data(engine)[0])
    totals_before = {name: _count(engine, name) for name in {*MARKETS_TABLES, *DATASETS.values()}}

    preflight = preflight_account_delete_with_portfolios(sqlite_markets.context, uid=account)
    delete_account_with_portfolios(sqlite_markets.context, uid=account)

    removed = {
        table.key: totals_before[table.model.__table__.name] - _count(engine, table.model.__table__.name)
        for table in ACCOUNT_DELETE_TABLES
        if table.key != "accounts"
    }
    assert removed == preflight["row_counts"]
    (portfolio,) = preflight["portfolios"]
    assert {
        key: totals_before[table_name] - _count(engine, table_name) for key, table_name in DATASETS.items()
    } == portfolio["row_counts"]
