"""An account with holdings, a target and funds, for the tests of the account snapshot reads.

`seed_account_snapshots` writes the rows directly, on SQLite or PostgreSQL alike, so a
test can have hundreds of funds or thousands of asset snapshots. `account_read_operations`
runs the reads and keeps what each sent to MetaTables, for a test to look at its cost.
"""

from __future__ import annotations

import datetime as dt
import uuid

from metatables import MetaTable
from msm.models import (
    AccountAllocationModelTable,
    AccountHoldingsSetTable,
    AccountTable,
    AccountTargetAllocationTable,
    AssetTable,
    CalendarTable,
    PortfolioTable,
    PositionSetTable,
    VirtualFundHoldingsSetTable,
    VirtualFundTable,
)
from msm.services import get_account_target_positions_snapshot_response
from msm.services.accounts import (
    get_account_holdings_by_fund_response,
    get_account_holdings_snapshot_response,
)
from msm.time_index.accounts.storage import AccountHoldingsStorage, TargetPositionsStorage
from msm.time_index.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.time_index.assets.storage import AssetSnapshotsStorage

WHEN = dt.datetime(2026, 11, 10, 15, 30, tzinfo=dt.UTC)


def seed_account_snapshots(
    engine,
    *,
    held: int,
    holders: int = 1,
    idle: int = 0,
    set_only: int = 0,
    other_snapshots: int = 0,
) -> uuid.UUID:
    """An account holding ``held`` assets at `WHEN`, each split among ``holders`` funds.

    Before those funds it has ``idle`` funds with nothing and ``set_only`` funds with a
    holdings set and no row. Its target names the held assets, or one portfolio when it
    holds none. With no holder it holds one unit of each asset, in no fund. Each held
    asset has one old snapshot; other assets have
    ``other_snapshots`` newer ones between them.
    """

    def insert(model, rows) -> None:
        if rows:
            with engine.begin() as connection:
                connection.execute(model.__table__.insert(), rows)

    account, model, allocation, source, position_set, calendar = (uuid.uuid4() for _ in range(6))
    assets = [(uuid.uuid4(), f"held-{index}") for index in range(held)]
    others = [(uuid.uuid4(), f"other-{index}") for index in range(50 if other_snapshots else 0)]
    funds = [(uuid.uuid4(), uuid.uuid4()) for _ in range(idle + set_only + holders)]
    fund_sets = [(fund, uuid.uuid4()) for fund, _portfolio in funds[idle:]]

    insert(AssetTable, [{"uid": uid, "unique_identifier": name} for uid, name in assets + others])
    insert(
        AssetSnapshotsStorage,
        [
            {
                "time_index": WHEN - dt.timedelta(days=700),
                "asset_identifier": name,
                "name": f"Name of {name}",
                "ticker": name,
            }
            for _uid, name in assets
        ]
        + [
            {
                "time_index": WHEN - dt.timedelta(days=600) + dt.timedelta(minutes=index),
                "asset_identifier": others[index % len(others)][1],
                "name": "Other",
                "ticker": "OTHER",
            }
            for index in range(other_snapshots)
        ],
    )
    insert(
        CalendarTable,
        [
            {
                "uid": calendar,
                "unique_identifier": "calendar",
                "display_name": "Calendar",
                "calendar_type": "exchange",
                "timezone": "UTC",
            }
        ],
    )
    insert(
        PortfolioTable,
        [
            {
                "uid": portfolio,
                "unique_identifier": f"portfolio-{index}",
                "calendar_uid": calendar,
                "backtest_table_price_column_name": "close",
            }
            for index, (_fund, portfolio) in enumerate(funds)
        ],
    )
    insert(
        AccountTable,
        [
            {
                "uid": account,
                "unique_identifier": "account",
                "account_name": "Account",
                "is_paper": True,
                "account_is_active": True,
            }
        ],
    )
    insert(AccountAllocationModelTable, [{"uid": model, "allocation_model_name": "Model"}])
    insert(
        AccountTargetAllocationTable,
        [
            {
                "uid": allocation,
                "unique_identifier": str(account),
                "account_uid": account,
                "account_allocation_model_uid": model,
                "is_active": True,
            }
        ],
    )
    insert(
        AccountHoldingsSetTable,
        [{"uid": source, "account_uid": account, "time_index": WHEN}],
    )
    insert(
        AccountHoldingsStorage,
        [
            {
                "time_index": WHEN,
                "account_uid": account,
                "asset_identifier": name,
                "holdings_set_uid": source,
                "quantity": float(max(holders, 1)),
                "direction": 1,
            }
            for _uid, name in assets
        ],
    )
    insert(
        VirtualFundTable,
        [
            {
                "uid": fund,
                "unique_identifier": f"fund-{index}",
                "account_uid": account,
                "account_target_allocation_uid": allocation,
                "target_portfolio_uid": portfolio,
            }
            for index, (fund, portfolio) in enumerate(funds)
        ],
    )
    insert(
        VirtualFundHoldingsSetTable,
        [
            {
                "uid": fund_set,
                "virtual_fund_uid": fund,
                "source_account_holdings_set_uid": source,
                "time_index": WHEN,
            }
            for fund, fund_set in fund_sets
        ],
    )
    insert(
        VirtualFundHoldingsStorage,
        [
            {
                "time_index": WHEN,
                "virtual_fund_uid": fund,
                "asset_identifier": name,
                "virtual_fund_holdings_set_uid": fund_set,
                "source_account_holdings_set_uid": source,
                "allocated_quantity": 1.0,
                "allocation_strategy": "proportional_attribution",
                "direction": 1,
            }
            for fund, fund_set in fund_sets[set_only:]
            for _uid, name in assets
        ],
    )
    insert(
        PositionSetTable,
        [
            {
                "uid": position_set,
                "account_target_allocation_uid": allocation,
                "position_set_time": WHEN,
            }
        ],
    )
    position = {"time_index": WHEN, "position_set_uid": position_set}
    insert(
        TargetPositionsStorage,
        [
            {
                **position,
                "target_type": "asset",
                "target_uid": uid,
                "asset_uid": uid,
                "single_asset_quantity": 1.0,
            }
            for uid, _name in assets
        ]
        or [
            {
                **position,
                "target_type": "portfolio",
                "target_uid": funds[-1][1],
                "portfolio_uid": funds[-1][1],
                "weight_notional_exposure": 1.0,
            }
        ],
    )
    return account


def account_read_operations(monkeypatch, context, account: uuid.UUID) -> list:
    """What the target, holdings and holdings-by-fund reads send: four statements."""

    execute, sent = MetaTable.execute_operation, []

    def kept(cls, operation, *, timeout=None):
        sent.append(operation)
        return execute(operation, timeout=timeout)

    with monkeypatch.context() as patch:
        patch.setattr(MetaTable, "execute_operation", classmethod(kept))
        for read in (
            get_account_target_positions_snapshot_response,
            get_account_holdings_snapshot_response,
            get_account_holdings_by_fund_response,
        ):
            read(context, account_uid=str(account))
    assert len(sent) == 4
    return sent
