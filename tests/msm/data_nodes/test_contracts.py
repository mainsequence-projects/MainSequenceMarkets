from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

from mainsequence.client import dtype_codec as dc

from msm.data_nodes.accounts import AccountHoldings, VirtualFundHoldings
from msm.data_nodes.storage import (
    AccountHoldingsStorage,
    FundHoldingsStorage,
    TargetPositionsStorage,
)
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.models import markets_sqlalchemy_models
from msm.services.holdings import (
    build_account_holdings_frame,
    build_fund_holdings_frame,
)
from msm.services.target_positions import (
    build_target_positions_frame,
    validate_target_position_payload,
)


def test_holdings_storage_classes_are_registered_metatables() -> None:
    model_classes = set(markets_sqlalchemy_models())

    assert AccountHoldingsStorage in model_classes
    assert FundHoldingsStorage in model_classes
    assert TargetPositionsStorage in model_classes


def test_holdings_nodes_source_column_dtypes_from_storage_classes() -> None:
    assert not hasattr(AccountHoldings, "_required_column_dtypes_map")
    assert not hasattr(VirtualFundHoldings, "_required_column_dtypes_map")
    assert AccountHoldings._column_dtypes_map_for_storage(
        AccountHoldingsStorage
    ) == storage_column_dtypes_map(AccountHoldingsStorage)
    assert VirtualFundHoldings._column_dtypes_map_for_storage(
        FundHoldingsStorage
    ) == storage_column_dtypes_map(FundHoldingsStorage)
    assert AccountHoldings._required_storage_table() is AccountHoldingsStorage
    assert VirtualFundHoldings._required_storage_table() is FundHoldingsStorage


def test_account_holdings_dtype_tokens_match_storage_columns() -> None:
    dtype_map = AccountHoldings._column_dtypes_map_for_storage(AccountHoldingsStorage)

    assert dtype_map["quantity"] == dc.FLOAT64
    assert dtype_map["unique_identifier"] == dc.STRING
    assert dtype_map["time_index"] == dc.TIMESTAMP_TZ
    assert dtype_map["target_trade_time"] == dc.TIMESTAMP_TZ
    # Holdings identity/grouping UUID columns are uuid-typed on the storage class.
    assert dtype_map["account_uid"] == dc.UUID_TOKEN
    assert dtype_map["holdings_set_uid"] == dc.UUID_TOKEN


def test_holdings_bound_dtype_map_uses_instance_storage_table() -> None:
    node = SimpleNamespace(storage_table=FundHoldingsStorage)

    assert AccountHoldings._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        FundHoldingsStorage
    )


def test_fund_holdings_dtype_tokens_match_storage_columns() -> None:
    dtype_map = VirtualFundHoldings._column_dtypes_map_for_storage(FundHoldingsStorage)

    assert dtype_map["target_weight"] == dc.FLOAT64
    assert dtype_map["quantity"] == dc.FLOAT64
    assert dtype_map["target_trade_time"] == dc.TIMESTAMP_TZ
    assert dtype_map["unique_identifier"] == dc.STRING
    assert dtype_map["fund_uid"] == dc.UUID_TOKEN


def test_holdings_bootstrap_frames_match_storage_index_and_columns() -> None:
    account_frame = AccountHoldings.build_schema_bootstrap_frame()
    fund_frame = VirtualFundHoldings.build_schema_bootstrap_frame()

    assert list(account_frame.index.names) == list(AccountHoldingsStorage.__index_names__)
    assert list(fund_frame.index.names) == list(FundHoldingsStorage.__index_names__)
    assert str(account_frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"
    assert str(fund_frame.reset_index()["time_index"].dtype) == "datetime64[ns, UTC]"

    account_columns = set(account_frame.reset_index().columns)
    assert set(storage_column_dtypes_map(AccountHoldingsStorage)).issubset(account_columns)


def test_account_holdings_frame_builder_uses_storage_contract() -> None:
    account_uid = uuid.uuid4()
    holdings_set_uid = uuid.uuid4()

    frame = build_account_holdings_frame(
        holdings_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        account_uid=account_uid,
        holdings_set_uid=holdings_set_uid,
        positions=[
            {
                "unique_identifier": "BTC",
                "quantity": "1.25",
                "target_trade_time": dt.datetime(2026, 5, 25, 11, tzinfo=dt.UTC),
                "extra_details": {"venue": "test"},
            }
        ],
    )

    assert list(frame.index.names) == list(AccountHoldingsStorage.__index_names__)
    row = frame.reset_index().iloc[0]
    assert row["account_uid"] == str(account_uid)
    assert row["holdings_set_uid"] == str(holdings_set_uid)
    assert row["quantity"] == 1.25
    assert str(frame.reset_index()["quantity"].dtype) == "float64"
    assert str(frame.reset_index()["target_trade_time"].dtype) == "datetime64[ns, UTC]"
    assert row["target_trade_time"] == pd.Timestamp("2026-05-25T11:00:00Z")


def test_account_holdings_datanode_exposes_frame_helpers_only() -> None:
    frame = build_account_holdings_frame(
        holdings_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        account_uid=uuid.uuid4(),
        positions=[{"unique_identifier": "BTC", "quantity": "1"}],
    )

    assert list(frame.index.names) == list(AccountHoldingsStorage.__index_names__)
    assert not hasattr(AccountHoldings, "create_account")
    assert not hasattr(AccountHoldings, "add_account_holdings")
    assert not hasattr(AccountHoldings, "get_account_holdings")


def test_fund_holdings_frame_builder_keeps_target_weight_contract() -> None:
    fund_uid = uuid.uuid4()

    frame = build_fund_holdings_frame(
        holdings_date="2026-05-25T10:00:00+00:00",
        fund_uid=fund_uid,
        positions=[
            {
                "unique_identifier": "ETH",
                "quantity": "3",
                "target_weight": "0.15",
            }
        ],
    )

    assert list(frame.index.names) == list(FundHoldingsStorage.__index_names__)
    row = frame.reset_index().iloc[0]
    assert row["fund_uid"] == str(fund_uid)
    assert row["quantity"] == 3.0
    assert row["target_weight"] == 0.15
    assert str(frame.reset_index()["quantity"].dtype) == "float64"
    assert str(frame.reset_index()["target_weight"].dtype) == "float64"


def test_holdings_frame_builder_rejects_duplicate_position_identifiers() -> None:
    with pytest.raises(ValueError, match="Duplicate values: BTC"):
        build_account_holdings_frame(
            holdings_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
            account_uid=uuid.uuid4(),
            positions=[
                {"unique_identifier": "BTC", "quantity": "1"},
                {"unique_identifier": "BTC", "quantity": "2"},
            ],
        )


def test_target_positions_frame_validation_keeps_storage_dtype_contract() -> None:
    position_set_uid = uuid.uuid4()
    frame = build_target_positions_frame(
        target_positions_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        position_set_uid=position_set_uid,
        positions=[
            {
                "unique_identifier": "BTC",
                "weight_notional_exposure": "0.25",
            }
        ],
    )

    assert list(frame.index.names) == list(TargetPositionsStorage.__index_names__)
    assert frame.reset_index()["position_set_uid"].iloc[0] == str(position_set_uid)
    assert str(frame.reset_index()["weight_notional_exposure"].dtype) == "float64"
    assert frame.reset_index()["weight_notional_exposure"].iloc[0] == 0.25


def test_target_positions_require_exactly_one_exposure_shape() -> None:
    with pytest.raises(ValueError):
        validate_target_position_payload(
            {
                "unique_identifier": "BTC",
                "weight_notional_exposure": "0.25",
                "single_asset_quantity": "1",
            }
        )
