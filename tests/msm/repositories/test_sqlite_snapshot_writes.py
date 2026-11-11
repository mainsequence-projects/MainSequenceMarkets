"""The account snapshot writes on a SQLite DataSource, end to end (MainSequenceMarkets#53).

SQLite accepts only `SELECT` inside `WITH`, so these writes run there as statement
lists in one MetaTables transaction (MetaTables ADR 0026). Each test migrates a fresh
SQLite file to head with the Markets migrations, then runs the repositories through
MetaTables' own server code for the local runtime: `MetaTable.execute_operation` and
`MetaTable.execute_transaction` go, after wire serialization, to the SQLite backend's
`execute` and `execute_transaction`, which bind values and own the transaction as the
local API does. Nothing leaves the process.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from alembic import command

import metatables.runtime_context
from metatables import (
    MetaTable,
    MetaTableCompiledSQLOperation,
    MetaTableCompiledSQLTransaction,
    MetaTableTransactionGuardError,
)
from metatables.runtime_contract import RuntimeContext

from msm.repositories.accounts import (
    replace_account_holdings_snapshot,
    replace_account_target_positions_snapshot,
)
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.virtual_funds import replace_account_virtual_fund_holdings
from tests.msm.maintenance.test_legacy_schema_migration import _config

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
STORED_WHEN = "2026-11-10 15:30:00.000000"  # How the local runtime stores a UTC timestamp.


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    from mainsequence.code_repository_context import GitCodeRepositorySourceContext
    from metatables.api.backend.backends.access import ExecutionIdentity
    from metatables.api.backend.backends.contracts import SQLExecutionError
    from metatables.api.backend.backends.registry import backend_for
    from metatables.api.backend.integrations.local_workspace import select_local_workspace

    workspace = select_local_workspace(
        source=GitCodeRepositorySourceContext(
            tmp_path, "https://example.test/repo", "test", "refs/heads/test", "a" * 40
        ),
        values={"METATABLES_LOCAL_STORAGE_DIR": str(tmp_path)},
    )
    workspace.tables_path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(f"sqlite:///{workspace.tables_path}")
    with engine.connect() as connection:
        command.upgrade(_config(connection), "head")
        connection.commit()

    source = workspace.data_source
    backend = backend_for(source)
    tables = frozenset(("main", name) for name in sa.inspect(engine).get_table_names())
    identity = ExecutionIdentity(uuid.uuid4(), "fixture", None, tables, tables)
    runtime = RuntimeContext(
        git_source=None,
        dialect="sqlite",
        paramstyle="named",
        data_source={"uid": str(source.uid)},
        default_schema="main",
    )
    monkeypatch.setattr(metatables.runtime_context, "get_runtime_context", lambda: runtime)

    def execute_operation(cls, operation, *, timeout=None):
        wire = MetaTableCompiledSQLOperation.model_validate_json(operation.model_dump_json())
        return backend.sql.execute(
            identity=identity,
            sql_text=wire.statement.sql,
            operation=wire.operation,
            parameters=wire.statement.parameters,
            parameter_types=wire.statement.parameter_types,
            **wire.limits.model_dump(include={"max_rows", "offset", "statement_timeout_ms"}),
        )

    def execute_transaction(cls, transaction, *, timeout=None):
        wire = MetaTableCompiledSQLTransaction.model_validate_json(transaction.model_dump_json())
        try:
            return backend.sql.execute_transaction(
                identity=identity,
                operation=wire.operation,
                statements=[
                    statement.model_dump(
                        include={"sql", "parameters", "parameter_types", "expect_rows", "label"}
                    )
                    for statement in wire.statements
                ],
                **wire.limits.model_dump(include={"max_rows", "offset", "statement_timeout_ms"}),
            )
        except SQLExecutionError as error:
            # The route answers 409 and the client raises this (MetaTables ADR 0026).
            if error.code != MetaTableTransactionGuardError.code:
                raise
            raise MetaTableTransactionGuardError(
                str(error),
                statement_index=error.extra.get("statement_index"),
                label=error.extra.get("label"),
                expect_rows=error.extra.get("expect_rows"),
                row_count=error.extra.get("row_count"),
            ) from error

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(execute_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(execute_transaction))
    return SimpleNamespace(engine=engine, context=MarketsRepositoryContext())


def _insert(engine, table_name: str, **values) -> dict:
    """Insert one row, filling required columns the test does not care about."""

    table = sa.Table(table_name, sa.MetaData(), autoload_with=engine)
    row = dict(values)
    for column in table.columns:
        if column.name in row or column.nullable or column.server_default is not None:
            continue
        type_name = str(column.type).upper()
        if type_name == "CHAR(32)":
            row[column.name] = uuid.uuid4().hex
        elif "BOOL" in type_name:
            row[column.name] = True
        elif "DATETIME" in type_name:
            row[column.name] = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
        elif type_name == "DATE":
            row[column.name] = dt.date(2026, 1, 1)
        elif "INT" in type_name:
            row[column.name] = 1
        elif "FLOAT" in type_name or "REAL" in type_name or "NUMERIC" in type_name:
            row[column.name] = 1.0
        elif "JSON" in type_name:
            row[column.name] = {}
        else:
            length = getattr(column.type, "length", None) or 255
            row[column.name] = f"{uuid.uuid4().hex[:8]}-{column.name}"[:length]
    with engine.begin() as connection:
        connection.execute(table.insert(), row)
    return row


def _rows(engine, sql: str, **parameters) -> list[dict]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(sa.text(sql), parameters).mappings()]


def _count(engine, table_name: str) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT count(*) FROM {table_name}")).scalar_one()


def _account(engine) -> uuid.UUID:
    account = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__account",
        uid=account.hex,
        unique_identifier=f"account-{account.hex[:8]}",
        account_name="SQLite account",
        is_paper=True,
        account_is_active=True,
    )
    return account


def _asset(engine, unique_identifier: str) -> uuid.UUID:
    asset = uuid.uuid4()
    _insert(engine, "ms_markets__asset", uid=asset.hex, unique_identifier=unique_identifier)
    return asset


def _portfolio(engine, *, retired: bool = False) -> uuid.UUID:
    calendar = _insert(engine, "ms_markets__calendar")
    portfolio = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__portfolio",
        uid=portfolio.hex,
        unique_identifier=f"portfolio-{portfolio.hex[:8]}",
        calendar_uid=calendar["uid"],
        retired_at=dt.datetime(2026, 11, 1, tzinfo=dt.UTC) if retired else None,
    )
    return portfolio


# Holdings ----------------------------------------------------------------------------


def _write_holdings(sqlite_markets, account, positions, *, overwrite=False):
    return replace_account_holdings_snapshot(
        sqlite_markets.context,
        holdings_set_uid=uuid.uuid4(),
        account_uid=account,
        holdings_date=WHEN,
        positions=positions,
        overwrite=overwrite,
    )


def test_holdings_snapshot_writes_the_set_and_its_rows(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")
    _asset(engine, "BBB")

    result = _write_holdings(
        sqlite_markets,
        account,
        [
            {"asset_identifier": "AAA", "quantity": 10.0, "extra_details": {"lot": 1}},
            {"asset_identifier": "BBB", "quantity": 5.5, "direction": -1},
        ],
    )

    assert sorted(row["asset_identifier"] for row in result["rows"]) == ["AAA", "BBB"]
    (holdings_set,) = _rows(engine, "SELECT uid, account_uid, time_index FROM ms_markets__accountholdingsset")
    assert holdings_set["account_uid"] == account.hex
    assert holdings_set["time_index"] == STORED_WHEN
    stored = _rows(
        engine,
        "SELECT asset_identifier, quantity, direction, holdings_set_uid, time_index, "
        "target_trade_time, extra_details FROM ms_markets__accountholdingsts ORDER BY asset_identifier",
    )
    assert [(row["asset_identifier"], row["quantity"], row["direction"]) for row in stored] == [
        ("AAA", 10.0, 1),
        ("BBB", 5.5, -1),
    ]
    assert {row["holdings_set_uid"] for row in stored} == {holdings_set["uid"]}
    assert {row["time_index"] for row in stored} == {STORED_WHEN}
    assert {row["target_trade_time"] for row in stored} == {STORED_WHEN}
    assert json.loads(stored[0]["extra_details"]) == {"lot": 1}


def test_existing_holdings_snapshot_is_refused_without_overwrite_and_replaced_with_it(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")
    _asset(engine, "BBB")
    _write_holdings(sqlite_markets, account, [{"asset_identifier": "AAA", "quantity": 1.0}])

    refused = _write_holdings(sqlite_markets, account, [{"asset_identifier": "BBB", "quantity": 2.0}])

    assert refused["rows"] == []
    assert _rows(engine, "SELECT asset_identifier, quantity FROM ms_markets__accountholdingsts") == [
        {"asset_identifier": "AAA", "quantity": 1.0}
    ]

    replaced = _write_holdings(
        sqlite_markets, account, [{"asset_identifier": "BBB", "quantity": 2.0}], overwrite=True
    )

    assert [row["asset_identifier"] for row in replaced["rows"]] == ["BBB"]
    assert _rows(engine, "SELECT asset_identifier, quantity FROM ms_markets__accountholdingsts") == [
        {"asset_identifier": "BBB", "quantity": 2.0}
    ]
    assert _count(engine, "ms_markets__accountholdingsset") == 1


def test_a_failing_holdings_row_rolls_back_the_whole_snapshot(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")

    with pytest.raises(Exception, match="FOREIGN KEY"):
        _write_holdings(
            sqlite_markets,
            account,
            [
                {"asset_identifier": "AAA", "quantity": 1.0},
                {"asset_identifier": "NOT-AN-ASSET", "quantity": 1.0},
            ],
        )

    assert _count(engine, "ms_markets__accountholdingsset") == 0
    assert _count(engine, "ms_markets__accountholdingsts") == 0


# Target positions ----------------------------------------------------------------------


def _write_target(sqlite_markets, account, positions, *, overwrite=False):
    return replace_account_target_positions_snapshot(
        sqlite_markets.context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account,
        account_name="SQLite account",
        target_positions_date=WHEN,
        positions=positions,
        overwrite=overwrite,
    )


def _portfolio_position(portfolio, exposure=1000.0):
    return {
        "target_type": "portfolio",
        "target_uid": portfolio,
        "portfolio_uid": portfolio,
        "constant_notional_exposure": exposure,
        "metadata_json": {"note": "sqlite"},
    }


def test_target_snapshot_writes_the_allocation_its_position_set_and_rows(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    asset = _asset(engine, "AAA")

    result = _write_target(
        sqlite_markets,
        account,
        [
            _portfolio_position(portfolio),
            {"target_type": "asset", "target_uid": asset, "asset_uid": asset, "single_asset_quantity": 3.0},
        ],
    )

    assert sorted(row["target_type"] for row in result["rows"]) == ["asset", "portfolio"]
    (model,) = _rows(engine, "SELECT uid, allocation_model_name, metadata_json FROM ms_markets__accountallocationmodel")
    assert model["allocation_model_name"] == str(account)
    (allocation,) = _rows(
        engine,
        "SELECT uid, unique_identifier, account_uid, account_allocation_model_uid, display_name, "
        "is_active, source FROM ms_markets__accounttargetallocation",
    )
    assert allocation["unique_identifier"] == str(account)  # Dashed, as on PostgreSQL.
    assert allocation["account_uid"] == account.hex
    assert allocation["account_allocation_model_uid"] == model["uid"]
    assert (allocation["display_name"], allocation["is_active"], allocation["source"]) == (
        "SQLite account",
        1,
        "apps.v1",
    )
    (position_set,) = _rows(
        engine,
        "SELECT uid, account_target_allocation_uid, position_set_time FROM ms_markets__positionset",
    )
    assert position_set["account_target_allocation_uid"] == allocation["uid"]
    assert position_set["position_set_time"] == STORED_WHEN
    stored = _rows(
        engine,
        "SELECT target_type, portfolio_uid, asset_uid, constant_notional_exposure, "
        "single_asset_quantity, position_set_uid, time_index, metadata_json "
        "FROM ms_markets__targetpositionsts ORDER BY target_type",
    )
    assert [
        (row["target_type"], row["asset_uid"], row["portfolio_uid"]) for row in stored
    ] == [("asset", asset.hex, None), ("portfolio", None, portfolio.hex)]
    assert stored[1]["constant_notional_exposure"] == 1000.0
    assert stored[0]["single_asset_quantity"] == 3.0
    assert {row["position_set_uid"] for row in stored} == {position_set["uid"]}
    assert {row["time_index"] for row in stored} == {STORED_WHEN}
    assert json.loads(stored[1]["metadata_json"]) == {"note": "sqlite"}


def test_existing_target_snapshot_is_refused_without_overwrite_and_replaced_with_it(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    first, second = _portfolio(engine), _portfolio(engine)
    _write_target(sqlite_markets, account, [_portfolio_position(first)])

    refused = _write_target(sqlite_markets, account, [_portfolio_position(second)])

    assert refused["rows"] == []
    assert _rows(engine, "SELECT portfolio_uid FROM ms_markets__targetpositionsts") == [
        {"portfolio_uid": first.hex}
    ]

    replaced = _write_target(sqlite_markets, account, [_portfolio_position(second, 50.0)], overwrite=True)

    assert [row["constant_notional_exposure"] for row in replaced["rows"]] == [50.0]
    assert _rows(engine, "SELECT portfolio_uid FROM ms_markets__targetpositionsts") == [
        {"portfolio_uid": second.hex}
    ]
    assert _count(engine, "ms_markets__positionset") == 1
    assert _count(engine, "ms_markets__accounttargetallocation") == 1


def test_a_retired_portfolio_refuses_the_target_snapshot_and_nothing_is_written(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    live, retired = _portfolio(engine), _portfolio(engine, retired=True)

    result = _write_target(
        sqlite_markets, account, [_portfolio_position(live), _portfolio_position(retired)]
    )

    assert result["rows"] == []
    for table in (
        "ms_markets__accountallocationmodel",
        "ms_markets__accounttargetallocation",
        "ms_markets__positionset",
        "ms_markets__targetpositionsts",
    ):
        assert _count(engine, table) == 0, table


def test_clearing_the_target_writes_an_empty_position_set_and_deactivates_the_allocation(
    sqlite_markets,
) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    _write_target(sqlite_markets, account, [_portfolio_position(portfolio)])

    later = WHEN + dt.timedelta(days=1)
    cleared = replace_account_target_positions_snapshot(
        sqlite_markets.context,
        account_allocation_model_uid=uuid.uuid4(),
        account_target_allocation_uid=uuid.uuid4(),
        position_set_uid=uuid.uuid4(),
        account_uid=account,
        account_name="SQLite account",
        target_positions_date=later,
        positions=[],
    )

    position_sets = _rows(
        engine, "SELECT uid, position_set_time FROM ms_markets__positionset ORDER BY position_set_time"
    )
    assert [row["position_set_time"] for row in position_sets] == [
        STORED_WHEN,
        "2026-11-11 15:30:00.000000",
    ]
    assert [row["uid"] for row in cleared["rows"]] == [position_sets[1]["uid"]]
    assert _rows(engine, "SELECT is_active FROM ms_markets__accounttargetallocation") == [{"is_active": 0}]
    # History keeps the earlier snapshot; the clear adds an empty one.
    assert _rows(engine, "SELECT position_set_uid FROM ms_markets__targetpositionsts") == [
        {"position_set_uid": position_sets[0]["uid"]}
    ]


def test_clearing_over_an_existing_snapshot_is_refused_without_overwrite(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    portfolio = _portfolio(engine)
    _write_target(sqlite_markets, account, [_portfolio_position(portfolio)])

    refused = _write_target(sqlite_markets, account, [])

    assert refused["rows"] == []
    assert _rows(engine, "SELECT is_active FROM ms_markets__accounttargetallocation") == [{"is_active": 1}]
    assert _count(engine, "ms_markets__targetpositionsts") == 1

    cleared = _write_target(sqlite_markets, account, [], overwrite=True)

    assert len(cleared["rows"]) == 1
    assert _rows(engine, "SELECT is_active FROM ms_markets__accounttargetallocation") == [{"is_active": 0}]
    assert _count(engine, "ms_markets__targetpositionsts") == 0
    assert _count(engine, "ms_markets__positionset") == 1


# Virtual funds -------------------------------------------------------------------------


def _source_holdings_set(engine, account) -> uuid.UUID:
    source = uuid.uuid4()
    _insert(
        engine,
        "ms_markets__accountholdingsset",
        uid=source.hex,
        account_uid=account.hex,
        time_index=WHEN,
    )
    return source


def _fund(unique_identifier, portfolio, *holdings):
    return {
        "unique_identifier": unique_identifier,
        "target_portfolio_uid": portfolio,
        "holdings": [
            {
                "asset_identifier": asset_identifier,
                "allocated_quantity": quantity,
                "allocation_strategy": "explicit",
                "direction": 1,
                "target_trade_time": WHEN,
                "extra_details": {"fund": unique_identifier},
            }
            for asset_identifier, quantity in holdings
        ],
    }


def _write_funds(sqlite_markets, account, source, funds):
    return replace_account_virtual_fund_holdings(
        sqlite_markets.context,
        account_uid=account,
        source_account_holdings_set_uid=source,
        allocation_time=WHEN,
        funds=funds,
    )


def test_virtual_fund_holdings_replace_the_source_sets_allocation(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = _account(engine)
    source = _source_holdings_set(engine, account)
    first, second = _portfolio(engine), _portfolio(engine)
    _asset(engine, "AAA")
    _asset(engine, "BBB")

    written = _write_funds(
        sqlite_markets,
        account,
        source,
        [_fund("fund-a", first, ("AAA", 1.0)), _fund("fund-b", second, ("BBB", 2.0))],
    )

    assert len(written["rows"]) == 2
    funds = {
        row["unique_identifier"]: row
        for row in _rows(engine, "SELECT uid, unique_identifier, account_uid, target_portfolio_uid FROM ms_markets__virtualfund")
    }
    assert {name: row["target_portfolio_uid"] for name, row in funds.items()} == {
        "fund-a": first.hex,
        "fund-b": second.hex,
    }
    sets = _rows(engine, "SELECT uid, virtual_fund_uid, source_account_holdings_set_uid, time_index FROM ms_markets__virtualfundholdingsset")
    assert {row["virtual_fund_uid"] for row in sets} == {row["uid"] for row in funds.values()}
    assert {row["source_account_holdings_set_uid"] for row in sets} == {source.hex}
    assert {row["time_index"] for row in sets} == {STORED_WHEN}
    stored = _rows(
        engine,
        "SELECT virtual_fund_uid, virtual_fund_holdings_set_uid, asset_identifier, allocated_quantity, "
        "time_index, target_trade_time, extra_details FROM ms_markets__virtualfundholdingsts "
        "ORDER BY asset_identifier",
    )
    set_by_fund = {row["virtual_fund_uid"]: row["uid"] for row in sets}
    assert [(row["asset_identifier"], row["allocated_quantity"]) for row in stored] == [
        ("AAA", 1.0),
        ("BBB", 2.0),
    ]
    assert stored[0]["virtual_fund_uid"] == funds["fund-a"]["uid"]
    assert all(set_by_fund[row["virtual_fund_uid"]] == row["virtual_fund_holdings_set_uid"] for row in stored)
    assert {(row["time_index"], row["target_trade_time"]) for row in stored} == {(STORED_WHEN, STORED_WHEN)}
    assert json.loads(stored[0]["extra_details"]) == {"fund": "fund-a"}

    # A second allocation of the same source keeps fund-a, drops fund-b's set and rows.
    rewritten = _write_funds(sqlite_markets, account, source, [_fund("fund-a", second, ("BBB", 3.0))])

    assert [row["allocated_quantity"] for row in rewritten["rows"]] == [3.0]
    assert _rows(engine, "SELECT virtual_fund_uid FROM ms_markets__virtualfundholdingsset") == [
        {"virtual_fund_uid": funds["fund-a"]["uid"]}
    ]
    assert _rows(
        engine, "SELECT asset_identifier, allocated_quantity FROM ms_markets__virtualfundholdingsts"
    ) == [{"asset_identifier": "BBB", "allocated_quantity": 3.0}]
    assert _rows(engine, "SELECT target_portfolio_uid FROM ms_markets__virtualfund WHERE unique_identifier = 'fund-a'") == [
        {"target_portfolio_uid": second.hex}
    ]


def test_a_fund_of_another_account_stops_the_whole_virtual_fund_write(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    owner, account = _account(engine), _account(engine)
    portfolio = _portfolio(engine)
    _asset(engine, "AAA")
    _write_funds(
        sqlite_markets, owner, _source_holdings_set(engine, owner), [_fund("taken", portfolio, ("AAA", 1.0))]
    )
    before = {
        table: _count(engine, table)
        for table in (
            "ms_markets__virtualfund",
            "ms_markets__virtualfundholdingsset",
            "ms_markets__virtualfundholdingsts",
        )
    }

    result = _write_funds(
        sqlite_markets,
        account,
        _source_holdings_set(engine, account),
        [_fund("own", portfolio, ("AAA", 1.0)), _fund("taken", portfolio, ("AAA", 2.0))],
    )

    assert result["rows"] == []
    assert {table: _count(engine, table) for table in before} == before
    assert _rows(engine, "SELECT account_uid FROM ms_markets__virtualfund WHERE unique_identifier = 'taken'") == [
        {"account_uid": owner.hex}
    ]


# The services behind the routes -------------------------------------------------------
#
# Routes pass UUIDs as text, and each service reads back what it wrote. These run the
# whole service on SQLite (MetaTables 0.1.61 binds text UUIDs there, MetaTables#100/#101),
# through the `msm.services` entry points the Markets API calls.


def test_the_holdings_service_writes_reads_back_and_refuses_a_repeat(sqlite_markets) -> None:
    from msm.services import add_account_holdings_snapshot_response
    from msm.services.accounts import AccountHoldingsSnapshotExistsError

    engine = sqlite_markets.engine
    account = _account(engine)
    _asset(engine, "AAA")

    snapshot = add_account_holdings_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        holdings_date=WHEN,
        positions=[{"asset_identifier": "AAA", "quantity": 2.0}],
    )

    assert snapshot["holdings_date"] == WHEN
    assert [row["asset_identifier"] for row in snapshot["holdings"]] == ["AAA"]
    with pytest.raises(AccountHoldingsSnapshotExistsError):
        add_account_holdings_snapshot_response(
            sqlite_markets.context,
            account_uid=str(account),
            holdings_date=WHEN,
            positions=[{"asset_identifier": "AAA", "quantity": 3.0}],
        )
    assert _rows(engine, "SELECT quantity FROM ms_markets__accountholdingsts") == [{"quantity": 2.0}]


def test_the_target_service_writes_reads_back_and_refuses_repeats_and_retired_portfolios(
    sqlite_markets,
) -> None:
    from msm.services import add_account_target_positions_snapshot_response
    from msm.services.portfolio_lifecycle import PortfolioRetiredError
    from msm.services.target_positions import AccountTargetPositionsSnapshotExistsError

    engine = sqlite_markets.engine
    account = _account(engine)
    live, retired = _portfolio(engine), _portfolio(engine, retired=True)

    def add(portfolio, when=WHEN):
        return add_account_target_positions_snapshot_response(
            sqlite_markets.context,
            account_uid=str(account),
            target_positions_date=when,
            positions=[
                {
                    "target_type": "portfolio",
                    "portfolio_uid": str(portfolio),
                    "constant_notional_exposure": 100.0,
                }
            ],
        )

    snapshot = add(live)

    assert snapshot["target_positions_date"] == WHEN
    assert len(snapshot["positions"]) == 1
    with pytest.raises(AccountTargetPositionsSnapshotExistsError):
        add(live)
    with pytest.raises(PortfolioRetiredError):
        add(retired, WHEN + dt.timedelta(days=1))
    assert _count(engine, "ms_markets__positionset") == 1
    assert _count(engine, "ms_markets__targetpositionsts") == 1
