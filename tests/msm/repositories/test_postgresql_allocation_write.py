"""A large allocation is one PostgreSQL statement inside MetaTables' request limits.

Set ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` to run this test; it is skipped
otherwise. MetaTables refuses a statement over 1,000,000 characters or a request over
12,100,000 bytes, and PostgreSQL takes at most 65,535 parameters. A value bound for each
column of each row passed the first between 500 and 600 assets in two funds.
"""

from __future__ import annotations

import datetime as dt
import uuid

import sqlalchemy as sa

from msm.models import AssetTable, VirtualFundTable
from msm.repositories.virtual_funds import (
    build_write_account_virtual_fund_allocation_operation,
    write_account_virtual_fund_allocation,
)
from msm.time_index.accounts.virtual_funds.storage import (
    AccountAllocationLinesStorage,
    VirtualFundHoldingsStorage,
)
from tests.support.account_snapshots import WHEN, seed_account_snapshots

ASSETS = 2_500


def test_a_large_allocation_is_written_whole_and_exactly(postgresql_markets) -> None:
    engine, context, _operations = postgresql_markets
    account = seed_account_snapshots(engine, held=1)
    when = WHEN + dt.timedelta(days=1)
    source = uuid.uuid4()
    names = ["held-0", "Ç '%:x\"\\", *(f"asset-{index}" for index in range(ASSETS - 2))]
    with engine.begin() as connection:
        connection.execute(
            AssetTable.__table__.insert(),
            [{"uid": uuid.uuid4(), "unique_identifier": name} for name in names[1:]],
        )
        connection.exec_driver_sql(
            "INSERT INTO ms_markets__accountholdingsset (uid, account_uid, time_index) "
            "VALUES (%s, %s, %s)",
            (source, account, when),
        )
        fund = connection.execute(
            sa.select(
                VirtualFundTable.__table__.c.unique_identifier,
                VirtualFundTable.__table__.c.target_portfolio_uid,
                VirtualFundTable.__table__.c.uid,
            )
        ).one()
        allocation = connection.execute(
            sa.select(VirtualFundTable.__table__.c.account_target_allocation_uid)
        ).scalar_one()
        second_portfolio = uuid.uuid4()
        connection.exec_driver_sql(
            "INSERT INTO ms_markets__portfolio "
            "SELECT (jsonb_populate_record(p, jsonb_build_object("
            "'uid', %s::text, 'unique_identifier', 'second'))).* FROM ms_markets__portfolio p",
            (str(second_portfolio),),
        )

    details = {"plan_digest": "sha256:x", "note": "Ç '%:x\"\\", "nested": {"n": [1, None]}}
    quantity = 0.1 + 0.2
    funds = [
        {
            "unique_identifier": name,
            "account_target_allocation_uid": str(allocation),
            "target_portfolio_uid": str(portfolio),
            "virtual_fund_uid": str(uid),
            "holdings_set_uid": str(uuid.uuid4()),
            "holdings": [
                {
                    "asset_identifier": asset,
                    "allocated_quantity": quantity,
                    "allocation_strategy": "proportional_attribution",
                    "direction": -1,
                    "extra_details": details,
                }
                for asset in names
            ],
        }
        for name, portfolio, uid in (
            tuple(fund),
            ("second-fund", second_portfolio, uuid.uuid4()),
        )
    ]
    lines = [
        {
            "owner_type": "fund",
            "fund_unique_identifier": written["unique_identifier"],
            "asset_identifier": asset,
            "target_quantity": 1 / 3,
            "target_direction": 1,
            "assigned_quantity": quantity,
            "assigned_direction": -1,
            "allocation_strategy": "proportional_attribution",
            "extra_details": details,
        }
        for written in funds
        for asset in names
    ]
    write = {
        "account_uid": account,
        "source_account_holdings_set_uid": source,
        "allocation_time": when,
        "funds": funds,
        "lines": lines,
    }

    operation = build_write_account_virtual_fund_allocation_operation(context, **write)

    assert len(operation.statement.sql) < 1_000_000
    assert len(operation.statement.parameters) < 65_535
    assert len(operation.model_dump_json().encode()) < 12_100_000

    assert write_account_virtual_fund_allocation(context, **write)["rows"]

    holdings = VirtualFundHoldingsStorage.__table__
    stored_lines = AccountAllocationLinesStorage.__table__
    with engine.connect() as connection:
        held = connection.execute(
            holdings.select().where(holdings.c.source_account_holdings_set_uid == source)
        ).all()
        recorded = connection.execute(stored_lines.select()).all()
        # The new fund names its allocation, as the one the target write made does.
        fund_allocations = set(
            connection.execute(
                sa.select(VirtualFundTable.__table__.c.account_target_allocation_uid)
            ).scalars()
        )
    assert fund_allocations == {allocation}
    assert sorted(row.asset_identifier for row in held) == sorted(names * 2)
    assert {(row.allocated_quantity, row.direction) for row in held} == {(quantity, -1)}
    assert all(row.extra_details == details and row.time_index == when for row in held)
    assert sorted(row.asset_identifier for row in recorded) == sorted(names * 2)
    assert {(row.target_quantity, row.assigned_quantity) for row in recorded} == {
        (1 / 3, quantity)
    }
    assert {row.owner_uid for row in recorded} == {
        uuid.UUID(written["virtual_fund_uid"]) for written in funds
    }
    assert all(row.extra_details == details for row in recorded)
    # An applied allocation is account history: the same write again writes nothing.
    assert write_account_virtual_fund_allocation(context, **write)["rows"] == []
