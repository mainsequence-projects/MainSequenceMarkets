from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from msm.api.base import MarketsMetaTableRow, MarketsRow
from msm.api.accounts import (
    Account,
    AccountGroup,
    AccountAllocationModel,
    AccountTargetAllocation,
    PositionSet,
    PositionSetUpsert,
)
from msm.api.assets import (
    AssetCategory,
    AssetCategoryMembership,
    AssetType,
    OpenFigiDetails,
)
from msm.api.calendars import Calendar, CalendarDate, CalendarEvent, CalendarSession
from msm.api.execution import OrderManager
from msm.api.indices import Index, IndexType
from msm.models import (
    AccountGroupTable,
    AccountAllocationModelTable,
    AccountTable,
    AccountTargetAllocationTable,
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTypeTable,
    CalendarDateTable,
    CalendarEventTable,
    CalendarSessionTable,
    CalendarTable,
    IndexTable,
    IndexTypeTable,
    OpenFigiAssetDetailsTable,
    OrderManagerTable,
    PositionSetTable,
)


@pytest.mark.parametrize(
    ("row_model", "table_model", "upsert_keys"),
    [
        (AssetType, AssetTypeTable, ("asset_type",)),
        (AssetCategory, AssetCategoryTable, ("unique_identifier",)),
        (AssetCategoryMembership, AssetCategoryMembershipTable, ("category_uid", "asset_uid")),
        (OpenFigiDetails, OpenFigiAssetDetailsTable, ("asset_uid",)),
        (Calendar, CalendarTable, ("unique_identifier",)),
        (CalendarDate, CalendarDateTable, ("calendar_uid", "local_date")),
        (
            CalendarSession,
            CalendarSessionTable,
            ("calendar_uid", "local_date", "session_label"),
        ),
        (
            CalendarEvent,
            CalendarEventTable,
            (
                "calendar_uid",
                "event_date",
                "event_type",
                "event_label",
                "target_type",
                "target_identifier",
            ),
        ),
        (AccountAllocationModel, AccountAllocationModelTable, ("allocation_model_name",)),
        (AccountGroup, AccountGroupTable, ("group_name",)),
        (Account, AccountTable, ("unique_identifier",)),
        (AccountTargetAllocation, AccountTargetAllocationTable, ("unique_identifier",)),
        (
            PositionSet,
            PositionSetTable,
            ("account_target_allocation_uid", "position_set_time"),
        ),
        (IndexType, IndexTypeTable, ("index_type",)),
        (Index, IndexTable, ("unique_identifier",)),
        (OrderManager, OrderManagerTable, ("unique_identifier",)),
    ],
)
def test_api_rows_declare_table_and_upsert_contracts(
    row_model,
    table_model,
    upsert_keys,
) -> None:
    assert row_model.__table__ is table_model
    assert table_model in row_model.__required_tables__
    assert row_model.__upsert_keys__ == upsert_keys
    assert issubclass(row_model, MarketsMetaTableRow)


def test_legacy_markets_row_name_is_compatibility_alias() -> None:
    assert MarketsRow is MarketsMetaTableRow


def test_position_set_requires_utc_timestamp() -> None:
    account_target_allocation_uid = uuid.uuid4()

    with pytest.raises(ValidationError):
        PositionSetUpsert(
            account_target_allocation_uid=account_target_allocation_uid,
            position_set_time="eod",
        )

    with pytest.raises(ValidationError):
        PositionSetUpsert(
            account_target_allocation_uid=account_target_allocation_uid,
            position_set_time=dt.datetime(2026, 5, 25),
        )

    payload = PositionSetUpsert(
        account_target_allocation_uid=account_target_allocation_uid,
        position_set_time="2026-05-25T00:00:00Z",
    )

    assert payload.position_set_time == dt.datetime(2026, 5, 25, tzinfo=dt.UTC)


def test_account_pretty_print_positions_formats_holdings(capsys) -> None:
    account_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()
    account = Account.model_validate(
        {
            "uid": account_uid,
            "unique_identifier": "account-main",
            "account_name": "Main Account",
            "is_paper": True,
            "account_is_active": True,
        }
    )
    holdings = pd.DataFrame(
        [
            {
                "time_index": dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
                "account_uid": account_uid,
                "asset_identifier": "example-asset-btc",
                "quantity": 10.0,
                "direction": -1,
                "extra_details": {"ticker": "BTC"},
            }
        ]
    ).set_index(["time_index", "account_uid", "asset_identifier"])

    positions = account.pretty_print_positions(
        holdings,
        asset_resolver=lambda unique_identifier: SimpleNamespace(
            uid=asset_uid,
            unique_identifier=unique_identifier,
        ),
    )

    assert positions.to_dict("records") == [
        {
            "asset_uid": asset_uid,
            "ticker": "BTC",
            "position_type": "quantity",
            "position_value": -10.0,
        }
    ]
    assert "asset_uid" in capsys.readouterr().out


def test_account_pretty_print_positions_rejects_datanode_run_tuple() -> None:
    account = Account.model_validate(
        {
            "uid": uuid.uuid4(),
            "unique_identifier": "account-main",
            "account_name": "Main Account",
        }
    )
    holdings = pd.DataFrame(
        [
            {
                "time_index": dt.datetime(2026, 5, 25, tzinfo=dt.UTC),
                "account_uid": account.uid,
                "asset_identifier": "example-asset-btc",
                "quantity": 10.0,
            }
        ]
    ).set_index(["time_index", "account_uid", "asset_identifier"])

    with pytest.raises(TypeError, match="Unpack DataNode run results"):
        account.pretty_print_positions((False, holdings))


def test_account_owns_group_relationship_only() -> None:
    assert AccountGroup.__required_tables__ == [AccountGroupTable]
    assert AccountGroupTable in AccountGroup.__required_tables__
    assert AccountAllocationModelTable not in Account.__required_tables__
    assert AccountGroupTable in Account.__required_tables__
    assert "account_group_uid" in AccountTable.__table__.c
    assert "account_allocation_model_uid" not in AccountTable.__table__.c
    assert "account_allocation_model_uid" not in AccountGroupTable.__table__.c
