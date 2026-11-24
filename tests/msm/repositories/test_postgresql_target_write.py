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


def _admitted_by_metatables(monkeypatch) -> list[int]:
    """Validate each request with MetaTables' own request models, as its route does."""

    import json

    from metatables.api.app.routes.table_sql import CompiledOperation, CompiledTransaction

    sizes: list[int] = []
    operation, transaction = MetaTable.execute_operation, MetaTable.execute_transaction

    def admitted(model, value):
        body = value.model_dump(mode="json", by_alias=True, exclude_none=True)
        model.model_validate(body)  # refuses a statement over 1,000,000 characters
        sizes.append(len(json.dumps(body, separators=(",", ":")).encode()))
        assert sizes[-1] <= 12_100_000

    def op(cls, value, *, timeout=None):
        admitted(CompiledOperation, value)
        return operation(value, timeout=timeout)

    def tx(cls, value, *, timeout=None):
        admitted(CompiledTransaction, value)
        return transaction(value, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(op))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(tx))
    return sizes


@pytest.mark.parametrize("write", ["holdings", "target"])
def test_ten_thousand_positions_are_written_within_metatables_limits(
    postgresql_markets, monkeypatch, write
) -> None:
    # #112: a value bound per column and row passed 1,000,000 characters of SQL at 3,952
    # holdings and 2,846 asset targets.
    import uuid

    from msm.services import add_account_holdings_snapshot_response
    from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage

    engine, context, _operations = postgresql_markets
    account = str(seed_account_snapshots(engine, held=0))
    assets = [(uuid.uuid4(), f"A{index:05d}") for index in range(10_000)]
    with engine.begin() as connection:
        connection.execute(
            AssetTable.__table__.insert(), [{"uid": uid, "unique_identifier": name} for uid, name in assets]
        )
    _admitted_by_metatables(monkeypatch)
    when = WHEN + dt.timedelta(days=1)

    if write == "holdings":
        answer = add_account_holdings_snapshot_response(
            context,
            account_uid=account,
            holdings_date=when,
            positions=[
                {"asset_identifier": name, "quantity": index + 0.125, "direction": -1 if index % 2 else 1,
                 "extra_details": {"lot": index}}
                for index, (_uid, name) in enumerate(assets)
            ],
            include_asset_detail=False,
        )
        assert len(answer["holdings"]) == 10_000
        with engine.connect() as connection:
            stored = connection.execute(
                sa.select(AccountHoldingsStorage.__table__).where(AccountHoldingsStorage.time_index == when)
            ).mappings().all()
        assert len(stored) == 10_000
        sample = {row["asset_identifier"]: row for row in stored}["A00007"]
        assert (sample["quantity"], sample["direction"], sample["extra_details"]) == (7.125, -1, {"lot": 7})
        assert sample["target_trade_time"] == when
    else:
        answer = add_account_target_positions_snapshot_response(
            context,
            account_uid=account,
            target_positions_date=when,
            positions=[
                {"target_type": "asset", "target_uid": str(uid), "asset_uid": str(uid),
                 "single_asset_quantity": index + 0.5}
                for index, (uid, _name) in enumerate(assets)
            ],
            include_asset_detail=False,
        )
        assert len(answer["positions"]) == 10_000
        with engine.connect() as connection:
            stored = connection.execute(
                sa.select(TargetPositionsStorage.__table__).where(TargetPositionsStorage.time_index == when)
            ).mappings().all()
        assert len(stored) == 10_000
        sample = {row["asset_uid"]: row for row in stored}[assets[7][0]]
        assert sample["single_asset_quantity"] == 7.5
        assert sample["portfolio_uid"] is None and sample["weight_notional_exposure"] is None
