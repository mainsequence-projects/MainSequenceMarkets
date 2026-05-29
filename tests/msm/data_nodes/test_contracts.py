from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

from mainsequence.client.models_tdag import LOGICAL_COLUMN_DTYPES_ATTR

from msm.data_nodes.accounts import AccountHoldings, VirtualFundHoldings
from msm.data_nodes.utils import (
    ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT,
    FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT,
    POSITION_EXPOSURE_TABLE_CONTRACT,
    source_table_initialization_kwargs,
)
from msm.models import markets_sqlalchemy_models
from msm.services.holdings import (
    build_account_holdings_frame,
    build_fund_holdings_frame,
)
from msm.services.target_positions import (
    build_target_positions_frame,
    validate_target_position_payload,
)


def test_holdings_contracts_are_not_registered_as_metatables() -> None:
    model_table_names = {model.__table__.name for model in markets_sqlalchemy_models()}

    assert ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT.table_name not in model_table_names
    assert FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT.table_name not in model_table_names
    assert POSITION_EXPOSURE_TABLE_CONTRACT.table_name not in model_table_names


def test_account_and_fund_holdings_data_nodes_use_backend_independent_contracts() -> None:
    assert not hasattr(ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT, "column_dtypes_map")
    assert not hasattr(FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT, "column_dtypes_map")
    assert not hasattr(POSITION_EXPOSURE_TABLE_CONTRACT, "column_dtypes_map")
    assert AccountHoldings._required_index_names() == (
        ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT.dynamic_table_index_names
    )
    assert VirtualFundHoldings._required_index_names() == (
        FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT.dynamic_table_index_names
    )
    assert AccountHoldings.default_config().column_dtypes_map == (
        _record_dtypes(ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT)
    )
    assert VirtualFundHoldings.default_config().column_dtypes_map == (
        _record_dtypes(FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT)
    )
    assert _record_dtypes(ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT)["quantity"] == "float64"
    assert (
        _record_dtypes(ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT)["target_trade_time"]
        == "datetime64[ns, UTC]"
    )
    assert _record_dtypes(ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT)["unique_identifier"] == (
        "string"
    )
    assert _record_dtypes(FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT)["target_weight"] == "float64"
    assert (
        _record_dtypes(FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT)["target_trade_time"]
        == "datetime64[ns, UTC]"
    )
    assert _record_dtypes(FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT)["unique_identifier"] == "string"


def test_holdings_source_initialization_uses_generic_platform_api() -> None:
    class FakeStorage:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.sourcetableconfiguration = None

        def initialize_source_table(self, **kwargs):
            self.calls.append(kwargs)
            self.sourcetableconfiguration = SimpleNamespace(**kwargs)
            return {"source_table_configuration": kwargs}

        def initialize_account_holdings_source_table(self, **kwargs):  # pragma: no cover
            raise AssertionError("Legacy initializer must not be called.")

    storage = FakeStorage()
    config = AccountHoldings.default_config()

    AccountHoldings._initialize_source_table(
        AccountHoldings.__new__(AccountHoldings),
        storage=storage,
        config=config,
    )

    assert storage.calls == [
        {
            "time_index_name": config.time_index_name,
            "index_names": config.index_names,
            "column_dtypes_map": config.column_dtypes_map,
        }
    ]


def test_source_table_initialization_kwargs_are_generic_dynamic_table_payload() -> None:
    payload = source_table_initialization_kwargs(POSITION_EXPOSURE_TABLE_CONTRACT)

    assert payload == {
        "time_index_name": "time_index",
        "index_names": ["time_index", "position_set_uid", "unique_identifier"],
        "column_dtypes_map": _record_dtypes(POSITION_EXPOSURE_TABLE_CONTRACT),
    }


def test_account_holdings_frame_builder_uses_datanode_contract() -> None:
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

    assert list(frame.index.names) == ["time_index", "account_uid", "unique_identifier"]
    assert frame.attrs[LOGICAL_COLUMN_DTYPES_ATTR] == (
        _record_dtypes(ACCOUNT_HISTORICAL_HOLDINGS_TABLE_CONTRACT)
    )
    row = frame.reset_index().iloc[0]
    assert row["account_uid"] == str(account_uid)
    assert row["holdings_set_uid"] == str(holdings_set_uid)
    assert row["quantity"] == 1.25
    assert str(frame.reset_index()["quantity"].dtype) == "float64"
    assert str(frame.reset_index()["target_trade_time"].dtype) == "datetime64[ns, UTC]"
    assert row["target_trade_time"] == pd.Timestamp("2026-05-25T11:00:00Z")


def test_account_holdings_datanode_exposes_frame_helpers_only() -> None:
    account_node = AccountHoldings.__new__(AccountHoldings)

    frame = account_node.build_account_holdings_frame(
        holdings_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        account_uid=uuid.uuid4(),
        positions=[{"unique_identifier": "BTC", "quantity": "1"}],
    )

    assert list(frame.index.names) == ["time_index", "account_uid", "unique_identifier"]
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

    assert list(frame.index.names) == ["time_index", "fund_uid", "unique_identifier"]
    assert frame.attrs[LOGICAL_COLUMN_DTYPES_ATTR] == (
        _record_dtypes(FUND_HISTORICAL_HOLDINGS_TABLE_CONTRACT)
    )
    row = frame.reset_index().iloc[0]
    assert row["fund_uid"] == str(fund_uid)
    assert row["quantity"] == 3.0
    assert row["target_weight"] == 0.15
    assert str(frame.reset_index()["quantity"].dtype) == "float64"
    assert str(frame.reset_index()["target_weight"].dtype) == "float64"


def test_virtual_fund_holdings_datanode_exposes_frame_helpers() -> None:
    fund_node = VirtualFundHoldings.__new__(VirtualFundHoldings)

    frame = fund_node.build_fund_holdings_frame(
        holdings_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        fund_uid=uuid.uuid4(),
        positions=[{"unique_identifier": "ETH", "quantity": "3"}],
    )

    assert list(frame.index.names) == ["time_index", "fund_uid", "unique_identifier"]


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


def test_target_positions_frame_validation_keeps_datanode_dtype_contract() -> None:
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

    assert list(frame.index.names) == ["time_index", "position_set_uid", "unique_identifier"]
    assert frame.attrs[LOGICAL_COLUMN_DTYPES_ATTR] == (
        _record_dtypes(POSITION_EXPOSURE_TABLE_CONTRACT)
    )
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


def _record_dtypes(contract) -> dict[str, str]:
    return {record.column_name: record.dtype for record in contract.records}
