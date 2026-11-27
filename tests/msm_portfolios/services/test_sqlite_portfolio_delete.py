"""The portfolio delete on a SQLite DataSource, end to end (issue 93, ADR 0049).

Each test runs `msm_portfolios.services` on its own copy of a migrated SQLite file,
through MetaTables' own server code for the local runtime, as `test_sqlite_account_delete`
does.
A portfolio is deleted with its rows in its seven datasets in one transaction, or not at
all. Tables of another application are created with `provider_ns__` names after the
execution identity; Markets sends them no statement, never reads, counts or names them,
and lets the database refuse the delete when their `RESTRICT` keys hold rows (ADR 0060).
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa
from metatables import TransferOutcomeUnknown
from sqlalchemy.sql.util import find_tables

from msm.models import PortfolioTable
from msm_portfolios.repositories import portfolio_deletion as repository
from msm_portfolios.repositories.portfolio_deletion import portfolio_delete_statements
from msm_portfolios.services import (
    PortfolioDeleteConflictError,
    bulk_delete_portfolio_records,
    delete_portfolio_record,
    plan_portfolio_deletes,
    preflight_bulk_delete_portfolio_records,
)
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.portfolio_delete import (
    DATASETS,
    _dataset_row,
    _dataset_rows,
    _deletes,
    _exists,
    _identifier,
    _portfolio_with,
    _reads,
    portfolio_markets,
    series_index,
)
from tests.support.unanswered_calls import unanswered_reads, unanswered_transaction
from tests.support.sqlite_markets import (
    WHEN,
    _account,
    _count,
    _insert,
    _portfolio,
    _portfolio_position,
    _target_allocation,
    _write_target,
    table_reads,
)

MARKETS_TABLES = {*DATASETS.values(), "ms_markets__portfolio", "ms_markets__virtualfund", "ms_markets__targetpositionsts"}
PORTFOLIO_TABLE_UID = "0e0e0e0e-0000-4000-8000-000000000001"
PROVIDER_LEDGER_UID = "2c2c2c2c-0000-4000-8000-000000000003"
PROVIDER_VALUES_TABLE = "provider_ns__portfoliosts__copy"
PROVIDER_LEDGER_TABLE = "provider_ns__portfolioeventledgerts__copy"
PROVIDER_TABLES = (
    # Instances copy the contract's RESTRICT key on Portfolio.unique_identifier
    # (`_copy_contract_table`).
    f"CREATE TABLE {PROVIDER_VALUES_TABLE} (time_index DATETIME NOT NULL, "
    "portfolio_identifier VARCHAR(255) NOT NULL REFERENCES ms_markets__portfolio "
    "(unique_identifier) ON DELETE RESTRICT, close FLOAT)",
    f"CREATE TABLE {PROVIDER_LEDGER_TABLE} (time_index DATETIME NOT NULL, "
    "portfolio_identifier VARCHAR(255) NOT NULL REFERENCES ms_markets__portfolio "
    "(unique_identifier) ON DELETE RESTRICT, event_type VARCHAR(64))",
)


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    """The harness, with no MetaTables impact and no delete-after-date call allowed."""

    return portfolio_markets(sqlite_markets, monkeypatch)


# Data ------------------------------------------------------------------------------------


def _virtual_fund(engine, portfolio: uuid.UUID) -> None:
    account = _account(engine)
    _insert(
        engine,
        "ms_markets__virtualfund",
        unique_identifier=f"fund-{uuid.uuid4().hex[:8]}",
        account_uid=account.hex,
        account_target_allocation_uid=_target_allocation(engine, account),
        target_portfolio_uid=portfolio.hex,
    )


def _preflight(markets, portfolio: uuid.UUID) -> dict:
    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[portfolio])
    (item,) = preflight["portfolios"]
    return {**item, "allowed": preflight["allowed"], "all_blockers": preflight["blockers"]}


# Other applications' tables, as MetaTables serves them ----------------------------------


def _create_provider_tables(engine) -> None:
    with engine.begin() as connection:
        for ddl in PROVIDER_TABLES:
            connection.exec_driver_sql(ddl)


def _provider_row(engine, table_name: str, identifier: str) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"INSERT INTO {table_name} (time_index, portfolio_identifier) VALUES (?, ?)",
            ("2026-11-10 15:30:00.000000", identifier),
        )


def _refuse_reading_other_tables(monkeypatch) -> None:
    """Fail the test if Markets reads, counts or describes a table it does not own."""

    from metatables import MetaTable

    def refuse(*_args, **_kwargs):
        raise AssertionError("Markets must not read another application's table (ADR 0060).")

    monkeypatch.setattr(MetaTable, "get_by_uid", classmethod(refuse))
    monkeypatch.setattr(MetaTable, "run_query", refuse)


def _serve_impact(monkeypatch, *sources: dict) -> None:
    """MetaTables' delete impact for the portfolio table: a RESTRICT edge per source node.

    The weights table is always listed too, as MetaTables lists every key into the table.
    """

    root = {
        "id": PORTFOLIO_TABLE_UID,
        "type": "meta_table",
        "uid": PORTFOLIO_TABLE_UID,
        "identifier": "Portfolio",
        "namespaces": ["mainsequence.markets"],
        "physical_schema": "main",
        "physical_table_name": "ms_markets__portfolio",
        "effects": ["delete"],
    }
    weights = {
        "id": "3d3d3d3d-0000-4000-8000-000000000004",
        "type": "meta_table",
        "uid": "3d3d3d3d-0000-4000-8000-000000000004",
        "identifier": "PortfolioWeightsTS",
        "namespaces": ["mainsequence.markets"],
        "physical_schema": "main",
        "physical_table_name": DATASETS["weights"],
    }
    nodes = [root, weights, *sources]
    payload = {
        "root_uid": PORTFOLIO_TABLE_UID,
        "action": "delete_rows",
        "allowed": True,
        "nodes": nodes,
        "edges": [
            {
                "source": node["id"],
                "target": PORTFOLIO_TABLE_UID,
                "kind": "foreign_key",
                "effect": "restrict",
                "name": f"fk_{node.get('physical_table_name', 'hidden')}_portfolio_identifier",
                "on_delete": "restrict",
            }
            for node in nodes[1:]
        ],
        "blockers": [],
    }

    class _Impact:
        def model_dump(self, mode="json"):
            return payload

    class _PortfolioMetaTable:
        uid = PORTFOLIO_TABLE_UID

        def get_impact(self, *, action):
            assert action == "delete_rows"
            return _Impact()

    monkeypatch.setattr(PortfolioTable, "get_meta_table", classmethod(lambda cls: _PortfolioMetaTable()))


def _provider_node(uid: str, identifier: str, name: str) -> dict:
    return {
        "id": uid,
        "type": "meta_table",
        "uid": uid,
        "identifier": identifier,
        "namespaces": ["provider-ns"],
        "physical_schema": "main",
        "physical_table_name": name,
    }


# Statements ------------------------------------------------------------------------------


def test_every_statement_targets_a_portfolio_dataset_or_the_portfolio() -> None:
    statements = portfolio_delete_statements(uid=uuid.uuid4(), unique_identifier="portfolio-1")

    assert [getattr(item, "statement", item).table.name for item in statements] == [
        *DATASETS.values(),
        "ms_markets__portfolio",
    ]
    for item in statements:
        statement = getattr(item, "statement", item)
        assert {table.name for table in find_tables(statement, include_crud=True)} <= MARKETS_TABLES
    assert statements[-1].label == "portfolio" and statements[-1].expect_rows == 1


def test_a_blank_identifier_is_refused() -> None:
    with pytest.raises(ValueError, match="unique_identifier"):
        portfolio_delete_statements(uid=uuid.uuid4(), unique_identifier=" ")


# The delete ------------------------------------------------------------------------------


def test_a_portfolio_with_rows_in_one_dataset_is_deleted_with_them(markets) -> None:
    # Each dataset alone: `test_all_seven_datasets_go_in_one_transaction_with_the_portfolio`
    # deletes rows from all seven, `test_the_preflight_counts_match_what_the_delete_removes`
    # counts them, and `test_bulk_delete_deletes_what_may_go_and_reports_the_rest` keeps
    # another portfolio's rows in each.
    key = "values"
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, key)
    _dataset_row(engine, key, identifier, when=WHEN + dt.timedelta(days=1))
    other, other_identifier = _portfolio_with(engine, key)

    preflight = _preflight(markets, portfolio)
    deleted = delete_portfolio_record(markets.context, uid=portfolio)

    assert preflight["allowed"] is True and preflight["blockers"] == []
    assert preflight["row_counts"] == {name: 2 if name == key else 0 for name in DATASETS}
    assert deleted == {
        "detail": f"Portfolio {identifier!r} deleted with its datasets.",
        "uid": str(portfolio),
        "unique_identifier": identifier,
        "deleted_count": 1,
        "deleted_rows": preflight["row_counts"],
    }
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier)[key] == 1


def test_all_seven_datasets_go_in_one_transaction_with_the_portfolio(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    group = _insert(engine, "ms_markets__portfoliogroup")
    _insert(
        engine,
        "ms_markets__portfoliogroupmembership",
        portfolio_group_uid=group["uid"],
        portfolio_uid=portfolio.hex,
    )
    # Another application's table references portfolios; it holds no rows of this one.
    _create_provider_tables(engine)
    _refuse_reading_other_tables(monkeypatch)
    markets.statements.clear()

    deleted = delete_portfolio_record(markets.context, uid=str(portfolio))

    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert len(_deletes(markets)) == len(DATASETS) + 1
    assert not any("provider_ns__" in sql for sql in markets.statements)
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _count(engine, "ms_markets__portfoliogroupmembership") == 0  # its CASCADE key
    assert _count(engine, "ms_markets__portfoliogroup") == 1


def test_the_read_and_the_transaction_run_under_the_delete_deadline(markets, monkeypatch) -> None:
    # MetaTables' 15 s default covers the whole statement list; a portfolio with long
    # series takes longer to delete (ADR 0049), so both requests carry its 60 s maximum.
    sent: list[tuple[str, int]] = []
    for name in ("execute_markets_operation", "execute_markets_write"):

        def record(operation, *, original=getattr(repository, name), **kwargs):
            sent.append((operation.operation, operation.limits.statement_timeout_ms))
            return original(operation, **kwargs)

        monkeypatch.setattr(repository, name, record)
    portfolio, _identifier = _portfolio_with(markets.engine, *DATASETS)

    delete_portfolio_record(markets.context, uid=portfolio)

    assert sent == [("select", 60_000), ("delete", 60_000)]
    assert not _exists(markets.engine, portfolio)


def test_the_deleted_portfolio_leaves_the_stored_statistics(markets) -> None:
    """MetaTables rebuilds the statistics of each dataset table the statement list
    changes (MetaTables#117), so a portfolio re-created under the deleted one's
    identifier starts from scratch."""

    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _other, other_identifier = _portfolio_with(engine, *DATASETS)
    markets.keep_statistics(*(table.model for table in PORTFOLIO_DATASET_TABLES))
    for table in PORTFOLIO_DATASET_TABLES:
        progress = markets.index_stats[table.table_name]["index_progress"]
        assert {identifier, other_identifier} <= set(progress)

    assert delete_portfolio_record(markets.context, uid=portfolio)["uid"] == str(portfolio)

    for table in PORTFOLIO_DATASET_TABLES:
        progress = markets.index_stats[table.table_name]["index_progress"]
        assert identifier not in progress and other_identifier in progress


def test_a_missing_portfolio_deletes_nothing(markets) -> None:
    missing = uuid.uuid4()

    assert delete_portfolio_record(markets.context, uid=missing) is None
    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[missing])
    assert preflight["allowed"] is False
    assert preflight["blockers"] == [f"Portfolio {missing} was not found."]
    assert _deletes(markets) == []


def test_an_invalid_uid_is_a_value_error(markets) -> None:
    with pytest.raises(ValueError):
        delete_portfolio_record(markets.context, uid="not-a-uid")


# Account history -------------------------------------------------------------------------


def test_a_virtual_fund_blocks_the_delete_and_nothing_is_deleted(markets) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _virtual_fund(engine, portfolio)

    preflight = _preflight(markets, portfolio)
    with pytest.raises(PortfolioDeleteConflictError) as refused:
        delete_portfolio_record(markets.context, uid=portfolio)

    blocker = "1 virtual fund target it (VirtualFundTable.target_portfolio_uid, ON DELETE RESTRICT)."
    assert preflight["allowed"] is False
    assert preflight["blockers"] == [blocker]
    assert preflight["row_counts"] == {key: 1 for key in DATASETS}
    assert blocker in str(refused.value) and "nothing was deleted" in str(refused.value)
    assert "retire the portfolio" in str(refused.value)
    assert _deletes(markets) == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_an_account_target_row_blocks_the_delete_and_nothing_is_deleted(markets) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _write_target(markets, _account(engine), [_portfolio_position(portfolio)])
    markets.statements.clear()

    preflight = _preflight(markets, portfolio)
    with pytest.raises(PortfolioDeleteConflictError, match=r"TargetPositionsStorage\.portfolio_uid"):
        delete_portfolio_record(markets.context, uid=portfolio)

    assert preflight["allowed"] is False
    assert preflight["blockers"] == [
        "1 account target-position row name it (TargetPositionsStorage.portfolio_uid, "
        "ON DELETE RESTRICT)."
    ]
    assert _deletes(markets) == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


# Other applications' tables --------------------------------------------------------------


def test_a_table_metatables_lists_is_never_read_and_the_database_refuses(
    markets, monkeypatch
) -> None:
    """ADR 0060: Markets passes MetaTables' impact through and reads no listed table."""

    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    clean, clean_identifier = _portfolio_with(engine, *DATASETS)
    _create_provider_tables(engine)
    _provider_row(engine, PROVIDER_LEDGER_TABLE, identifier)
    _serve_impact(
        monkeypatch,
        _provider_node(PROVIDER_LEDGER_UID, "PortfolioEventLedgerTS.provider_key", PROVIDER_LEDGER_TABLE),
    )
    _refuse_reading_other_tables(monkeypatch)

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[portfolio, clean])
    with pytest.raises(PortfolioDeleteConflictError, match="FOREIGN KEY constraint failed"):
        delete_portfolio_record(markets.context, uid=portfolio)
    deleted = delete_portfolio_record(markets.context, uid=clean)

    assert preflight["allowed"] is True
    assert preflight["impact"] is not None
    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert not _exists(engine, clean) and set(_dataset_rows(engine, clean_identifier).values()) == {0}
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert _count(engine, PROVIDER_LEDGER_TABLE) == 1
    assert not any("provider_ns__" in sql for sql in markets.statements)


def test_only_the_portfolios_manager_deletes_it(markets) -> None:
    """ADR 0060, decision 4: through the Markets API a caller deletes only what it manages."""

    from msm.api.managers import Manager, acting_manager_scope

    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "UPDATE ms_markets__portfolio SET managed_by = 'branch:00000000-0000-4000-8000-00000000000a'"
        )

    with acting_manager_scope(lambda: Manager("branch:00000000-0000-4000-8000-00000000000b")):
        preflight = _preflight(markets, portfolio)
        with pytest.raises(PermissionError, match="managed by"):
            delete_portfolio_record(markets.context, uid=portfolio)
        bulk = bulk_delete_portfolio_records(markets.context, uids=[portfolio])
    with acting_manager_scope(lambda: Manager("branch:00000000-0000-4000-8000-00000000000a")):
        deleted = delete_portfolio_record(markets.context, uid=portfolio)

    assert preflight["allowed"] is False and "managed by" in preflight["blockers"][0]
    assert bulk["deleted_count"] == 0 and "managed by" in bulk["failed"][0]["detail"]
    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert set(_dataset_rows(engine, identifier).values()) == {0}


def test_a_restrict_key_the_checks_cannot_see_refuses_the_whole_delete(markets) -> None:
    """Issue 93, ADR 0060: the database refuses the portfolio row last; the datasets are kept."""

    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _create_provider_tables(engine)
    _provider_row(engine, PROVIDER_VALUES_TABLE, identifier)

    preflight = _preflight(markets, portfolio)
    with pytest.raises(PortfolioDeleteConflictError, match="nothing was deleted") as refused:
        delete_portfolio_record(markets.context, uid=portfolio)

    # Markets does not look for the key; the transaction meets it.
    assert preflight["allowed"] is True
    assert "FOREIGN KEY constraint failed" in str(refused.value)
    assert len(_deletes(markets)) == len(DATASETS) + 1
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert _count(engine, PROVIDER_VALUES_TABLE) == 1


# Changes between the checks and the delete -----------------------------------------------


def _between(monkeypatch, change) -> None:
    """Run ``change`` right after the delete's first counting read."""

    count = repository.count_portfolio_delete_rows
    calls: list[object] = []

    def counted(context, *, uids):
        result = count(context, uids=uids)
        if not calls:
            change()
        calls.append(uids)
        return result

    monkeypatch.setattr(repository, "count_portfolio_delete_rows", counted)


def test_account_history_written_in_between_stops_the_guard(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _between(monkeypatch, lambda: _virtual_fund(engine, portfolio))

    with pytest.raises(PortfolioDeleteConflictError, match=r"VirtualFundTable\.target_portfolio_uid"):
        delete_portfolio_record(markets.context, uid=portfolio)

    assert len(_deletes(markets)) == len(DATASETS) + 1
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_a_portfolio_deleted_in_between_is_not_found(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio = _portfolio(engine)

    def remove() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.text("DELETE FROM ms_markets__portfolio WHERE uid = :uid"), {"uid": portfolio.hex}
            )

    _between(monkeypatch, remove)

    assert delete_portfolio_record(markets.context, uid=portfolio) is None


def test_a_portfolio_renamed_in_between_is_kept(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio = _portfolio(engine)

    def rename() -> None:
        with engine.begin() as connection:
            connection.execute(
                sa.text("UPDATE ms_markets__portfolio SET unique_identifier = 'renamed' WHERE uid = :uid"),
                {"uid": portfolio.hex},
            )

    _between(monkeypatch, rename)

    with pytest.raises(PortfolioDeleteConflictError, match="changed while it was being deleted"):
        delete_portfolio_record(markets.context, uid=portfolio)
    assert _identifier(engine, portfolio) == "renamed"


# Bulk ------------------------------------------------------------------------------------


def test_bulk_delete_deletes_what_may_go_and_reports_the_rest(markets) -> None:
    """Issue 127: a missing or refused portfolio never stops the others."""

    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, *DATASETS)
    blocked, blocked_identifier = _portfolio_with(engine, *DATASETS)
    _virtual_fund(engine, blocked)
    missing = uuid.uuid4()

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[first, blocked, missing])
    result = bulk_delete_portfolio_records(markets.context, uids=[first, blocked, missing, first])

    assert preflight["allowed"] is True
    assert preflight["detail"] == (
        "1 of the 3 selected portfolios can be deleted with its datasets; the others are kept."
    )
    assert preflight["matched_count"] == 2
    assert [item["uid"] for item in preflight["portfolios"]] == [str(first), str(blocked)]
    assert f"Portfolio {missing} was not found." in preflight["blockers"]
    assert f"Portfolio {blocked_identifier!r}: 1 virtual fund target it" in " ".join(preflight["blockers"])
    assert result["deleted_count"] == 1
    assert result["detail"] == "Deleted 1 portfolio with its datasets. 2 could not be deleted."
    assert [item["uid"] for item in result["deleted"]] == [str(first)]
    assert result["deleted"][0]["deleted_rows"] == {key: 1 for key in DATASETS}
    assert [item["uid"] for item in result["failed"]] == [str(blocked), str(missing)]
    assert "VirtualFundTable.target_portfolio_uid" in result["failed"][0]["detail"]
    assert result["failed"][1]["detail"] == f"Portfolio {missing} was not found."
    assert not _exists(engine, first) and set(_dataset_rows(engine, first_identifier).values()) == {0}
    assert _exists(engine, blocked)
    assert _dataset_rows(engine, blocked_identifier) == {key: 1 for key in DATASETS}


def test_the_preflight_counts_match_what_the_delete_removes(markets) -> None:
    engine = markets.engine
    first, _ = _portfolio_with(engine, *DATASETS)
    second, _ = _portfolio_with(engine, "values", "weights")
    _dataset_row(engine, "values", _identifier(engine, second), when=WHEN + dt.timedelta(days=1))
    totals_before = {key: _count(engine, name) for key, name in DATASETS.items()}

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[first, second])
    markets.statements.clear()
    result = bulk_delete_portfolio_records(markets.context, uids=[first, second])

    # Both portfolios go in one transaction: one statement per dataset, then the rows.
    assert len(_deletes(markets)) == len(DATASETS) + 1
    assert preflight["allowed"] is True
    assert preflight["detail"] == "2 portfolios are ready for deletion with their datasets."
    counts = {item["uid"]: item["row_counts"] for item in preflight["portfolios"]}
    assert counts[str(second)] == {key: {"values": 2, "weights": 1}.get(key, 0) for key in DATASETS}
    assert {item["uid"]: item["deleted_rows"] for item in result["deleted"]} == counts
    removed = {key: totals_before[key] - _count(engine, name) for key, name in DATASETS.items()}
    assert removed == {key: sum(item[key] for item in counts.values()) for key in DATASETS}


# The counting read and the bulk delete (issue 96) ----------------------------------------


def _counted(portfolio: uuid.UUID, identifier: str, **rows: int) -> dict:
    """What `count_portfolio_delete_rows` answers for one portfolio with ``rows`` per key."""

    return {
        "uid": str(portfolio),
        "unique_identifier": identifier,
        "managed_by": None,
        **{key: rows.get(key, 0) for key in (*DATASETS, "virtual_funds", "target_positions")},
    }


def test_one_read_counts_each_selected_portfolio_in_each_dataset(markets) -> None:
    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, "weights", "values")
    second, second_identifier = _portfolio_with(engine, "values", "event_ledger", "cash_flows")
    _dataset_row(engine, "values", second_identifier, when=WHEN + dt.timedelta(days=1))
    _virtual_fund(engine, second)
    empty, empty_identifier = _portfolio_with(engine)
    _portfolio_with(engine, *DATASETS)  # Not selected: none of its rows is counted.
    missing = uuid.uuid4()
    markets.statements.clear()

    counted = repository.count_portfolio_delete_rows(
        markets.context, uids=[first, second, empty, missing]
    )

    assert len(markets.statements) == 1
    assert counted == {
        str(first): _counted(first, first_identifier, weights=1, values=1),
        str(second): _counted(
            second, second_identifier, values=2, event_ledger=1, cash_flows=1, virtual_funds=1
        ),
        str(empty): _counted(empty, empty_identifier),
    }


def test_each_count_reads_the_portfolios_rows_through_the_series_index(markets) -> None:
    portfolios = [_portfolio_with(markets.engine, *DATASETS)[0] for _ in range(3)]

    reads = table_reads(
        markets.engine,
        repository.build_count_portfolio_delete_rows_operation(markets.context, uids=portfolios),
        DATASETS.values(),
    )

    # Each dataset count is one index search on the portfolio, never a scan of the table:
    # its cost follows the portfolio's rows, not the table's (issue 96).
    for table in PORTFOLIO_DATASET_TABLES:
        (step,) = reads[table.table_name]
        assert step.startswith("SEARCH") and series_index(table) in step, step
        assert "(portfolio_identifier=?)" in step, step


def test_deleting_by_an_earlier_plan_still_refuses_a_portfolio_referenced_since(markets) -> None:
    engine = markets.engine
    kept, kept_identifier = _portfolio_with(engine, *DATASETS)
    gone, gone_identifier = _portfolio_with(engine, *DATASETS)
    plan = plan_portfolio_deletes(markets.context, uids=[kept, gone])
    assert plan.preflight()["allowed"] is True
    _virtual_fund(engine, kept)
    markets.statements.clear()

    result = bulk_delete_portfolio_records(markets.context, uids=[kept, gone], plan=plan)

    # The guarded statement stops the selection's transaction, which deletes nothing; each
    # portfolio is then deleted on its own, and only the refused one is read again, to name
    # what refuses it. The selection is not counted again.
    assert [item["uid"] for item in result["failed"]] == [str(kept)]
    assert "VirtualFundTable.target_portfolio_uid" in result["failed"][0]["detail"]
    assert [item["uid"] for item in result["deleted"]] == [str(gone)]
    assert len(_reads(markets)) == 1
    assert _exists(engine, kept) and _dataset_rows(engine, kept_identifier) == {key: 1 for key in DATASETS}
    assert not _exists(engine, gone) and set(_dataset_rows(engine, gone_identifier).values()) == {0}


def test_a_key_the_read_cannot_see_keeps_only_its_portfolio(markets) -> None:
    """Issue 127, ADR 0060: the database refuses the selection's transaction, which deletes
    nothing; the portfolios are then deleted one by one, and only the refused one stays."""

    engine = markets.engine
    blocked, blocked_identifier = _portfolio_with(engine, *DATASETS)
    clean, clean_identifier = _portfolio_with(engine, *DATASETS)
    _create_provider_tables(engine)
    _provider_row(engine, PROVIDER_VALUES_TABLE, blocked_identifier)

    result = bulk_delete_portfolio_records(markets.context, uids=[blocked, clean])

    assert [item["uid"] for item in result["deleted"]] == [str(clean)]
    assert [item["uid"] for item in result["failed"]] == [str(blocked)]
    assert "FOREIGN KEY constraint failed" in result["failed"][0]["detail"]
    assert result["detail"] == "Deleted 1 portfolio with its datasets. 1 could not be deleted."
    assert not _exists(engine, clean) and set(_dataset_rows(engine, clean_identifier).values()) == {0}
    assert _exists(engine, blocked)
    assert _dataset_rows(engine, blocked_identifier) == {key: 1 for key in DATASETS}
    assert _count(engine, PROVIDER_VALUES_TABLE) == 1


def test_a_blocker_on_the_whole_table_keeps_every_portfolio(markets, monkeypatch) -> None:
    """MetaTables' impact blockers refuse the delete itself, so every portfolio is kept."""

    from msm_portfolios.services import portfolio_deletion as service

    blocker = "ms_markets__portfolio: the caller cannot write this table."
    monkeypatch.setattr(
        service,
        "portfolio_delete_impact",
        lambda **_kwargs: service.PortfolioDeleteImpact(impact=None, blockers=[blocker]),
    )
    first, _ = _portfolio_with(markets.engine, *DATASETS)
    second, _ = _portfolio_with(markets.engine, *DATASETS)

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[first, second])
    result = bulk_delete_portfolio_records(markets.context, uids=[first, second])

    assert preflight["allowed"] is False
    assert preflight["detail"] == "None of the selected portfolios can be deleted."
    assert result["deleted_count"] == 0
    assert [item["uid"] for item in result["failed"]] == [str(first), str(second)]
    assert all(blocker in item["detail"] for item in result["failed"])
    assert _deletes(markets) == []
    assert _exists(markets.engine, first) and _exists(markets.engine, second)


def test_a_plan_for_another_selection_is_refused(markets) -> None:
    first, _ = _portfolio_with(markets.engine)
    second, _ = _portfolio_with(markets.engine)
    plan = plan_portfolio_deletes(markets.context, uids=[first])

    with pytest.raises(ValueError, match="another portfolio selection"):
        bulk_delete_portfolio_records(markets.context, uids=[first, second], plan=plan)

    assert _deletes(markets) == []
    assert _exists(markets.engine, first) and _exists(markets.engine, second)


# A delete MetaTables does not answer (issue 151) ------------------------------------------


def _remove(engine, portfolio: uuid.UUID) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text("DELETE FROM ms_markets__portfolio WHERE uid = :uid"), {"uid": portfolio.hex}
        )


def test_a_bulk_delete_that_committed_without_an_answer_is_deleted(markets, monkeypatch) -> None:
    """The transaction is all or nothing: with every portfolio gone, it committed."""

    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, *DATASETS)
    second, second_identifier = _portfolio_with(engine, *DATASETS)
    plan = plan_portfolio_deletes(markets.context, uids=[first, second])
    unanswered_transaction(monkeypatch, committed=True)
    markets.statements.clear()

    result = bulk_delete_portfolio_records(markets.context, uids=[first, second], plan=plan)

    assert result["detail"] == "Deleted 2 portfolios with their datasets."
    assert [item["uid"] for item in result["deleted"]] == [str(first), str(second)]
    assert result["deleted"][0]["deleted_rows"] == {key: 1 for key in DATASETS}
    assert result["failed"] == []
    # The transaction, then one read of the portfolio rows to confirm it.
    assert len(_deletes(markets)) == len(DATASETS) + 1
    (confirm,) = _reads(markets)
    assert "ms_markets__portfolio" in confirm
    assert not _exists(engine, first) and set(_dataset_rows(engine, first_identifier).values()) == {0}
    assert not _exists(engine, second) and set(_dataset_rows(engine, second_identifier).values()) == {0}


def test_a_bulk_delete_without_an_answer_that_did_not_commit_may_be_retried(
    markets, monkeypatch
) -> None:
    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, *DATASETS)
    second, second_identifier = _portfolio_with(engine, *DATASETS)
    unanswered_transaction(monkeypatch, committed=False)

    result = bulk_delete_portfolio_records(markets.context, uids=[first, second])

    assert result["detail"] == "No portfolios were deleted. 2 could not be deleted."
    assert result["deleted"] == []
    assert result["failed"] == [
        {
            "uid": str(uid),
            "detail": (
                f"Portfolio {identifier!r}: the outcome of its delete is unknown. MetaTables "
                "did not answer it, and the portfolio still existed when read again; the "
                "delete may still finish. The call may be retried."
            ),
        }
        for uid, identifier in ((first, first_identifier), (second, second_identifier))
    ]
    assert _exists(engine, first) and _exists(engine, second)
    assert _dataset_rows(engine, first_identifier) == {key: 1 for key in DATASETS}

    retried = bulk_delete_portfolio_records(markets.context, uids=[first, second])

    assert [item["uid"] for item in retried["deleted"]] == [str(first), str(second)]
    assert not _exists(engine, first) and not _exists(engine, second)


def test_a_portfolio_another_call_deleted_meanwhile_is_not_found(markets, monkeypatch) -> None:
    """One portfolio left means the transaction did not commit; the gone one is not found."""

    engine = markets.engine
    kept, kept_identifier = _portfolio_with(engine, *DATASETS)
    gone, _ = _portfolio_with(engine)
    unanswered_transaction(monkeypatch, committed=False, before_raising=lambda: _remove(engine, gone))

    result = bulk_delete_portfolio_records(markets.context, uids=[kept, gone])

    assert result["deleted"] == []
    assert [item["uid"] for item in result["failed"]] == [str(kept), str(gone)]
    assert result["failed"][0]["detail"].startswith(
        f"Portfolio {kept_identifier!r}: the outcome of its delete is unknown."
    )
    assert result["failed"][1]["detail"] == f"Portfolio {gone} was not found."
    assert _exists(engine, kept)


def test_a_delete_whose_confirming_read_fails_too_may_be_retried(markets, monkeypatch) -> None:
    engine = markets.engine
    first, first_identifier = _portfolio_with(engine)
    second, _ = _portfolio_with(engine)
    unanswered_transaction(
        monkeypatch, committed=False, before_raising=lambda: unanswered_reads(monkeypatch)
    )

    result = bulk_delete_portfolio_records(markets.context, uids=[first, second])

    assert result["deleted"] == []
    assert [item["uid"] for item in result["failed"]] == [str(first), str(second)]
    assert result["failed"][0]["detail"] == (
        f"Portfolio {first_identifier!r}: the outcome of its delete is unknown. MetaTables "
        "did not answer it, and reading the portfolio again failed too (UnansweredReadError). "
        "The call may be retried."
    )
    assert _exists(engine, first) and _exists(engine, second)


@pytest.mark.parametrize("committed", [True, False])
def test_one_portfolio_deleted_without_an_answer(markets, monkeypatch, committed) -> None:
    """The single delete, and a bulk delete of one portfolio, confirm it the same way."""

    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    other, _ = _portfolio_with(engine, *DATASETS)
    unanswered_transaction(monkeypatch, committed=committed)

    if committed:
        deleted = delete_portfolio_record(markets.context, uid=portfolio)
        assert deleted["detail"] == f"Portfolio {identifier!r} deleted with its datasets."
        assert not _exists(engine, portfolio)
    else:
        with pytest.raises(TransferOutcomeUnknown, match="outcome of its delete is unknown") as raised:
            delete_portfolio_record(markets.context, uid=portfolio)
        assert isinstance(raised.value.__cause__, TransferOutcomeUnknown)
        assert _exists(engine, portfolio)

    unanswered_transaction(monkeypatch, committed=committed)
    result = bulk_delete_portfolio_records(markets.context, uids=[other])

    assert [item["uid"] for item in result["deleted"]] == ([str(other)] if committed else [])
    assert [item["uid"] for item in result["failed"]] == ([] if committed else [str(other)])
    assert _exists(engine, other) is not committed
