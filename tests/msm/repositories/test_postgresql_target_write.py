"""The target write's transaction on PostgreSQL: a guarded statement, then its read.

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to run these tests; they are skipped
otherwise. SQLite writes the target as a list of statements, so only PostgreSQL runs this
guard, and only its locks say which tables MetaTables rebuilds statistics for.
"""

from __future__ import annotations

import datetime as dt

import pytest
import sqlalchemy as sa

from metatables import MetaTable
from metatables.api.backend.backends.postgresql_access import WRITTEN_RELATIONS
from metatables.api.backend.backends.restricted_sql import parameters_for
from msm.models import AccountTargetAllocationTable, AssetTable
from msm.services import (
    add_account_target_positions_snapshot_response,
    get_account_target_positions_snapshot_response,
)
from msm.services.target_positions import AccountTargetPositionsSnapshotExistsError
from msm.time_index.assets.storage import AssetSnapshotsStorage
from tests.support.account_snapshots import WHEN, seed_account_snapshots


def _position(engine):
    with engine.connect() as connection:
        asset = str(connection.execute(sa.select(AssetTable.__table__.c.uid)).scalars().first())
    return {
        "target_type": "asset",
        "target_uid": asset,
        "asset_uid": asset,
        "single_asset_quantity": 2,
    }


def test_a_target_write_reads_back_and_a_refused_one_changes_nothing(postgresql_markets) -> None:
    engine, context, operations = postgresql_markets
    account = str(seed_account_snapshots(engine, held=3))
    position, when = _position(engine), WHEN + dt.timedelta(days=1)

    def write():
        return add_account_target_positions_snapshot_response(
            context, account_uid=account, target_positions_date=when, positions=[position]
        )

    operations.clear()
    written = write()
    assert operations == ["read", "transaction"]
    assert written == get_account_target_positions_snapshot_response(context, account_uid=account)

    allocation = AccountTargetAllocationTable.__table__
    with engine.begin() as connection:
        connection.execute(allocation.update().values(display_name="Unchanged by a refusal"))
        before = connection.execute(sa.select(allocation)).all()
    with pytest.raises(AccountTargetPositionsSnapshotExistsError):
        write()
    with engine.connect() as connection:
        assert connection.execute(sa.select(allocation)).all() == before


def test_the_read_back_does_not_count_as_a_write_of_the_tables_it_reads(
    postgresql_markets, monkeypatch
) -> None:
    # MetaTables rebuilds the statistics of each time-index table it finds written, and
    # the asset snapshots are the large table this read touches.
    engine, context, _operations = postgresql_markets
    account = str(seed_account_snapshots(engine, held=3))
    sent = []
    execute = MetaTable.execute_transaction

    def kept(cls, transaction, *, timeout=None):
        sent.append(transaction)
        return execute(transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(kept))
    add_account_target_positions_snapshot_response(
        context,
        account_uid=account,
        target_positions_date=WHEN + dt.timedelta(days=1),
        positions=[_position(engine)],
        overwrite=True,
    )

    (transaction,) = sent
    with engine.connect() as connection:
        for statement in transaction.statements:
            values = parameters_for(statement.parameters, statement.parameter_types, "postgresql")
            connection.exec_driver_sql(statement.sql, values or {}).close()
        written = {name for _schema, name in connection.exec_driver_sql(WRITTEN_RELATIONS)}
        connection.rollback()

    assert AssetSnapshotsStorage.__table__.name not in written
    assert "ms_markets__targetpositionsts" in written
