"""Portfolio dataset rows on the disposable PostgreSQL database, and how PostgreSQL reads them.

For the PostgreSQL tests of the portfolio and account deletes, on the
`postgresql_markets` fixture (`tests/support/postgresql_markets.py`).
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa

from msm_portfolios.time_index.portfolios.storage import PORTFOLIO_DATASET_TABLES
from tests.support.postgresql_markets import _insert  # noqa: F401  (the portfolio tests' helper)

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)
DATASETS = {table.key: table.table_name for table in PORTFOLIO_DATASET_TABLES}


def _portfolio(engine) -> tuple[uuid.UUID, str]:
    calendar = _insert(engine, "ms_markets__calendar")
    portfolio = uuid.uuid4()
    identifier = f"portfolio-{portfolio.hex[:8]}"
    _insert(
        engine,
        "ms_markets__portfolio",
        uid=portfolio,
        unique_identifier=identifier,
        calendar_uid=calendar["uid"],
        retired_at=None,
    )
    return portfolio, identifier


def _datasets(engine, identifier: str) -> None:
    for table_name in DATASETS.values():
        assets = {
            foreign_key["constrained_columns"][0]: "AAA"
            for foreign_key in sa.inspect(engine).get_foreign_keys(table_name)
            if foreign_key["referred_table"] == "ms_markets__asset"
        }
        _insert(engine, table_name, time_index=WHEN, portfolio_identifier=identifier, **assets)


def _rows_in(engine, identifier: str, **rows: int) -> None:
    """``rows[key]`` rows of the portfolio in dataset ``key``, one a day."""

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


def explain(engine, operation) -> list:
    """PostgreSQL's plan for a compiled read with sequential scans priced out (``FORMAT JSON``).

    The read is bound as MetaTables binds it. With ``enable_seqscan`` off the planner
    takes any usable index even on the tests' few rows, so the plan shows whether one
    exists for the read's conditions.
    """

    from metatables.api.backend.backends.restricted_sql import parameters_for

    statement = operation.statement
    values = parameters_for(statement.parameters, statement.parameter_types, "postgresql")
    with engine.connect() as connection:
        connection.exec_driver_sql("SET enable_seqscan = off")
        return connection.exec_driver_sql(f"EXPLAIN (FORMAT JSON) {statement.sql}", values).scalar_one()


def dataset_reads(plan: list) -> dict[str, list[str]]:
    """How the plan reads each dataset table: per plan node that reads it, the index it uses.

    ``None`` stands for a node that reads the table without an index.
    """

    reads: dict[str, list[str]] = {table_name: [] for table_name in DATASETS.values()}

    def visit(node: dict) -> None:
        if node.get("Relation Name") in reads:
            index = node.get("Index Name") or next(
                (
                    child.get("Index Name")
                    for child in node.get("Plans", ())
                    if child.get("Node Type") == "Bitmap Index Scan"
                ),
                None,
            )
            reads[node["Relation Name"]].append(index)
        for child in node.get("Plans", ()):
            visit(child)

    visit(plan[0]["Plan"])
    return reads


def series_indexes() -> dict[str, list[str]]:
    """Per dataset table, its index that leads with ``portfolio_identifier``, once."""

    return {
        table.table_name: [index.name for index in table.model.__table__.indexes if not index.unique]
        for table in PORTFOLIO_DATASET_TABLES
    }


def _dataset_rows(engine, identifier: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            key: connection.execute(
                sa.text(f"SELECT count(*) FROM {table_name} WHERE portfolio_identifier = :identifier"),
                {"identifier": identifier},
            ).scalar_one()
            for key, table_name in DATASETS.items()
        }


def _count(engine, sql: str, **parameters) -> int:
    with engine.connect() as connection:
        return connection.execute(sa.text(sql), parameters).scalar_one()


def _exists(engine, portfolio: uuid.UUID) -> bool:
    return bool(_count(engine, "SELECT count(*) FROM ms_markets__portfolio WHERE uid = :uid", uid=portfolio))
