"""A bulk upsert of any length goes to MetaTables in statements it accepts (MainSequenceMarkets#84).

The first tests compile for PostgreSQL offline and answer each statement themselves, so
they check how a list is split. The others run end to end on a migrated SQLite
DataSource through MetaTables' own SQLite backend, with the trigger of
``test_sqlite_upserts`` that aborts an update which would rewrite a row with the values
it already holds.
"""

from __future__ import annotations

import pytest
from metatables import MetaTable

from msm.models import AssetTable
from msm.repositories import crud
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import (
    MAX_STATEMENT_PARAMETERS,
    MAX_STATEMENT_ROWS,
    MAX_STATEMENT_SQL_CHARACTERS,
    UPSERT_STATUS_COLUMN,
    build_bulk_upsert_model_operation,
    bulk_upsert_model,
)
from tests.msm.repositories.test_sqlite_snapshot_writes import _count, make_sqlite_markets
from tests.msm.repositories.test_sqlite_upserts import _refuse_identical_rewrites

KEY = ("unique_identifier",)
STATUSES = ("inserted", "updated", "unchanged")


def _assets(count: int, asset_type: str = "equity") -> list[dict]:
    return [{"unique_identifier": f"A{index:05d}", "asset_type": asset_type} for index in range(count)]


def _statuses(result) -> list[tuple[str, str]]:
    return [(row["unique_identifier"], row[UPSERT_STATUS_COLUMN]) for row in result["rows"]]


@pytest.fixture
def sent(monkeypatch, offline_postgresql_runtime):
    """Record every PostgreSQL write; answer each of its rows with a status by position."""

    writes = []

    def execute(write, *, context):
        writes.append(write)
        parameters = write.statement.parameters
        count = sum(name.startswith("unique_identifier_m") for name in parameters)
        rows = []
        for index in range(count):
            identifier = parameters[f"unique_identifier_m{index}"]
            rows.append(
                {
                    "unique_identifier": identifier,
                    UPSERT_STATUS_COLUMN: STATUSES[int(identifier[1:]) % 3],
                    "upsert_index": index,
                }
            )
        return {
            "ok": True,
            "rows": rows,
            "row_count": count,
            "truncated": False,
            "max_rows": write.limits.max_rows,
            "pagination": {"limit": write.limits.max_rows},
        }

    monkeypatch.setattr(crud, "execute_markets_write", execute)
    monkeypatch.setattr(crud, "execute_markets_operation", pytest.fail)
    return writes


def _upsert(values, context=None):
    return bulk_upsert_model(
        context or MarketsRepositoryContext(),
        model=AssetTable,
        values=values,
        conflict_columns=KEY,
    )


def _assert_inside_the_limits(writes) -> None:
    for write in writes:
        assert len(write.statement.sql) <= crud.MAX_STATEMENT_SQL_CHARACTERS
        assert len(write.statement.parameters) <= crud.MAX_STATEMENT_PARAMETERS
        rows = sum(name.startswith("unique_identifier_m") for name in write.statement.parameters)
        assert rows <= write.limits.max_rows <= MAX_STATEMENT_ROWS


def test_a_short_list_is_one_statement_with_its_answer_unchanged(sent) -> None:
    result = _upsert(_assets(3))

    assert len(sent) == 1
    assert _statuses(result) == [("A00000", "inserted"), ("A00001", "updated"), ("A00002", "unchanged")]
    assert result["pagination"] == {"limit": 1000}
    assert "upsert_index" not in result["rows"][0]


def test_a_statement_returns_every_row_above_the_default_row_limit(sent) -> None:
    result = _upsert(_assets(1500))

    assert len(sent) == 1
    assert sent[0].limits.max_rows == 1500
    assert result["row_count"] == 1500


def test_a_long_list_goes_in_statements_inside_the_limits(sent) -> None:
    values = _assets(12_000)

    result = _upsert(values)

    assert len(sent) > 1
    _assert_inside_the_limits(sent)
    # The 12,000 rows compiled as one statement are over the limit MetaTables enforces.
    assert sum(len(write.statement.sql) for write in sent) > MAX_STATEMENT_SQL_CHARACTERS
    assert result["row_count"] == 12_000
    assert _statuses(result) == [
        (row["unique_identifier"], STATUSES[index % 3]) for index, row in enumerate(values)
    ]
    assert not result["truncated"]
    assert "pagination" not in result and "max_rows" not in result


def test_a_list_may_need_more_statements_than_one_transaction_holds(sent, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_SQL_CHARACTERS", 20_000)
    values = _assets(4000)

    result = _upsert(values)

    assert len(sent) > 32
    _assert_inside_the_limits(sent)
    assert [row["unique_identifier"] for row in result["rows"]] == [
        row["unique_identifier"] for row in values
    ]


def test_the_bound_values_of_a_statement_are_limited_too(sent, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_PARAMETERS", 500)

    result = _upsert(_assets(1000))

    assert len(sent) > 1
    _assert_inside_the_limits(sent)
    assert result["row_count"] == 1000


def test_a_statement_writes_no_more_rows_than_metatables_returns(sent, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_ROWS", 100)

    result = _upsert(_assets(250))

    assert [write.limits.max_rows for write in sent] == [1000, 1000, 1000]
    assert [len(write.statement.parameters) for write in sent] == [500, 500, 250]
    assert result["row_count"] == 250


def test_the_bytes_of_a_statement_are_limited_too(sent) -> None:
    """Rows of 100,000 characters each: 100 of them are more than one request may carry."""

    values = [
        {"unique_identifier": f"A{index:05d}", "asset_type": "x" * 100_000} for index in range(100)
    ]

    result = _upsert(values)

    assert len(sent) > 1
    for write in sent:
        sent_bytes = sum(len(str(value)) for value in write.statement.parameters.values())
        assert sent_bytes <= crud.MAX_STATEMENT_ROW_BYTES
    assert [row["unique_identifier"] for row in result["rows"]] == [
        row["unique_identifier"] for row in values
    ]


def test_a_row_larger_than_the_byte_limit_goes_alone(sent, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_ROW_BYTES", 10)

    result = _upsert(_assets(3))

    assert len(sent) == 3
    assert result["row_count"] == 3


def test_a_statement_measured_too_short_is_split_again(sent, monkeypatch) -> None:
    """Rows that need more SQL text than the measured ones still go inside the limit."""

    monkeypatch.setattr(crud, "MAX_STATEMENT_SQL_CHARACTERS", 20_000)
    monkeypatch.setattr(crud, "_statement_rows", lambda *args, **kwargs: MAX_STATEMENT_ROWS)
    values = _assets(600)

    result = _upsert(values)

    assert len(sent) > 1
    _assert_inside_the_limits(sent)
    assert [row["unique_identifier"] for row in result["rows"]] == [
        row["unique_identifier"] for row in values
    ]


def test_one_row_over_the_limit_is_refused_before_anything_is_sent(sent, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_SQL_CHARACTERS", 100)

    with pytest.raises(ValueError, match="the limit is 100"):
        _upsert(_assets(1))

    assert sent == []


def test_the_keys_of_the_whole_list_are_checked_before_anything_is_sent(sent) -> None:
    values = [*_assets(12_000), {"unique_identifier": "A00007", "asset_type": "bond"}]

    with pytest.raises(ValueError, match="more than once"):
        _upsert(values)

    assert sent == []


def test_a_failed_statement_leaves_the_statements_before_it_sent(sent, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_SQL_CHARACTERS", 20_000)
    answer = crud.execute_markets_write

    def fail_on_the_third(write, *, context):
        if len(sent) == 2:
            raise RuntimeError("refused")
        return answer(write, context=context)

    monkeypatch.setattr(crud, "execute_markets_write", fail_on_the_third)

    with pytest.raises(RuntimeError, match="refused"):
        _upsert(_assets(4000))

    assert len(sent) == 2


def test_the_builder_refuses_a_statement_over_the_limit(offline_postgresql_runtime) -> None:
    with pytest.raises(ValueError, match=r"the limit is 1,000,000\. bulk_upsert_model"):
        build_bulk_upsert_model_operation(
            MarketsRepositoryContext(),
            model=AssetTable,
            values=_assets(6000),
            conflict_columns=KEY,
        )


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    return make_sqlite_markets(tmp_path, monkeypatch, prepare=_refuse_identical_rewrites)


def _stored(markets, asset_type: str) -> int:
    with markets.engine.connect() as connection:
        return connection.exec_driver_sql(
            "SELECT count(*) FROM ms_markets__asset WHERE asset_type = ?", (asset_type,)
        ).scalar_one()


def test_a_long_list_is_upserted_on_sqlite(sqlite_markets) -> None:
    """7,000 rows bind more values than one SQLite statement takes: they go in two batches."""

    values = _assets(7000)
    _upsert([values[6999], values[5], values[3000]], sqlite_markets.context)
    sqlite_markets.statements.clear()
    values[5] = {**values[5], "asset_type": "bond"}

    result = _upsert(values, sqlite_markets.context)

    expected = {6999: "unchanged", 5: "updated", 3000: "unchanged"}
    assert _statuses(result) == [
        (row["unique_identifier"], expected.get(index, "inserted"))
        for index, row in enumerate(values)
    ]
    assert result["row_count"] == 7000
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 7000
    assert _stored(sqlite_markets, "bond") == 1
    # Each batch reads its statuses, then runs a guard, the upsert and the read of its rows.
    assert len(sqlite_markets.statements) == 8
    assert max(map(len, sqlite_markets.statements)) <= MAX_STATEMENT_SQL_CHARACTERS

    again = _upsert(values[6000:], sqlite_markets.context)

    assert {status for _identifier, status in _statuses(again)} == {"unchanged"}


def test_more_statements_than_one_transaction_holds_run_on_sqlite(sqlite_markets, monkeypatch) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_PARAMETERS", 200)
    values = _assets(2000)
    _upsert(values[100:103], sqlite_markets.context)
    sqlite_markets.statements.clear()

    result = _upsert(values, sqlite_markets.context)

    assert len(sqlite_markets.statements) / 4 > 32
    assert _statuses(result) == [
        (row["unique_identifier"], "unchanged" if 100 <= index < 103 else "inserted")
        for index, row in enumerate(values)
    ]
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 2000


def test_a_failure_keeps_the_batches_before_it_and_a_repeat_finishes(
    sqlite_markets, monkeypatch
) -> None:
    monkeypatch.setattr(crud, "MAX_STATEMENT_PARAMETERS", 200)
    values = _assets(120)
    run = MetaTable.execute_transaction
    transactions = []

    def fail_on_the_second(transaction, *, timeout=None):
        transactions.append(transaction)
        if len(transactions) == 2:
            raise RuntimeError("the database went away")
        return run(transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_transaction", fail_on_the_second)

    with pytest.raises(RuntimeError, match="went away"):
        _upsert(values, sqlite_markets.context)

    written = _count(sqlite_markets.engine, "ms_markets__asset")
    assert 0 < written < 120

    result = _upsert(values, sqlite_markets.context)

    assert [status for _identifier, status in _statuses(result)] == [
        *["unchanged"] * written,
        *["inserted"] * (120 - written),
    ]
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 120


def test_the_row_api_upserts_a_list_longer_than_one_statement(sqlite_markets, monkeypatch) -> None:
    from types import SimpleNamespace

    from msm.api.assets import Asset

    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=sqlite_markets.context),
    )
    monkeypatch.setattr(crud, "MAX_STATEMENT_PARAMETERS", 2000)
    values = _assets(1500)

    rows = Asset.upsert_many(values)

    assert [row.unique_identifier for row in rows] == [row["unique_identifier"] for row in values]
    assert len({row.uid for row in rows}) == 1500
    assert MAX_STATEMENT_PARAMETERS > 2000
