"""The portfolio delete on a SQLite DataSource, end to end (issue 93, ADR 0049).

Each test migrates a fresh SQLite file and runs `msm_portfolios.services` through
MetaTables' own server code for the local runtime, as `test_sqlite_account_delete` does.
A portfolio is deleted with its rows in its seven datasets in one transaction, or not at
all. Tables of another application are created with `provider_ns__` names after the
execution identity; no statement Markets sends names them. MetaTables' impact, table
reads and read-only queries are served from the same file where a test needs them.

Each dataset storage is bound to a table whose `delete_after_date` runs the local
backend's own tail delete and keeps the statistics it rebuilds, as MetaTables'
delete-after-date route stores them in `index_stats`.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.sql.util import find_tables

from msm.models import PortfolioTable
from msm_portfolios.repositories import portfolio_deletion as repository
from msm_portfolios.repositories.portfolio_deletion import portfolio_delete_statements
from msm_portfolios.services import (
    PortfolioDeleteConflictError,
    bulk_delete_portfolio_records,
    delete_portfolio_record,
    preflight_bulk_delete_portfolio_records,
)
from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.msm.repositories.test_sqlite_snapshot_writes import (
    WHEN,
    _account,
    _asset,
    _count,
    _insert,
    _portfolio,
    _portfolio_position,
    _rows,
    _write_target,
    make_sqlite_markets,
)

DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}
MARKETS_TABLES = {*DATASETS.values(), "ms_markets__portfolio", "ms_markets__virtualfund", "ms_markets__targetpositionsts"}
PORTFOLIO_TABLE_UID = "0e0e0e0e-0000-4000-8000-000000000001"
PROVIDER_VALUES_UID = "1b1b1b1b-0000-4000-8000-000000000002"
PROVIDER_LEDGER_UID = "2c2c2c2c-0000-4000-8000-000000000003"
PROVIDER_SIDECAR_UID = "4e4e4e4e-0000-4000-8000-000000000005"
PROVIDER_SIDECAR_TABLE = "provider_ns__portfolio_sidecar"
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


class _DatasetTable:
    """A dataset storage's TimeIndexMetaTable, served by MetaTables' local SQLite backend.

    ``delete_after_date`` runs the backend's own tail delete, which rebuilds the
    table's statistics from its rows, and keeps them, as the route stores them in
    ``index_stats``. Each call is recorded as (dataset, identifiers, rows deleted).
    """

    def __init__(self, markets, table) -> None:
        self.markets, self.table = markets, table
        self.uid = f"core-{table.key}"

    def delete_after_date(self, after_date, *, dimension_filters, timeout=None):
        if self.table.key in self.markets.failing:
            raise TimeoutError("The rebuild exceeded MetaTables' 45 s statement timeout.")
        model = self.table.model
        snapshot = self.markets.backend.tables.delete_tail(
            physical_schema=None,
            physical_table_name=model.__table__.name,
            time_index_name=model.__time_index_name__,
            identity_dimensions=tuple(model.__index_names__[1:]),
            after_date=after_date,
            dimension_filters=dimension_filters,
            index_coordinates=None,
            dimension_range_map=None,
        )
        self.markets.index_stats[self.table.key] = snapshot.multi_index_stats or {}
        self.markets.refreshes.append(
            (self.table.key, list(dimension_filters["portfolio_identifier"]), snapshot.deleted_count)
        )
        return {"deleted_count": snapshot.deleted_count, "table_empty": snapshot.table_empty}


@pytest.fixture
def markets(tmp_path, monkeypatch):
    """The harness, with no MetaTables impact and every dataset storage bound."""

    monkeypatch.setattr(PortfolioTable, "get_meta_table", classmethod(lambda cls: None))
    markets = make_sqlite_markets(tmp_path, monkeypatch)
    markets.refreshes, markets.index_stats, markets.failing, markets.tables = [], {}, set(), {}
    for table in PORTFOLIO_DATASET_TABLES:
        bound = markets.tables[table.key] = _DatasetTable(markets, table)
        monkeypatch.setattr(
            table.model, "get_time_index_meta_table", classmethod(lambda cls, bound=bound: bound)
        )
    _asset(markets.engine, "AAA")
    return markets


def _progress(markets, key: str) -> dict:
    """The progress MetaTables stores for one dataset, rebuilt from its rows now."""

    markets.tables[key].delete_after_date(
        "9999-12-31T00:00:00+00:00", dimension_filters={"portfolio_identifier": ["-"]}
    )
    markets.refreshes.pop()
    return markets.index_stats[key].get("index_progress", {})


# Data ------------------------------------------------------------------------------------


def _identifier(engine, portfolio: uuid.UUID) -> str:
    (row,) = _rows(
        engine,
        "SELECT unique_identifier FROM ms_markets__portfolio WHERE uid = :uid",
        uid=portfolio.hex,
    )
    return row["unique_identifier"]


def _dataset_row(engine, key: str, identifier: str, *, when: dt.datetime = WHEN) -> None:
    table_name = DATASETS[key]
    assets = {
        foreign_key["constrained_columns"][0]: "AAA"
        for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
        if foreign_key["referred_table"] == "ms_markets__asset"
    }
    _insert(engine, table_name, time_index=when, portfolio_identifier=identifier, **assets)


def _portfolio_with(engine, *keys: str) -> tuple[uuid.UUID, str]:
    portfolio = _portfolio(engine)
    identifier = _identifier(engine, portfolio)
    for key in keys:
        _dataset_row(engine, key, identifier)
    return portfolio, identifier


def _dataset_rows(engine, identifier: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            key: connection.execute(
                sa.text(f"SELECT count(*) FROM {table_name} WHERE portfolio_identifier = :identifier"),
                {"identifier": identifier},
            ).scalar_one()
            for key, table_name in DATASETS.items()
        }


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(
        _rows(engine, "SELECT uid FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio.hex)
    )


def _virtual_fund(engine, portfolio: uuid.UUID) -> None:
    _insert(
        engine,
        "ms_markets__virtualfund",
        unique_identifier=f"fund-{uuid.uuid4().hex[:8]}",
        account_uid=_account(engine).hex,
        target_portfolio_uid=portfolio.hex,
    )


def _deletes(markets) -> list[str]:
    return [sql for sql in markets.statements if sql.lstrip().upper().startswith("DELETE")]


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


def _catalog(engine, portfolio: uuid.UUID, *, values: str) -> None:
    _insert(
        engine,
        "ms_markets__portfoliodatasetavailability",
        portfolio_uid=portfolio.hex,
        values_meta_table_uid=values,
        weights_meta_table_uid=None,
        signal_meta_table_uid=None,
        population_state="unavailable",
        row_count=None,
        earliest_time_index=None,
        latest_time_index=None,
    )


def _serve_tables(monkeypatch, engine, tables: dict[str, tuple], *, unreadable=()) -> list[str]:
    """Serve ``MetaTable.get_by_uid`` and ``run_query`` for provider tables from ``engine``.

    ``tables`` maps a table uid to its identifier, physical name and, optionally, the
    column pair of its key to the portfolio table (the contract's
    ``portfolio_identifier`` -> ``unique_identifier`` by default). Returns the SQL of
    every query run.
    """

    from metatables import MetaTable
    from metatables.models import MetaTableForeignKeyPayload

    def get_by_uid(cls, uid, timeout=None, **filters):
        if str(uid) in unreadable or str(uid) not in tables:
            raise LookupError(f"MetaTable {uid} was not found.")
        identifier, name, *key = tables[str(uid)]
        source, target = key[0] if key else ("portfolio_identifier", "unique_identifier")
        return MetaTable.model_construct(
            uid=str(uid),
            identifier=identifier,
            physical_schema="main",
            physical_table_name=name,
            foreign_keys=[
                MetaTableForeignKeyPayload(
                    name=f"fk_{name}_portfolio_identifier",
                    source_columns=[source],
                    target_table_uid=PORTFOLIO_TABLE_UID,
                    target_columns=[target],
                    on_delete="restrict",
                )
            ],
        )

    queries: list[str] = []

    def run_query(self, sql, *, max_rows=None, statement_timeout_ms=None, timeout=None):
        queries.append(sql)
        with engine.connect() as connection:
            rows = [dict(row) for row in connection.exec_driver_sql(sql).mappings()]
        return {"ok": True, "results": rows, "truncated": False, "row_count": len(rows)}

    monkeypatch.setattr(MetaTable, "get_by_uid", classmethod(get_by_uid))
    monkeypatch.setattr(MetaTable, "run_query", run_query)
    return queries


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


@pytest.mark.parametrize("key", list(DATASETS))
def test_the_portfolio_is_deleted_with_its_rows_in_each_dataset(markets, key: str) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, key)
    _dataset_row(engine, key, identifier, when=WHEN + dt.timedelta(days=1))
    other, other_identifier = _portfolio_with(engine, key)
    assert {identifier, other_identifier} <= set(_progress(markets, key))

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
        "statistics_not_refreshed": [],
    }
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _exists(engine, other)
    assert _dataset_rows(engine, other_identifier)[key] == 1
    # Only the table that lost rows is refreshed, after the transaction: it deletes nothing.
    assert markets.refreshes == [(key, [identifier], 0)]
    # The stored progress no longer lists the deleted identifier; the other one stays.
    progress = markets.index_stats[key]["index_progress"]
    assert identifier not in progress and other_identifier in progress


def test_all_seven_datasets_go_in_one_transaction_with_the_portfolio(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _catalog(engine, portfolio, values=PROVIDER_VALUES_UID)
    group = _insert(engine, "ms_markets__portfoliogroup")
    _insert(
        engine,
        "ms_markets__portfoliogroupmembership",
        portfolio_group_uid=group["uid"],
        portfolio_uid=portfolio.hex,
    )
    # The catalog names an instance another application owns; it holds no rows of this
    # portfolio, so it does not block.
    _create_provider_tables(engine)
    queries = _serve_tables(
        monkeypatch,
        engine,
        {PROVIDER_VALUES_UID: ("PortfoliosTS.provider_key", PROVIDER_VALUES_TABLE)},
    )
    markets.statements.clear()

    deleted = delete_portfolio_record(markets.context, uid=str(portfolio))

    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    assert deleted["statistics_not_refreshed"] == []
    assert markets.refreshes == [(key, [identifier], 0) for key in DATASETS]
    assert all(stats == {} for stats in markets.index_stats.values())  # every table is empty
    assert len(queries) == 1 and PROVIDER_VALUES_TABLE in queries[0]
    assert len(_deletes(markets)) == len(DATASETS) + 1
    assert not any("provider_ns__" in sql for sql in markets.statements)
    assert not _exists(engine, portfolio)
    assert set(_dataset_rows(engine, identifier).values()) == {0}
    assert _count(engine, "ms_markets__portfoliodatasetavailability") == 0  # its CASCADE key
    assert _count(engine, "ms_markets__portfoliogroupmembership") == 0  # its CASCADE key
    assert _count(engine, "ms_markets__portfoliogroup") == 1


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
    assert markets.refreshes == []
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
    assert markets.refreshes == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


# Other applications' tables --------------------------------------------------------------


def test_a_catalogued_instance_holding_rows_blocks_the_delete(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _create_provider_tables(engine)
    _provider_row(engine, PROVIDER_VALUES_TABLE, identifier)
    _catalog(engine, portfolio, values=PROVIDER_VALUES_UID)
    _serve_tables(
        monkeypatch,
        engine,
        {PROVIDER_VALUES_UID: ("PortfoliosTS.provider_key", PROVIDER_VALUES_TABLE)},
    )

    preflight = _preflight(markets, portfolio)
    with pytest.raises(PortfolioDeleteConflictError) as refused:
        delete_portfolio_record(markets.context, uid=portfolio)

    label = f"Table PortfoliosTS.provider_key ({PROVIDER_VALUES_UID}), which another application owns,"
    assert preflight["allowed"] is False
    assert preflight["blockers"] == [
        f"{label} holds 1 row that references it (RESTRICT key); Markets does not delete them."
    ]
    assert preflight["row_counts"] == {key: 1 for key in DATASETS}
    assert label in str(refused.value)
    assert "delete them through the application that owns the table" in str(refused.value)
    assert _deletes(markets) == []
    assert markets.refreshes == []
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert _count(engine, PROVIDER_VALUES_TABLE) == 1


def test_a_restrict_key_from_the_impact_blocks_while_its_table_holds_rows(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    clean, clean_identifier = _portfolio_with(engine, *DATASETS)
    _create_provider_tables(engine)
    _provider_row(engine, PROVIDER_LEDGER_TABLE, identifier)
    _serve_impact(
        monkeypatch,
        _provider_node(PROVIDER_LEDGER_UID, "PortfolioEventLedgerTS.provider_key", PROVIDER_LEDGER_TABLE),
    )
    queries = _serve_tables(
        monkeypatch,
        engine,
        {PROVIDER_LEDGER_UID: ("PortfolioEventLedgerTS.provider_key", PROVIDER_LEDGER_TABLE)},
    )

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[portfolio, clean])
    blocked = {item["uid"]: item["blockers"] for item in preflight["portfolios"]}
    with pytest.raises(PortfolioDeleteConflictError, match="PortfolioEventLedgerTS.provider_key"):
        delete_portfolio_record(markets.context, uid=portfolio)
    deleted = delete_portfolio_record(markets.context, uid=clean)

    constraint = f"RESTRICT key fk_{PROVIDER_LEDGER_TABLE}_portfolio_identifier"
    assert preflight["allowed"] is False
    assert blocked[str(clean)] == []
    assert blocked[str(portfolio)] == [
        f"Table PortfolioEventLedgerTS.provider_key ({PROVIDER_LEDGER_UID}), which another "
        f"application owns, holds 1 row that references it ({constraint}); Markets does not "
        "delete them."
    ]
    # One query for the whole selection; the weights table is Markets' own.
    assert len(queries) == 3 and all(PROVIDER_LEDGER_TABLE in sql for sql in queries)
    assert deleted["deleted_rows"] == {key: 1 for key in DATASETS}
    # Only the clean portfolio's delete refreshed anything.
    assert markets.refreshes == [(key, [clean_identifier], 0) for key in DATASETS]
    assert not _exists(engine, clean) and set(_dataset_rows(engine, clean_identifier).values()) == {0}
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert not any("provider_ns__" in sql for sql in markets.statements)


def test_a_table_keyed_by_the_portfolio_uid_blocks_while_it_holds_rows(markets, monkeypatch) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    clean, _ = _portfolio_with(engine, *DATASETS)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"CREATE TABLE {PROVIDER_SIDECAR_TABLE} (portfolio_uid CHAR(32) PRIMARY KEY "
            "REFERENCES ms_markets__portfolio (uid) ON DELETE RESTRICT, note TEXT)"
        )
        connection.exec_driver_sql(
            f"INSERT INTO {PROVIDER_SIDECAR_TABLE} VALUES (?, 'kept')", (portfolio.hex,)
        )
    _serve_impact(
        monkeypatch,
        _provider_node(PROVIDER_SIDECAR_UID, "PortfolioSidecar", PROVIDER_SIDECAR_TABLE),
    )
    queries = _serve_tables(
        monkeypatch,
        engine,
        {PROVIDER_SIDECAR_UID: ("PortfolioSidecar", PROVIDER_SIDECAR_TABLE, ("portfolio_uid", "uid"))},
    )

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[portfolio, clean])
    blocked = {item["uid"]: item["blockers"] for item in preflight["portfolios"]}
    with pytest.raises(PortfolioDeleteConflictError, match="PortfolioSidecar"):
        delete_portfolio_record(markets.context, uid=portfolio)

    # The count joins the portfolio table, so a uid key is counted by identifier.
    assert 'JOIN "main"."ms_markets__portfolio" AS p' in queries[0]
    assert blocked[str(clean)] == []
    assert blocked[str(portfolio)] == [
        f"Table PortfolioSidecar ({PROVIDER_SIDECAR_UID}), which another application owns, "
        f"holds 1 row that references it (RESTRICT key fk_{PROVIDER_SIDECAR_TABLE}_portfolio_identifier); "
        "Markets does not delete them."
    ]
    assert delete_portfolio_record(markets.context, uid=clean)["deleted_rows"] == {key: 1 for key in DATASETS}
    assert _exists(engine, portfolio)
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}
    assert _count(engine, PROVIDER_SIDECAR_TABLE) == 1


@pytest.mark.parametrize("hidden", [True, False])
def test_a_table_that_cannot_be_checked_blocks_the_delete(markets, monkeypatch, hidden: bool) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    if hidden:
        _serve_impact(monkeypatch, {"id": "hidden:1", "type": "hidden"})
        expected = "A table you cannot view references portfolios"
    else:
        _serve_impact(
            monkeypatch,
            _provider_node(PROVIDER_LEDGER_UID, "PortfolioEventLedgerTS.provider_key", PROVIDER_LEDGER_TABLE),
        )
        _serve_tables(monkeypatch, engine, {}, unreadable={PROVIDER_LEDGER_UID})
        expected = f"Table PortfolioEventLedgerTS.provider_key ({PROVIDER_LEDGER_UID})"

    preflight = _preflight(markets, portfolio)
    with pytest.raises(PortfolioDeleteConflictError, match="could not be checked"):
        delete_portfolio_record(markets.context, uid=portfolio)

    assert preflight["allowed"] is False
    assert len(preflight["blockers"]) == 1 and preflight["blockers"][0].startswith(expected)
    assert "could not be checked" in preflight["blockers"][0]
    assert _deletes(markets) == []
    assert markets.refreshes == []
    assert _dataset_rows(engine, identifier) == {key: 1 for key in DATASETS}


def test_a_restrict_key_the_checks_cannot_see_refuses_the_whole_delete(markets) -> None:
    """Issue 93: the database refuses the portfolio row last; the datasets are kept."""

    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, *DATASETS)
    _create_provider_tables(engine)
    _provider_row(engine, PROVIDER_VALUES_TABLE, identifier)

    preflight = _preflight(markets, portfolio)
    with pytest.raises(PortfolioDeleteConflictError, match="nothing was deleted") as refused:
        delete_portfolio_record(markets.context, uid=portfolio)

    # Without MetaTables' impact the checks cannot see the key; the transaction can.
    assert preflight["allowed"] is True
    assert "FOREIGN KEY constraint failed" in str(refused.value)
    assert len(_deletes(markets)) == len(DATASETS) + 1
    assert markets.refreshes == []
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
    assert markets.refreshes == []
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
    assert markets.refreshes == []


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
    assert markets.refreshes == []


# Bulk ------------------------------------------------------------------------------------


def test_bulk_delete_deletes_each_portfolio_and_reports_the_rest(markets) -> None:
    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, *DATASETS)
    blocked, blocked_identifier = _portfolio_with(engine, *DATASETS)
    _virtual_fund(engine, blocked)
    missing = uuid.uuid4()

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[first, blocked, missing])
    result = bulk_delete_portfolio_records(markets.context, uids=[first, blocked, missing, first])

    assert preflight["allowed"] is False
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
    assert markets.refreshes == [(key, [first_identifier], 0) for key in DATASETS]


def test_bulk_delete_refreshes_each_table_once_for_the_portfolios_it_deleted(markets) -> None:
    engine = markets.engine
    first, first_identifier = _portfolio_with(engine, "weights", "values")
    second, second_identifier = _portfolio_with(engine, "values", "state")
    blocked, blocked_identifier = _portfolio_with(engine, *DATASETS)
    _virtual_fund(engine, blocked)

    result = bulk_delete_portfolio_records(markets.context, uids=[first, second, blocked])

    assert [item["uid"] for item in result["deleted"]] == [str(first), str(second)]
    assert [item["statistics_not_refreshed"] for item in result["deleted"]] == [[], []]
    assert markets.refreshes == [
        ("weights", [first_identifier], 0),
        ("values", [first_identifier, second_identifier], 0),
        ("state", [second_identifier], 0),
    ]
    for key in ("weights", "values", "state"):
        progress = markets.index_stats[key]["index_progress"]
        assert first_identifier not in progress and second_identifier not in progress
        assert blocked_identifier in progress


def test_a_refresh_failure_still_reports_the_delete_and_names_the_dataset(markets, caplog) -> None:
    engine = markets.engine
    portfolio, identifier = _portfolio_with(engine, "weights", "values")
    other, _ = _portfolio_with(engine, "values")
    markets.failing.add("values")

    with caplog.at_level(logging.ERROR):
        deleted = delete_portfolio_record(markets.context, uid=portfolio)
        result = bulk_delete_portfolio_records(markets.context, uids=[other])

    assert deleted["statistics_not_refreshed"] == ["values"]
    assert deleted["detail"] == (
        f"Portfolio {identifier!r} deleted with its datasets. MetaTables could not refresh the "
        "stored update statistics of values; see statistics_not_refreshed."
    )
    assert deleted["deleted_rows"] == {key: {"weights": 1, "values": 1}.get(key, 0) for key in DATASETS}
    assert not _exists(engine, portfolio) and set(_dataset_rows(engine, identifier).values()) == {0}
    assert result["deleted"][0]["statistics_not_refreshed"] == ["values"]
    assert result["detail"].endswith(
        "MetaTables could not refresh the stored update statistics of values; "
        "see statistics_not_refreshed."
    )
    assert not _exists(engine, other)
    assert [key for key, _identifiers, _deleted in markets.refreshes] == ["weights"]
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert len(errors) == 2 and all("could not refresh" in record.getMessage() for record in errors)


def test_the_preflight_counts_match_what_the_delete_removes(markets) -> None:
    engine = markets.engine
    first, _ = _portfolio_with(engine, *DATASETS)
    second, _ = _portfolio_with(engine, "values", "weights")
    _dataset_row(engine, "values", _identifier(engine, second), when=WHEN + dt.timedelta(days=1))
    totals_before = {key: _count(engine, name) for key, name in DATASETS.items()}

    preflight = preflight_bulk_delete_portfolio_records(markets.context, uids=[first, second])
    result = bulk_delete_portfolio_records(markets.context, uids=[first, second])

    assert preflight["allowed"] is True
    assert preflight["detail"] == "2 portfolios are ready for deletion with their datasets."
    counts = {item["uid"]: item["row_counts"] for item in preflight["portfolios"]}
    assert counts[str(second)] == {key: {"values": 2, "weights": 1}.get(key, 0) for key in DATASETS}
    assert {item["uid"]: item["deleted_rows"] for item in result["deleted"]} == counts
    removed = {key: totals_before[key] - _count(engine, name) for key, name in DATASETS.items()}
    assert removed == {key: sum(item[key] for item in counts.values()) for key in DATASETS}
