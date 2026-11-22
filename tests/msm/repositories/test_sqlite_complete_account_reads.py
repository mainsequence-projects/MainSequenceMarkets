"""An account snapshot is read whole, whatever its size.

The reads used to stop, without a word, at 500 rows, and the allocation's at MetaTables'
default of 1,000: the answers looked complete, and the allocation wrote from them.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
import sqlalchemy as sa

from metatables import MetaTable
from msm.models import (
    AccountHoldingsSetTable,
    AssetTable,
    PortfolioTable,
    PositionSetTable,
    VirtualFundTable,
)
from msm.repositories import complete_reads
from msm.repositories.virtual_funds import search_virtual_funds_by_unique_identifiers
from msm.services import (
    add_account_target_positions_snapshot_response,
    get_account_target_positions_snapshot_response,
    get_virtual_fund_holdings_snapshot_response,
)
from msm.services.accounts import (
    get_account_holdings_by_fund_response,
    get_account_holdings_snapshot_response,
)
from msm.services.accounts.account_virtual_allocations import (
    apply_account_virtual_fund_allocation_plan_in_context,
    get_account_allocation_record_in_context,
    plan_account_virtual_fund_allocations_in_context,
)
from msm.services.accounts.core import get_account_holdings_snapshots_response
from msm.services.accounts.virtual_fund_holdings import (
    build_virtual_fund_holdings_frame,
    validate_virtual_fund_allocation_bounds,
)
from msm.services.portfolio_lifecycle import retired_portfolios
from msm.time_index.accounts.storage import AccountHoldingsStorage
from tests.support.account_registration import _record_operations
from tests.support.account_snapshots import WHEN, seed_account_snapshots

SIZE = 1_101


def _values(engine, column) -> list:
    with engine.connect() as connection:
        return list(connection.execute(sa.select(column)).scalars())


def test_a_holdings_read_returns_every_holding(sqlite_markets) -> None:
    account = seed_account_snapshots(sqlite_markets.engine, held=SIZE)

    answer = get_account_holdings_snapshot_response(sqlite_markets.context, account_uid=str(account))

    assert {row["asset_identifier"] for row in answer["holdings"]} == {
        f"held-{index}" for index in range(SIZE)
    }
    assert len(answer["holdings"]) == SIZE
    assert all(row["asset"]["current_snapshot"]["name"] for row in answer["holdings"])


def test_a_target_read_returns_every_position(sqlite_markets) -> None:
    account = seed_account_snapshots(sqlite_markets.engine, held=SIZE)

    answer = get_account_target_positions_snapshot_response(
        sqlite_markets.context, account_uid=str(account)
    )

    assert len({row["target_uid"] for row in answer["positions"]}) == SIZE
    assert all(row["asset"]["current_snapshot"]["name"] for row in answer["positions"])


def test_a_target_write_answers_every_position_it_wrote(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = seed_account_snapshots(engine, held=SIZE)
    assets = _values(engine, AssetTable.__table__.c.uid)

    answer = add_account_target_positions_snapshot_response(
        sqlite_markets.context,
        account_uid=str(account),
        target_positions_date=WHEN + dt.timedelta(days=1),
        positions=[{"asset_uid": str(asset), "single_asset_quantity": 2} for asset in assets],
    )

    assert len(answer["positions"]) == SIZE


def test_holdings_by_fund_return_every_allocation_and_fund(sqlite_markets) -> None:
    account = seed_account_snapshots(sqlite_markets.engine, held=SIZE, holders=2, set_only=510)

    answer = get_account_holdings_by_fund_response(sqlite_markets.context, account_uid=str(account))

    allocated = sorted(len(group["holdings"]) for group in answer["funds"])
    assert allocated == [0] * 510 + [SIZE, SIZE]
    assert answer["residuals"] == []
    assert answer["allocation_warnings"] == []


def test_a_fund_holdings_read_returns_every_holding_with_its_name(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    seed_account_snapshots(engine, held=SIZE)
    (fund,) = _values(engine, VirtualFundTable.__table__.c.uid)

    answer = get_virtual_fund_holdings_snapshot_response(sqlite_markets.context, uid=str(fund))

    assert len(answer["holdings"]) == SIZE
    assert all(row["asset"]["current_snapshot"]["name"] for row in answer["holdings"])


def test_several_holdings_snapshots_are_each_whole(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    account = seed_account_snapshots(engine, held=700)
    times = [WHEN - dt.timedelta(days=day) for day in range(3)]
    for when in times[1:]:
        holdings_set = uuid.uuid4()
        with engine.begin() as connection:
            connection.execute(
                AccountHoldingsSetTable.__table__.insert(),
                {"uid": holdings_set, "account_uid": account, "time_index": when},
            )
            connection.execute(
                AccountHoldingsStorage.__table__.insert(),
                [
                    {
                        "time_index": when,
                        "account_uid": account,
                        "asset_identifier": f"held-{index}",
                        "holdings_set_uid": holdings_set,
                        "quantity": 1.0,
                        "direction": 1,
                    }
                    for index in range(700)
                ],
            )

    for kwargs in ({"limit": 3}, {"holdings_dates": times}):
        answer = get_account_holdings_snapshots_response(
            sqlite_markets.context, account_uid=str(account), **kwargs
        )

        assert [snapshot["holdings_date"] for snapshot in answer] == times
        for snapshot in answer:
            assert len({row["asset_identifier"] for row in snapshot["holdings"]}) == 700


def test_an_allocation_plans_writes_and_reads_back_every_line(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    context = sqlite_markets.context
    account = seed_account_snapshots(engine, held=SIZE, holders=0)
    (position_set,) = _values(engine, PositionSetTable.__table__.c.uid)

    plan = plan_account_virtual_fund_allocations_in_context(
        context, position_set_uid=position_set, valuation_time=WHEN, account_uid=account
    )

    assert len(plan.lines) == SIZE
    assert {(line.target, line.assigned) for line in plan.lines} == {(1.0, 1.0)}
    assert apply_account_virtual_fund_allocation_plan_in_context(context, plan).applied
    record = get_account_allocation_record_in_context(context, account_uid=account)
    assert len(record["lines"]) == SIZE
    assert apply_account_virtual_fund_allocation_plan_in_context(context, plan).already_applied


def test_the_bounds_check_counts_every_existing_allocation(sqlite_markets) -> None:
    # Four funds hold all 300 assets: a fifth allocation of any of them is one too many.
    engine = sqlite_markets.engine
    seed_account_snapshots(engine, held=300, holders=4)
    (source,) = _values(engine, AccountHoldingsSetTable.__table__.c.uid)
    frame = build_virtual_fund_holdings_frame(
        allocation_time=WHEN,
        virtual_fund_uid=uuid.uuid4(),
        source_account_holdings_set_uid=source,
        virtual_fund_holdings_set_uid=uuid.uuid4(),
        allocations=[
            {"asset_identifier": f"held-{index}", "allocated_quantity": 1.0}
            for index in range(300)
        ],
    )

    with pytest.raises(ValueError, match="exceeds source account holdings"):
        validate_virtual_fund_allocation_bounds(sqlite_markets.context, frame)


def test_the_allocation_guards_see_every_fund_and_portfolio(sqlite_markets) -> None:
    engine = sqlite_markets.engine
    context = sqlite_markets.context
    seed_account_snapshots(engine, held=0, idle=SIZE - 1)
    portfolios = PortfolioTable.__table__
    uids = _values(engine, portfolios.c.uid)
    with engine.begin() as connection:
        connection.execute(portfolios.update().values(retired_at=WHEN))

    assert len(retired_portfolios(context, uids)) == SIZE
    names = _values(engine, VirtualFundTable.__table__.c.unique_identifier)
    known = search_virtual_funds_by_unique_identifiers(context, unique_identifiers=names)
    assert len(known["rows"]) == SIZE


def test_a_snapshot_within_a_statement_costs_one_request(sqlite_markets, monkeypatch) -> None:
    account = seed_account_snapshots(sqlite_markets.engine, held=SIZE)
    operations = _record_operations(monkeypatch)

    get_account_holdings_snapshot_response(sqlite_markets.context, account_uid=str(account))

    assert operations == ["read"]


def test_a_snapshot_over_a_statements_rows_is_read_twice_in_pages(
    sqlite_markets, monkeypatch
) -> None:
    account = seed_account_snapshots(sqlite_markets.engine, held=10_100)
    operations = _record_operations(monkeypatch)

    answer = get_account_holdings_snapshot_response(
        sqlite_markets.context, account_uid=str(account), include_asset_detail=False
    )

    assert len({row["asset_identifier"] for row in answer["holdings"]}) == 10_100
    assert operations == ["read"] * 4


def test_a_snapshot_metatables_cuts_at_its_bytes_is_still_whole(sqlite_markets) -> None:
    # 1,200 rows of 8 KB are more than the 8 MiB of one answer.
    engine = sqlite_markets.engine
    account = seed_account_snapshots(engine, held=1_200)
    with engine.begin() as connection:
        connection.execute(
            AccountHoldingsStorage.__table__.update().values(extra_details={"note": "x" * 8_000})
        )

    answer = get_account_holdings_snapshot_response(
        sqlite_markets.context, account_uid=str(account), include_asset_detail=False
    )

    assert len({row["asset_identifier"] for row in answer["holdings"]}) == 1_200


def _change_after(monkeypatch, engine, change, *, every_request: bool) -> None:
    execute, requests = MetaTable.execute_operation, []

    def changed(cls, operation, *, timeout=None):
        result = execute(operation, timeout=timeout)
        requests.append(operation)
        if every_request or len(requests) == 1:
            with engine.begin() as connection:
                connection.execute(change(len(requests)))
        return result

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(changed))


@pytest.mark.parametrize("write", ["overwrite", "delete"])
def test_a_write_between_two_pages_never_mixes_two_snapshots(
    sqlite_markets, monkeypatch, write
) -> None:
    engine = sqlite_markets.engine
    account = seed_account_snapshots(engine, held=700)
    monkeypatch.setattr(complete_reads, "READ_PAGE_ROWS", 400)
    table = AccountHoldingsStorage.__table__
    change = (
        table.update().values(quantity=2.0)
        if write == "overwrite"
        else table.delete().where(table.c.asset_identifier == "held-0")
    )
    _change_after(monkeypatch, engine, lambda _request: change, every_request=False)

    answer = get_account_holdings_snapshot_response(
        sqlite_markets.context, account_uid=str(account), include_asset_detail=False
    )

    rows = answer["holdings"]
    if write == "overwrite":
        assert [row["quantity"] for row in rows] == ["2.0"] * 700
    else:
        assert len({row["asset_identifier"] for row in rows}) == len(rows) == 699


def test_a_snapshot_that_keeps_changing_is_refused_not_cut(sqlite_markets, monkeypatch) -> None:
    engine = sqlite_markets.engine
    account = seed_account_snapshots(engine, held=700)
    monkeypatch.setattr(complete_reads, "READ_PAGE_ROWS", 400)
    table = AccountHoldingsStorage.__table__
    _change_after(
        monkeypatch,
        engine,
        lambda request: table.update().values(quantity=float(request + 1)),
        every_request=True,
    )

    with pytest.raises(complete_reads.IncompleteReadError):
        get_account_holdings_snapshot_response(sqlite_markets.context, account_uid=str(account))


def test_an_empty_list_of_values_matches_nothing(sqlite_markets) -> None:
    # `search_model` drops an empty IN, which would read every account's rows.
    engine = sqlite_markets.engine
    context = sqlite_markets.context
    seed_account_snapshots(engine, held=2)

    funds = search_virtual_funds_by_unique_identifiers(context, unique_identifiers=[])
    holdings = complete_reads.read_every_model_row(
        context, model=AccountHoldingsStorage, in_filters={"holdings_set_uid": []}
    )

    assert funds["rows"] == holdings["rows"] == []
