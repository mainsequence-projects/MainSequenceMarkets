"""Give the six other portfolio datasets an index that leads with the portfolio (issue 96).

Revision 0026 gave the portfolio weights table an index on ``(portfolio_identifier,
time_index)``. The six other datasets keyed by ``portfolio_identifier`` (values,
rebalance state, analytics, event ledger, state and cash flows) kept only their unique
index, which leads with ``time_index``. Counting, reading or deleting one portfolio's
rows there read the whole table, and so did the ``RESTRICT`` check that runs when a
portfolio row is deleted. Each gets the same index as the weights table. The indexes are
not unique and change no row.

Only the Markets-owned tables are migrated here. A provider adds the same index to its
own instances in a revision of its own.

On an ordinary table the index is built inside the upgrade's transaction, as 0026 built
its own: it holds a ``SHARE`` lock on the table until the upgrade commits, so writes to the
table wait and reads do not.

A TimescaleDB DataSource makes these tables hypertables. Built in one transaction, an
index on a hypertable takes about two locks per chunk until the transaction ends, so a
table with thousands of chunks ran out of shared memory at PostgreSQL's default
``max_locks_per_transaction``. On a hypertable the index is therefore built with
``timescaledb.transaction_per_chunk``, outside the upgrade's transaction: one chunk per
transaction, holding a few locks at a time whatever the number of chunks, and writes wait
only on the chunk being indexed. A build that stops part way leaves the hypertable's index
invalid with some chunks indexed; the next upgrade drops those chunk indexes one at a
time, then the invalid index, and builds again. The downgrade drops a hypertable's chunk
indexes one at a time too. Dropping the hypertable's own index is still one transaction:
TimescaleDB 2.22 opens every chunk of the table and its indexes to drop it, about two
locks per chunk, so the chunk indexes go first and that drop only reads the chunks. ADR
0049's 4.1.0, issue 96 note has the measurements.
"""

from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa

revision: str = "0031"
down_revision: str = "0030"
branch_labels = None
depends_on = None

SERIES_COLUMNS = ["portfolio_identifier", "time_index"]
SERIES_INDEXES = {
    "ms_markets__portfoliosts": "ix__ms_markets__portfoliosts__portfolio_identifier__time_index",
    "ms_markets__portfoliorebalancestatets": "ix__ms_markets__portfoliorebalancestatets__portfolio_fbb9c4f661",
    "ms_markets__portfolioanalyticsts": "ix__ms_markets__portfolioanalyticsts__portfolio_iden_611b20844a",
    "ms_markets__portfolioeventledgerts": "ix__ms_markets__portfolioeventledgerts__portfolio_id_49b51173d6",
    "ms_markets__portfoliostatets": "ix__ms_markets__portfoliostatets__portfolio_identifi_9a38a1d6c2",
    "ms_markets__portfoliocashflowsts": "ix__ms_markets__portfoliocashflowsts__portfolio_iden_41ed9a24ea",
}

# The indexes on the table's chunks with exactly the series columns: what a build of the
# series index on the hypertable creates, chunk by chunk.
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
    bind = op.get_bind()
    hypertables = _hypertables(bind)
    for table, index in SERIES_INDEXES.items():
        if table not in hypertables:
            op.create_index(index, table, SERIES_COLUMNS, if_not_exists=True)
    if hypertables:
        with op.get_context().autocommit_block(), _without_statement_timeout():
            for table in hypertables:
                _build_hypertable_index(table, SERIES_INDEXES[table])


def downgrade() -> None:
    bind = op.get_bind()
    hypertables = _hypertables(bind)
    if hypertables:
        with op.get_context().autocommit_block(), _without_statement_timeout():
            for table in reversed(hypertables):
                _drop_hypertable_index(table, SERIES_INDEXES[table])
    for table, index in reversed(SERIES_INDEXES.items()):
        if table not in hypertables:
            op.drop_index(index, table_name=table, if_exists=True)


def _hypertables(bind) -> list[str]:
    """The tables of `SERIES_INDEXES` that are TimescaleDB hypertables, in that order."""

    if bind.dialect.name != "postgresql":
        return []
    if bind.execute(sa.text("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")).first() is None:
        return []
    names = set(
        bind.execute(
            sa.text(
                "SELECT hypertable_name FROM timescaledb_information.hypertables "
                "WHERE hypertable_schema = current_schema()"
            )
        ).scalars()
    )
    return [table for table in SERIES_INDEXES if table in names]


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

    return op.get_bind().execute(
        sa.text(
            "SELECT index_state.indisvalid FROM pg_index AS index_state "
            "JOIN pg_class AS index_class ON index_class.oid = index_state.indexrelid "
            "WHERE index_class.relname = :index AND index_state.indrelid = CAST(:table AS regclass)"
        ),
        {"index": index, "table": table},
    ).scalar()


def _build_hypertable_index(table: str, index: str) -> None:
    """Build the index chunk by chunk, after clearing what an interrupted build left."""

    if _index_valid(table, index):
        return
    _drop_hypertable_index(table, index)
    op.execute(
        f'CREATE INDEX "{index}" ON "{table}" ({", ".join(SERIES_COLUMNS)}) '
        "WITH (timescaledb.transaction_per_chunk)"
    )


def _drop_hypertable_index(table: str, index: str) -> None:
    """Drop the chunks' series indexes one per transaction, then the hypertable's."""

    bind = op.get_bind()
    for chunk_index in bind.execute(_CHUNK_INDEXES, {"table": table, "columns": SERIES_COLUMNS}).scalars().all():
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {chunk_index}"))
    op.execute(f'DROP INDEX IF EXISTS "{index}"')
