"""Bound, scoped inserts and reads of already registered tutorial tables."""

from uuid import UUID

from sqlalchemy import MetaData

from metatables import MetaTable, TimeIndexTableRef
from metatables.compiled_sql.v1 import compile_sqlalchemy_statement
from metatables.compiled_sql.v1 import dialect_insert as insert

from .frames import START
from .tables import ASSET_IDENTIFIER, RETURN_IDENTIFIER, VOLATILITY_IDENTIFIER, Asset

INSTRUMENTS = (
    {
        "uid": UUID("00000000-0000-4000-8000-000000000101"),
        "symbol": "SPY",
        "name": "SPDR S&P 500 ETF Trust",
    },
    {
        "uid": UUID("00000000-0000-4000-8000-000000000102"),
        "symbol": "QQQ",
        "name": "Invesco QQQ Trust",
    },
    {
        "uid": UUID("00000000-0000-4000-8000-000000000103"),
        "symbol": "IWM",
        "name": "iShares Russell 2000 ETF",
    },
)


def seed_operation(resource: MetaTable, *, dialect=None):
    # Use the catalog's physical binding, quoted by SQLAlchemy, for execution.
    table = Asset.__table__.to_metadata(
        MetaData(),
        schema=resource.physical_schema,
        name=resource.physical_table_name,
    )
    statement = insert(table, dialect=dialect).values(list(INSTRUMENTS))
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.symbol],
        set_={"name": statement.excluded.name},
    ).returning(table.c.uid, table.c.symbol, table.c.name)
    return compile_sqlalchemy_statement(
        statement,
        operation="insert", dialect=dialect,
        data_source_uid=str(resource.data_source_uid),
        limits={"max_rows": 3, "statement_timeout_ms": 15000},
    )


def seed_assets():
    resource = MetaTable.get(identifier=ASSET_IDENTIFIER)
    result = MetaTable.execute_operation(seed_operation(resource))
    rows = result.get("rows", [])
    if len(rows) != 3:
        raise RuntimeError("Expected three instrument rows from the seed operation.")
    return rows


def read_returns(symbol: str = "SPY"):
    return TimeIndexTableRef.from_identifier(RETURN_IDENTIFIER).get_df_between_dates(
        start_date=START,
        dimension_filters={"symbol": [symbol]},
        columns=["daily_return"],
    )


def read_volatility(symbol: str = "SPY"):
    return TimeIndexTableRef.from_identifier(VOLATILITY_IDENTIFIER).get_df_between_dates(
        start_date=START,
        dimension_filters={"symbol": [symbol]},
        columns=["annualized_volatility"],
    )
