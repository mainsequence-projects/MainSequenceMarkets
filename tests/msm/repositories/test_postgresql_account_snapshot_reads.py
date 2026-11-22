"""How PostgreSQL finds the asset names of the account snapshot reads.

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to run these tests; they are skipped
otherwise. The asset snapshots have no index that leads with the asset, so a lookup per
asset reads a whole index each time. PostgreSQL chooses one whenever it expects few
assets, as it does on tables without statistics, so both are tested.
"""

from __future__ import annotations

import json

import pytest

from metatables.api.backend.backends.restricted_sql import parameters_for
from msm.time_index.assets.storage import AssetSnapshotsStorage
from tests.support.account_snapshots import account_read_operations, seed_account_snapshots

SNAPSHOTS = AssetSnapshotsStorage.__table__.name


@pytest.mark.parametrize("held", [200, 0], ids=["assets held", "nothing held"])
@pytest.mark.parametrize("analyzed", [False, True], ids=["no statistics", "analyzed"])
def test_the_asset_snapshots_are_not_scanned_once_per_asset(
    postgresql_markets, monkeypatch, analyzed, held
) -> None:
    engine, context, _operations = postgresql_markets
    with engine.begin() as connection:
        for (table,) in connection.exec_driver_sql(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).all():
            connection.exec_driver_sql(f'ALTER TABLE "{table}" SET (autovacuum_enabled = false)')
    account = seed_account_snapshots(engine, held=held, other_snapshots=20_000)
    if analyzed:
        with engine.begin() as connection:
            connection.exec_driver_sql("ANALYZE")

    for operation in account_read_operations(monkeypatch, context, account):
        # A probe by the whole key (time and asset) is cheap and may repeat; any other
        # read of the snapshots runs once, parallel workers aside, and not without assets.
        runs = [
            scan["Actual Loops"]
            for scan in _snapshot_scans(_executed_plan(engine, operation))
            if "time_index =" not in scan.get("Index Cond", "")
        ]
        assert all(loops <= (5 if held else 0) for loops in runs), runs


def test_a_full_page_of_assets_is_hashed_within_a_small_work_mem(
    postgresql_markets, monkeypatch
) -> None:
    # Not hashed, the membership test compares each snapshot with each of the page's assets.
    engine, context, _operations = postgresql_markets
    account = seed_account_snapshots(engine, held=10_000, other_snapshots=2_000)
    with engine.begin() as connection:
        connection.exec_driver_sql("ANALYZE")

    for operation in account_read_operations(monkeypatch, context, account):
        assert "hashed SubPlan" in json.dumps(_executed_plan(engine, operation, work_mem="1MB"))


def _executed_plan(engine, operation, *, work_mem: str | None = None) -> dict:
    statement = operation.statement
    values = parameters_for(statement.parameters, statement.parameter_types, "postgresql")
    with engine.connect() as connection:
        if work_mem:
            connection.exec_driver_sql(f"SET LOCAL work_mem = '{work_mem}'")
        explained = connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, TIMING OFF, FORMAT JSON) {statement.sql}", values or {}
        ).scalar_one()
    return explained[0]["Plan"]


def _snapshot_scans(node: dict):
    if node.get("Relation Name") == SNAPSHOTS:
        yield node
    for child in node.get("Plans", ()):
        yield from _snapshot_scans(child)
