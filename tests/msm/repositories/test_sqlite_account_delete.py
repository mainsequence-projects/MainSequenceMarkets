"""The account delete on a SQLite DataSource, end to end (ADR 0050, issue 91).

Each test runs `msm.services` on its own copy of a migrated SQLite file, through
MetaTables' own server code for the local runtime (the `sqlite_markets` fixture). Tables
of another application are created with `provider_ns__` names; the tests check that no
statement Markets sends names them, so they change only through their own keys.

The delete that also takes the account's portfolios belongs to `msm_portfolios`; its
tests are in `tests/msm_portfolios/services/test_sqlite_account_portfolio_delete.py`
and share this module's harness and data, in `tests/support/account_delete.py`.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from metatables import TransferOutcomeUnknown
from sqlalchemy.sql.util import find_tables

from msm.models import AccountTable
from msm.repositories.account_deletion import (
    ACCOUNT_DELETE_TABLES,
    account_delete_statements,
    read_account_delete,
)
from msm.services import (
    AccountDeleteConflictError,
    bulk_delete_accounts,
    delete_account,
    preflight_account_delete,
    preflight_bulk_delete_accounts,
)
from msm.services.accounts import deletion
from msm.time_index.execution.storage import OrderEventsStorage, OrdersStorage, TradesStorage
from tests.support.account_delete import (
    EVERY_TABLE_COUNTS,
    MARKETS_TABLES,
    _account_rows,
    _create_provider_tables,
    _history,
    _identifier,
    _impact_unavailable,
    _order,
    _order_event,
    _progress,
    _provider_statements,
    account_markets,
)
from tests.support.sqlite_markets import (
    WHEN,
    _account,
    _count,
    _rows,
    _write_holdings,
)
from tests.support.unanswered_calls import unanswered_transaction

ACCOUNT_TABLE_UID = "5a5a5a5a-0000-4000-8000-000000000005"
ACCOUNT_DELETE_IMPACT = deletion.account_delete_impact


@pytest.fixture
def sqlite_markets(sqlite_markets, monkeypatch):
    return account_markets(sqlite_markets, monkeypatch)


# Statements ------------------------------------------------------------------------------


def test_every_statement_targets_a_markets_table() -> None:
    statements = account_delete_statements(
        uid=uuid.uuid4(), unique_identifier="account-1", row_counts=EVERY_TABLE_COUNTS
    )

    assert len(statements) == len(ACCOUNT_DELETE_TABLES)
    for item in statements:
        statement = getattr(item, "statement", item)
        assert statement.table.name in MARKETS_TABLES
        assert {table.name for table in find_tables(statement, include_crud=True)} <= MARKETS_TABLES
    assert [getattr(item, "statement", item).table.name for item in statements] == [
        table.model.__table__.name for table in ACCOUNT_DELETE_TABLES
    ]
    assert statements[-1].label == "account" and statements[-1].expect_rows == 1


def test_a_table_the_read_found_empty_gets_no_statement() -> None:
    counts = {**dict.fromkeys(EVERY_TABLE_COUNTS, 0), "holdings": 2, "holdings_sets": 1}

    statements = account_delete_statements(
        uid=uuid.uuid4(), unique_identifier="account-1", row_counts=counts
    )

    assert [getattr(item, "statement", item).table.name for item in statements] == [
        "ms_markets__accountholdingsts",
        "ms_markets__accountholdingsset",
        "ms_markets__account",
    ]


def test_order_events_get_a_statement_only_when_the_read_counted_them() -> None:
    # Order events have a key into their order (ADR 0064): one written after the read
    # refuses the transaction, as every other RESTRICT key does.
    counts = {**dict.fromkeys(EVERY_TABLE_COUNTS, 0), "orders": 1}

    statements = account_delete_statements(
        uid=uuid.uuid4(), unique_identifier="account-1", row_counts=counts
    )

    assert [getattr(item, "statement", item).table.name for item in statements] == [
        "ms_markets__order",
        "ms_markets__account",
    ]


def test_a_blank_identifier_is_refused() -> None:
    with pytest.raises(ValueError, match="unique_identifier"):
        account_delete_statements(
            uid=uuid.uuid4(), unique_identifier=" ", row_counts=EVERY_TABLE_COUNTS
        )


# The delete ------------------------------------------------------------------------------


def test_the_account_is_deleted_with_its_whole_history(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    other_history = _history(sqlite_markets, other)
    assets, portfolios = _count(engine, "ms_markets__asset"), _count(engine, "ms_markets__portfolio")

    before = read_account_delete(sqlite_markets.context, uid=account)["counts"]
    deleted = delete_account(sqlite_markets.context, uid=str(account))

    assert deleted == {
        "detail": f"Account {history['identifier']!r} deleted with its history.",
        "uid": str(account),
        "unique_identifier": history["identifier"],
        "deleted_count": 1,
        "deleted_rows": {key: before[key] for key in deleted["deleted_rows"]},
    }
    assert all(deleted["deleted_rows"][key] >= 1 for key in deleted["deleted_rows"])
    assert set(_account_rows(engine, account, history["identifier"]).values()) == {0}
    assert _count(engine, "ms_markets__positionset") == 1
    assert _count(engine, "ms_markets__targetpositionsts") == 1
    assert _count(engine, "ms_markets__virtualfundholdingsset") == 1
    assert _count(engine, "ms_markets__virtualfundholdingsts") == 1
    assert _count(engine, "ms_markets__ordereventsts") == 1
    other_rows = _account_rows(engine, other, other_history["identifier"])
    assert other_rows["orders"] == 1 and 0 not in other_rows.values()
    assert _count(engine, "ms_markets__asset") == assets
    assert _count(engine, "ms_markets__portfolio") == portfolios


def test_the_events_of_the_accounts_own_orders_are_deleted(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    history = _history(sqlite_markets, account)
    _order_event(engine, history["order"], event_time=WHEN + dt.timedelta(minutes=1))

    deleted = delete_account(sqlite_markets.context, uid=account)

    assert deleted["deleted_rows"]["order_events"] == 2
    assert _count(engine, "ms_markets__ordereventsts") == 0


def test_a_missing_account_deletes_nothing(sqlite_markets) -> None:
    missing = uuid.uuid4()

    assert delete_account(sqlite_markets.context, uid=missing) is None
    assert preflight_account_delete(sqlite_markets.context, uid=missing) is None
    assert sqlite_markets.requests == ["read", "read"]


def test_an_invalid_uid_is_a_value_error(sqlite_markets) -> None:
    with pytest.raises(ValueError):
        delete_account(sqlite_markets.context, uid="not-a-uid")


def test_one_delete_sends_one_read_and_one_transaction(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _history(sqlite_markets, account)
    sqlite_markets.requests.clear()

    delete_account(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read", f"transaction:{len(ACCOUNT_DELETE_TABLES)}"]


def test_an_account_with_holdings_only_sends_three_statements(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])
    sqlite_markets.requests.clear()

    deleted = delete_account(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read", "transaction:3"]
    assert {key: count for key, count in deleted["deleted_rows"].items() if count} == {
        "holdings": 1,
        "holdings_sets": 1,
    }
    assert _count(engine, "ms_markets__account") == 0
    assert _count(engine, "ms_markets__accountholdingsts") == 0


def test_holdings_written_after_the_read_refuse_the_delete(sqlite_markets, monkeypatch) -> None:
    # The read found no holdings, so the transaction has no holdings statement; the
    # holdings key refuses the account's delete and the transaction deletes nothing.
    engine = sqlite_markets.engine
    account = _account(engine)
    read = deletion.account_deletion_repository.read_account_delete

    def read_then_sync(context, **kwargs):
        result = read(context, **kwargs)
        _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])
        return result

    monkeypatch.setattr(deletion.account_deletion_repository, "read_account_delete", read_then_sync)

    with pytest.raises(AccountDeleteConflictError, match="nothing was deleted"):
        delete_account(sqlite_markets.context, uid=account)

    assert _count(engine, "ms_markets__account") == 1
    assert _count(engine, "ms_markets__accountholdingsts") == 1


def test_an_account_changed_in_between_deletes_nothing(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _history(sqlite_markets, account)
    read = deletion.account_deletion_repository.read_account_delete

    def read_then_rename(context, **kwargs):
        result = read(context, **kwargs)
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE ms_markets__account SET unique_identifier = 'renamed' WHERE uid = :uid"),
                {"uid": account.hex},
            )
        return result

    monkeypatch.setattr(deletion.account_deletion_repository, "read_account_delete", read_then_rename)
    sqlite_markets.requests.clear()

    with pytest.raises(AccountDeleteConflictError, match="changed while it was being deleted"):
        delete_account(sqlite_markets.context, uid=account)

    assert sqlite_markets.requests == ["read", f"transaction:{len(ACCOUNT_DELETE_TABLES)}", "read"]

    assert _account_rows(engine, account, "renamed")["accounts"] == 1
    assert _count(engine, "ms_markets__ordersts") == 1  # the history under the old identifier


def test_the_deleted_accounts_orders_trades_and_events_leave_the_stored_statistics(sqlite_markets) -> None:
    """MetaTables rebuilds the statistics of each time-index table a statement list
    changes (MetaTables#117), so an account re-created under the same identifier, whose
    connector publishes its orders again, does not resume from the deleted ones."""

    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    other_history = _history(sqlite_markets, other)
    sqlite_markets.keep_statistics(OrdersStorage, TradesStorage, OrderEventsStorage)
    orders = history["order"], other_history["order"]
    for model in (OrdersStorage, OrderEventsStorage):
        assert set(orders) <= {uuid.UUID(key) for key in _progress(sqlite_markets, model)}
    trades_before = set(_progress(sqlite_markets, TradesStorage))

    delete_account(sqlite_markets.context, uid=account)

    for model in (OrdersStorage, OrderEventsStorage):
        progress = {uuid.UUID(key) for key in _progress(sqlite_markets, model)}
        assert orders[0] not in progress and orders[1] in progress
    remaining = {row["trade_identifier"] for row in _rows(engine, "SELECT trade_identifier FROM ms_markets__tradests")}
    assert set(_progress(sqlite_markets, TradesStorage)) == remaining < trades_before


# Other accounts' Markets rows ------------------------------------------------------------


def test_another_accounts_order_on_its_order_manager_blocks_the_delete(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account, other = _account(engine), _account(engine)
    history = _history(sqlite_markets, account)
    _order(engine, _identifier(engine, other), manager=history["manager"])
    sqlite_markets.requests.clear()

    preflight = preflight_account_delete(sqlite_markets.context, uid=account)
    assert preflight["blockers"] == [
        "1 orders of other accounts name its order managers (ON DELETE RESTRICT)."
    ]
    with pytest.raises(AccountDeleteConflictError, match="orders of other accounts"):
        delete_account(sqlite_markets.context, uid=account)
    assert _account_rows(engine, account, history["identifier"])["accounts"] == 1
    assert sqlite_markets.requests == ["read", "read"]


# Other applications' tables --------------------------------------------------------------


# The provider tables are created after the execution identity, so they lie outside
# it, as another application's tables do. SQLite still reads them to enforce their
# keys (mainsequence-projects/MetaTables#105).


def test_other_namespace_tables_change_only_through_their_own_keys(sqlite_markets) -> None:
    markets = sqlite_markets
    engine = markets.engine
    account = _account(engine)
    _history(markets, account)
    _create_provider_tables(engine)
    (holdings_set,) = _rows(
        engine,
        "SELECT uid FROM ms_markets__accountholdingsset WHERE account_uid = :uid LIMIT 1",
        uid=account.hex,
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__account_sidecar VALUES (?, 'secret')", (account.hex,)
        )
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__accountholdingsts__copy VALUES (?, 2.0)", (holdings_set["uid"],)
        )

    deleted = delete_account(markets.context, uid=account)

    assert deleted is not None
    assert _provider_statements(markets) == []
    assert _count(engine, "provider_ns__account_sidecar") == 0  # its own CASCADE key
    assert _count(engine, "provider_ns__accountholdingsts__copy") == 0  # its own CASCADE key


def test_a_restrict_key_in_another_namespace_refuses_the_whole_delete(sqlite_markets) -> None:
    markets = sqlite_markets
    engine = markets.engine
    account = _account(engine)
    history = _history(markets, account)
    _create_provider_tables(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO provider_ns__ordersts__copy VALUES (?, ?)",
            ("2026-01-01 00:00:00", history["order"].hex),
        )
    before = _account_rows(engine, account, history["identifier"])

    with pytest.raises(AccountDeleteConflictError, match="nothing was deleted"):
        delete_account(markets.context, uid=account)

    assert _provider_statements(markets) == []
    assert _account_rows(engine, account, history["identifier"]) == before
    assert _count(engine, "ms_markets__ordereventsts") == 1
    assert _count(engine, "provider_ns__ordersts__copy") == 1


# Bulk ------------------------------------------------------------------------------------


def test_bulk_delete_deletes_each_account_and_reports_the_rest(sqlite_markets, monkeypatch) -> None:
    impact_calls = _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, blocked, other = _account(engine), _account(engine), _account(engine)
    _history(sqlite_markets, first)
    blocked_history = _history(sqlite_markets, blocked)
    _order(engine, _identifier(engine, other), manager=blocked_history["manager"])
    missing = uuid.uuid4()

    preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, blocked, missing])
    # Issue 128: a blocked or missing account keeps itself, never the selection.
    assert preflight["allowed"] is True
    assert preflight["detail"] == (
        "1 of the 3 selected accounts can be deleted with its history; the others are kept."
    )
    assert preflight["matched_count"] == 2
    assert [item["uid"] for item in preflight["accounts"]] == [str(first), str(blocked)]
    assert preflight["blockers"][1] == f"Account {missing} was not found."

    result = bulk_delete_accounts(sqlite_markets.context, uids=[first, blocked, missing, first])

    assert result["deleted_count"] == 1
    assert [item["uid"] for item in result["deleted"]] == [str(first)]
    assert [item["uid"] for item in result["failed"]] == [str(blocked), str(missing)]
    assert _count(engine, "ms_markets__account") == 2
    assert impact_calls == ["impact"]  # the preflight's; the bulk delete asks for none


def test_bulk_delete_deletes_the_selection_in_one_transaction(sqlite_markets, monkeypatch) -> None:
    """Issue 128: the accounts that may go are deleted together, and rows one selected
    account holds of another block neither."""

    _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)
    first_history = _history(sqlite_markets, first)
    _history(sqlite_markets, second)
    # The second account's order uses the first account's order manager: alone, the first
    # account could not be deleted.
    _order(engine, _identifier(engine, second), manager=first_history["manager"])
    alone = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first])
    sqlite_markets.requests.clear()

    result = bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    assert alone["allowed"] is False
    assert [item["uid"] for item in result["deleted"]] == [str(first), str(second)]
    assert result["failed"] == []
    assert sqlite_markets.requests == ["read", "read", f"transaction:{len(ACCOUNT_DELETE_TABLES)}"]
    assert _count(engine, "ms_markets__account") == 0


def test_bulk_preflight_allows_a_clean_selection(sqlite_markets, monkeypatch) -> None:
    impact_calls = _impact_unavailable(monkeypatch)
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)
    _history(sqlite_markets, first)
    sqlite_markets.requests.clear()

    preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    assert preflight["allowed"] is True
    assert preflight["blockers"] == []
    assert preflight["detail"] == "2 accounts are ready for deletion with their history."
    counts = {item["uid"]: item["row_counts"] for item in preflight["accounts"]}
    assert counts[str(first)]["holdings"] >= 1
    assert set(counts[str(second)].values()) == {0}
    assert _count(engine, "ms_markets__account") == 2
    assert sqlite_markets.requests == ["read", "read"]  # one read per account
    assert impact_calls == ["impact"]


def test_the_preflight_counts_match_what_the_delete_removes(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _history(sqlite_markets, account)
    totals_before = {name: _count(engine, name) for name in MARKETS_TABLES}

    counts = preflight_account_delete(sqlite_markets.context, uid=account)["row_counts"]
    delete_account(sqlite_markets.context, uid=account)

    removed = {
        table.key: totals_before[table.model.__table__.name] - _count(engine, table.model.__table__.name)
        for table in ACCOUNT_DELETE_TABLES
        if table.key != "accounts"
    }
    assert removed == counts


# MetaTables' impact ----------------------------------------------------------------------


def test_the_impact_is_asked_once_per_table_and_reused(sqlite_markets, monkeypatch) -> None:
    monkeypatch.setattr(deletion, "account_delete_impact", ACCOUNT_DELETE_IMPACT)
    calls: list[str] = []
    payload = {
        "root_uid": ACCOUNT_TABLE_UID,
        "action": "delete_rows",
        "allowed": True,
        "nodes": [
            {
                "id": ACCOUNT_TABLE_UID,
                "type": "meta_table",
                "uid": ACCOUNT_TABLE_UID,
                "identifier": "Account",
                "namespaces": ["mainsequence.markets"],
                "physical_schema": "main",
                "physical_table_name": "ms_markets__account",
                "effects": ["delete"],
            }
        ],
        "edges": [],
        "blockers": [],
    }

    class _Impact:
        def model_dump(self, mode="json"):
            return payload

    class _AccountMetaTable:
        uid = ACCOUNT_TABLE_UID

        def get_impact(self, *, action):
            calls.append(action)
            return _Impact()

    monkeypatch.setattr(AccountTable, "get_meta_table", classmethod(lambda cls: _AccountMetaTable()))
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)

    for _ in range(3):
        preflight = preflight_bulk_delete_accounts(sqlite_markets.context, uids=[first, second])
        assert preflight["impact"].root_uid == ACCOUNT_TABLE_UID
    bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    assert calls == ["delete_rows"]
    assert _count(engine, "ms_markets__account") == 0


# A delete MetaTables does not answer (issue 151) ------------------------------------------


def _unconfirmed(identifier: str) -> str:
    return (
        f"Account {identifier!r}: the outcome of its delete is unknown. MetaTables did not "
        "answer it, and the account still existed when read again; the delete may still "
        "finish. The call may be retried."
    )


@pytest.mark.parametrize("committed", [True, False])
def test_a_delete_without_an_answer_is_confirmed_by_one_read(
    sqlite_markets, monkeypatch, committed
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    history = _history(sqlite_markets, account)
    unanswered_transaction(monkeypatch, committed=committed)
    sqlite_markets.requests.clear()

    if committed:
        deleted = delete_account(sqlite_markets.context, uid=account)
        assert deleted["detail"] == f"Account {history['identifier']!r} deleted with its history."
        assert set(_account_rows(engine, account, history["identifier"]).values()) == {0}
    else:
        with pytest.raises(TransferOutcomeUnknown) as raised:
            delete_account(sqlite_markets.context, uid=account)
        assert str(raised.value) == _unconfirmed(history["identifier"])
        assert 0 not in _account_rows(engine, account, history["identifier"]).values()
    # The plan's read, the transaction, and one read of the account row.
    assert sqlite_markets.requests.count("read") == 2
    assert sqlite_markets.requests[-1] == "read"


@pytest.mark.parametrize("committed", [True, False])
def test_a_bulk_delete_without_an_answer_reports_what_it_could_not_confirm(
    sqlite_markets, monkeypatch, committed
) -> None:
    engine = sqlite_markets.engine
    first, second = _account(engine), _account(engine)
    identifiers = [_history(sqlite_markets, uid)["identifier"] for uid in (first, second)]
    unanswered_transaction(monkeypatch, committed=committed)

    result = bulk_delete_accounts(sqlite_markets.context, uids=[first, second])

    if committed:
        assert [item["uid"] for item in result["deleted"]] == [str(first), str(second)]
        assert result["failed"] == []
        assert _count(engine, "ms_markets__account") == 0
    else:
        assert result["detail"] == "No accounts were deleted. 2 could not be deleted."
        assert result["deleted"] == []
        assert result["failed"] == [
            {"uid": str(uid), "detail": _unconfirmed(identifier)}
            for uid, identifier in zip((first, second), identifiers)
        ]
        assert _count(engine, "ms_markets__account") == 2
