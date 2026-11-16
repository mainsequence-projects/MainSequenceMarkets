"""Give the signal and portfolio weights tables an index that leads with the series.

``SignalWeightsStorage`` and ``PortfolioWeightsStorage`` had one index, the unique
one, which leads with ``time_index``. A read of one series (one signal, one
portfolio) could not use it to skip the other series, and the last time of a
series that stopped publishing was found by walking the index backwards over
every later row. The new indexes are ``(signal_uid, time_index)`` and
``(portfolio_identifier, time_index)``. They are not unique and change no row.

Only the Markets-owned tables are migrated here. A provider adds the same index
to its own instances in a revision of its own.
"""

from alembic import op

revision: str = "0026"
down_revision: str = "0025"
branch_labels = None
depends_on = None

SIGNAL_WEIGHTS_TABLE = "ms_markets__signalweightsts"
PORTFOLIO_WEIGHTS_TABLE = "ms_markets__portfolioweightsts"
SIGNAL_SERIES_INDEX = "ix__ms_markets__signalweightsts__signal_uid__time_index"
PORTFOLIO_SERIES_INDEX = "ix__ms_markets__portfolioweightsts__portfolio_identi_f5e44268b1"


def upgrade() -> None:
    op.create_index(SIGNAL_SERIES_INDEX, SIGNAL_WEIGHTS_TABLE, ["signal_uid", "time_index"])
    op.create_index(
        PORTFOLIO_SERIES_INDEX, PORTFOLIO_WEIGHTS_TABLE, ["portfolio_identifier", "time_index"]
    )


def downgrade() -> None:
    op.drop_index(PORTFOLIO_SERIES_INDEX, table_name=PORTFOLIO_WEIGHTS_TABLE)
    op.drop_index(SIGNAL_SERIES_INDEX, table_name=SIGNAL_WEIGHTS_TABLE)
