"""Index the account history tables by the columns their foreign keys and owners use.

Holdings, allocation lines, virtual-fund holdings, orders, trades and order events kept
only their unique index, which leads with the time column. A foreign key whose column no
index leads with is checked by reading the whole referencing table, once per referenced
row deleted: deleting an account with 1,000 holdings sets read every holdings row 1,000
times, 6 of the delete's 6.1 seconds on 200,000 rows. One account's, one holdings set's or
one order's rows were also read through the whole table. Each table gets a non-unique
index on each such column, with the time column after an account's or an order's
identifier. The indexes change no row.

Only the Markets-owned tables are migrated here.

As in revision 0031, an index on an ordinary table is built inside the upgrade's
transaction: it holds a ``SHARE`` lock on the table until the upgrade commits, so writes
to the table wait and reads do not. On a TimescaleDB hypertable it is built with
``timescaledb.transaction_per_chunk``, outside the upgrade's transaction, one chunk per
transaction; an upgrade after an interrupted build drops the chunk indexes it left, then
the invalid index, and builds again. The downgrade drops a hypertable's chunk indexes one
at a time before the hypertable's own (see revision 0031).
"""

from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa

revision: str = "0034"
down_revision: str = "0033"
branch_labels = None
depends_on = None

INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ms_markets__accountholdingsts",
        "ix__ms_markets__accountholdingsts__account_uid__time_index",
        ("account_uid", "time_index"),
    ),
    (
        "ms_markets__accountholdingsts",
        "ix__ms_markets__accountholdingsts__holdings_set_uid",
        ("holdings_set_uid",),
    ),
    (
        "ms_markets__accountallocationlinests",
        "ix__ms_markets__accountallocationlinests__account_ui_a22e3b957c",
        ("account_uid", "time_index"),
    ),
    (
        "ms_markets__accountallocationlinests",
        "ix__ms_markets__accountallocationlinests__holdings_set_uid",
        ("holdings_set_uid",),
    ),
    (
        "ms_markets__accountallocationlinests",
        "ix__ms_markets__accountallocationlinests__virtual_fund_uid",
        ("virtual_fund_uid",),
    ),
    (
        "ms_markets__virtualfundholdingsts",
        "ix__ms_markets__virtualfundholdingsts__virtual_fund_d4a88a14c6",
        ("virtual_fund_uid", "source_account_holdings_set_uid"),
    ),
    (
        "ms_markets__virtualfundholdingsts",
        "ix__ms_markets__virtualfundholdingsts__source_accoun_3c343c4d79",
        ("source_account_holdings_set_uid",),
    ),
    (
        "ms_markets__virtualfundholdingsts",
        "ix__ms_markets__virtualfundholdingsts__virtual_fund_df413774a8",
        ("virtual_fund_holdings_set_uid",),
    ),
    (
        "ms_markets__ordersts",
        "ix__ms_markets__ordersts__account_identifier__order_time",
        ("account_identifier", "order_time"),
    ),
    (
        "ms_markets__ordersts",
        "ix__ms_markets__ordersts__order_manager_identifier",
        ("order_manager_identifier",),
    ),
    (
        "ms_markets__ordersts",
        "ix__ms_markets__ordersts__order_identifier",
        ("order_identifier",),
    ),
    (
        "ms_markets__tradests",
        "ix__ms_markets__tradests__account_identifier__trade_time",
        ("account_identifier", "trade_time"),
    ),
    (
        "ms_markets__ordereventsts",
        "ix__ms_markets__ordereventsts__order_identifier__event_time",
        ("order_identifier", "event_time"),
    ),
)

# The indexes on the table's chunks with exactly the given columns: what a build of the
# index on the hypertable creates, chunk by chunk.
_CHUNK_INDEXES = sa.text(
    """
    SELECT format('%I.%I', index_namespace.nspname, index_class.relname)
    FROM show_chunks(CAST(:table AS regclass)) AS chunk(relid)
    JOIN pg_index AS chunk_index ON chunk_index.indrelid = chunk.relid
    JOIN pg_class AS index_class ON index_class.oid = chunk_index.indexrelid
    JOIN pg_namespace AS index_namespace ON index_namespace.oid = index_class.relnamespace
    WHERE NOT chunk_index.indisunique
      AND ARRAY(
            SELECT attribute.attname::text
            FROM unnest(chunk_index.indkey::int2[]) WITH ORDINALITY AS key(attnum, position)
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = chunk_index.indrelid AND attribute.attnum = key.attnum
            ORDER BY key.position
          ) = CAST(:columns AS text[])
    """
)


def upgrade() -> None:
    hypertables = _hypertables(op.get_bind())
    for table, index, columns in INDEXES:
        if table not in hypertables:
            op.create_index(index, table, list(columns), if_not_exists=True)
    if hypertables:
        with op.get_context().autocommit_block(), _without_statement_timeout():
            for table, index, columns in INDEXES:
                if table in hypertables:
                    _build_hypertable_index(table, index, columns)


def downgrade() -> None:
    hypertables = _hypertables(op.get_bind())
    if hypertables:
        with op.get_context().autocommit_block(), _without_statement_timeout():
            for table, index, columns in reversed(INDEXES):
                if table in hypertables:
                    _drop_hypertable_index(table, index, columns)
    for table, index, _columns in reversed(INDEXES):
        if table not in hypertables:
            op.drop_index(index, table_name=table, if_exists=True)


def _hypertables(bind) -> set[str]:
    """The tables of `INDEXES` that are TimescaleDB hypertables."""

    if bind.dialect.name != "postgresql":
        return set()
    if (
        bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")).first()
        is None
    ):
        return set()
    names = set(
        bind.execute(
            sa.text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "WHERE hypertable_schema = current_schema()"
            )
        ).scalars()
    )
    return {table for table, _index, _columns in INDEXES if table in names}


@contextmanager
def _without_statement_timeout():
    """Let each build run as long as it takes, then restore the session's own timeout."""

    op.execute("SET statement_timeout = 0")
    try:
        yield
    finally:
        op.execute("RESET statement_timeout")


def _index_valid(table: str, index: str) -> bool | None:
    """Whether the hypertable's index is valid; ``None`` when it does not exist."""

    return (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT index_state.indisvalid FROM pg_index AS index_state "
                "JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid "
                "WHERE index_class.relname = :index AND index_state.indrelid = CAST(:table AS regclass)"
            ),
            {"index": index, "table": table},
        )
        .scalar()
    )


def _build_hypertable_index(table: str, index: str, columns: tuple[str, ...]) -> None:
    """Build the index chunk by chunk, after clearing what an interrupted build left."""

    if _index_valid(table, index):
        return
    _drop_hypertable_index(table, index, columns)
    op.execute(
        f'CREATE INDEX "{index}" ON "{table}" ({", ".join(columns)}) '
        "WITH (timescaledb.transaction_per_chunk)"
    )


def _drop_hypertable_index(table: str, index: str, columns: tuple[str, ...]) -> None:
    """Drop the chunks' indexes on ``columns`` one per transaction, then the hypertable's."""

    bind = op.get_bind()
    chunk_indexes = bind.execute(_CHUNK_INDEXES, {"table": table, "columns": list(columns)})
    for chunk_index in chunk_indexes.scalars().all():
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {chunk_index}"))
    op.execute(f'DROP INDEX IF EXISTS "{index}"')
