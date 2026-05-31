from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from msm.api.accounts import (
    Account,
    AccountGroup,
    AccountTargetPositionAssignment,
    AccountTargetPositionAssignmentUpsert,
)
from msm.api.assets import (
    AssetCategory,
    AssetCategoryMembership,
    AssetType,
    OpenFigiDetails,
)
from msm.api.calendars import Calendar
from msm.api.execution import Order, OrderManager, OrderStatusEvent
from msm.api.indices import Index, IndexType
from msm.api.market_metadata import (
    RebalanceStrategyMetadata,
    SignalMetadata,
)
from msm.api.portfolios import Fund, Portfolio, PortfolioAssetDetail, PortfolioMetadata
from msm.models import (
    AccountGroupTable,
    AccountTable,
    AccountTargetPositionAssignmentTable,
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTypeTable,
    AssetTable,
    CalendarTable,
    FundTable,
    IndexTable,
    IndexTypeTable,
    OpenFigiAssetDetailsTable,
    OrderManagerTable,
    OrderTable,
    PortfolioAssetDetailTable,
    PortfolioMetadataTable,
    PortfolioTable,
    RebalanceStrategyMetadataTable,
    SignalMetadataTable,
)


@pytest.mark.parametrize(
    ("row_model", "table_model", "upsert_keys"),
    [
        (AssetType, AssetTypeTable, ("asset_type",)),
        (AssetCategory, AssetCategoryTable, ("unique_identifier",)),
        (AssetCategoryMembership, AssetCategoryMembershipTable, ("category_uid", "asset_uid")),
        (OpenFigiDetails, OpenFigiAssetDetailsTable, ("asset_uid",)),
        (Calendar, CalendarTable, ("name",)),
        (Account, AccountTable, ("unique_identifier",)),
        (
            AccountTargetPositionAssignment,
            AccountTargetPositionAssignmentTable,
            ("account_uid", "target_positions_time"),
        ),
        (Portfolio, PortfolioTable, ("unique_identifier",)),
        (PortfolioAssetDetail, PortfolioAssetDetailTable, ("portfolio_uid",)),
        (PortfolioMetadata, PortfolioMetadataTable, ("unique_identifier",)),
        (Fund, FundTable, ("unique_identifier",)),
        (IndexType, IndexTypeTable, ("index_type",)),
        (Index, IndexTable, ("unique_identifier",)),
        (SignalMetadata, SignalMetadataTable, ("signal_uid",)),
        (
            RebalanceStrategyMetadata,
            RebalanceStrategyMetadataTable,
            ("rebalance_strategy_uid",),
        ),
        (OrderManager, OrderManagerTable, ("unique_identifier",)),
        (Order, OrderTable, ("order_time", "order_remote_id", "asset_unique_identifier")),
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


def test_account_target_position_assignment_requires_utc_timestamp() -> None:
    account_uid = uuid.uuid4()
    position_set_uid = uuid.uuid4()

    with pytest.raises(ValidationError):
        AccountTargetPositionAssignmentUpsert(
            account_uid=account_uid,
            target_positions_time="eod",
            position_set_uid=position_set_uid,
        )

    with pytest.raises(ValidationError):
        AccountTargetPositionAssignmentUpsert(
            account_uid=account_uid,
            target_positions_time=dt.datetime(2026, 5, 25),
            position_set_uid=position_set_uid,
        )

    payload = AccountTargetPositionAssignmentUpsert(
        account_uid=account_uid,
        target_positions_time="2026-05-25T00:00:00Z",
        position_set_uid=position_set_uid,
    )

    assert payload.target_positions_time == dt.datetime(2026, 5, 25, tzinfo=dt.UTC)


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
                "unique_identifier": "example-asset-btc",
                "quantity": 10.0,
                "extra_details": {"ticker": "BTC"},
            }
        ]
    ).set_index(["time_index", "account_uid", "unique_identifier"])

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
            "position_value": 10.0,
        }
    ]
    assert "asset_uid" in capsys.readouterr().out


def test_portfolio_create_schemas_includes_domain_required_tables(monkeypatch) -> None:
    calls = []
    runtime = SimpleNamespace()

    def fake_start_engine(**kwargs):
        calls.append(kwargs)
        return runtime

    monkeypatch.setattr("msm.bootstrap.start_engine", fake_start_engine)

    assert Portfolio.create_schemas(namespace="mainsequence.examples") is runtime
    assert calls == [
        {
            "models": [AssetTable, PortfolioTable, PortfolioAssetDetailTable],
            "namespace": "mainsequence.examples",
        }
    ]


def test_missing_required_table_fails_before_operation(monkeypatch) -> None:
    runtime = SimpleNamespace(
        context=object(),
        meta_table_models=[PortfolioTable],
    )

    def fake_attach_schemas(**kwargs):
        raise RuntimeError("offline unit test")

    monkeypatch.setattr("msm.bootstrap._RUNTIME", runtime)
    monkeypatch.setattr("msm.bootstrap.attach_schemas", fake_attach_schemas)

    with pytest.raises(RuntimeError, match="AssetTable"):
        Portfolio.filter(unique_identifier_contains="demo")


def test_append_only_status_event_does_not_define_generic_upsert() -> None:
    assert OrderStatusEvent.__upsert_keys__ == ()

    with pytest.raises(NotImplementedError):
        OrderStatusEvent.upsert(
            event_time=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            order_status="filled",
        )


def test_account_group_requires_model_portfolio_dependency() -> None:
    assert AccountGroupTable in AccountGroup.__required_tables__
