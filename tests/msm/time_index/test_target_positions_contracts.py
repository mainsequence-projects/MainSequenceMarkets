from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from msm.time_index.accounts import TargetPositions, TargetPositionsConfiguration
from msm.time_index.accounts.constants import TARGET_TYPE_ASSET, TARGET_TYPE_PORTFOLIO
from msm.time_index.accounts.storage import TargetPositionsStorage
from msm.time_index.utils.storage_schema import storage_column_dtypes_map
from msm.models import AssetTable, PortfolioTable, PositionSetTable, markets_sqlalchemy_models
from msm.models.registration import markets_foreign_key_target_identifiers
from msm.services.target_positions import (
    build_target_positions_frame,
    validate_target_position_payload,
)
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_target_positions_storage_belongs_to_core_account_model_graph() -> None:
    assert TargetPositionsStorage in set(markets_sqlalchemy_models())
    assert TargetPositionsStorage in set(portfolio_sqlalchemy_models())


def test_target_positions_storage_declares_target_foreign_keys() -> None:
    assert set(markets_foreign_key_target_identifiers(TargetPositionsStorage)) == {
        AssetTable.__table__.name,
        PortfolioTable.__table__.name,
        PositionSetTable.__table__.name,
    }

    position_set_column = TargetPositionsStorage.__table__.columns["position_set_uid"]
    asset_column = TargetPositionsStorage.__table__.columns["asset_uid"]
    portfolio_column = TargetPositionsStorage.__table__.columns["portfolio_uid"]
    assert any(
        foreign_key.column is PositionSetTable.__table__.c.uid and foreign_key.ondelete == "CASCADE"
        for foreign_key in position_set_column.foreign_keys
    )
    assert any(
        foreign_key.column is AssetTable.__table__.c.uid and foreign_key.ondelete == "RESTRICT"
        for foreign_key in asset_column.foreign_keys
    )
    assert any(
        foreign_key.column is PortfolioTable.__table__.c.uid and foreign_key.ondelete == "RESTRICT"
        for foreign_key in portfolio_column.foreign_keys
    )


def test_target_positions_storage_declares_target_index_names() -> None:
    assert TargetPositionsStorage.__index_names__ == [
        "time_index",
        "position_set_uid",
        "target_type",
        "target_uid",
        "asset_uid",
    ]


def test_target_positions_storage_stores_units_only() -> None:
    columns = TargetPositionsStorage.__table__.columns

    assert columns["quantity"].nullable is False
    assert columns["direction"].nullable is False
    assert columns["asset_uid"].nullable is False
    assert columns["portfolio_uid"].nullable is True
    assert not {
        "weight_notional_exposure",
        "constant_notional_exposure",
        "single_asset_quantity",
    } & set(columns.keys())


def test_target_positions_storage_validates_target_type() -> None:
    storage = TargetPositionsStorage(target_type=TARGET_TYPE_ASSET)

    assert storage.target_type == TARGET_TYPE_ASSET
    with pytest.raises(ValueError, match="target_type must be one of: asset, portfolio"):
        storage.target_type = "fund"


def test_target_positions_node_uses_target_position_configuration() -> None:
    config = TargetPositions.default_config()

    assert isinstance(config, TargetPositionsConfiguration)
    assert TargetPositions._required_output_table() is TargetPositionsStorage
    assert TargetPositions._column_dtypes_map_for_storage(
        TargetPositionsStorage
    ) == storage_column_dtypes_map(TargetPositionsStorage)


def test_target_positions_bound_dtype_map_uses_instance_output_table() -> None:
    node = SimpleNamespace(output_table=TargetPositionsStorage)

    assert TargetPositions._bound_column_dtypes_map(node) == storage_column_dtypes_map(
        TargetPositionsStorage
    )


def test_target_positions_node_requires_real_frame() -> None:
    node = object.__new__(TargetPositions)

    with pytest.raises(ValueError, match="requires a real target-position frame"):
        node.get_target_positions_frame()


def test_target_positions_frame_accepts_asset_targets_and_fund_baskets() -> None:
    position_set_uid = uuid.uuid4()
    direct_asset_uid = uuid.uuid4()
    basket_asset_uids = [uuid.uuid4(), uuid.uuid4()]
    portfolio_uid = uuid.uuid4()

    frame = build_target_positions_frame(
        target_positions_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        position_set_uid=position_set_uid,
        positions=[
            {"asset_uid": direct_asset_uid, "quantity": "12"},
            {"portfolio_uid": portfolio_uid, "asset_uid": basket_asset_uids[0], "quantity": 1000},
            {
                "portfolio_uid": portfolio_uid,
                "asset_uid": basket_asset_uids[1],
                "quantity": 40,
                "direction": -1,
            },
        ],
    )

    assert list(frame.index.names) == list(TargetPositionsStorage.__index_names__)
    flat = frame.reset_index()
    asset_row = flat[flat["target_type"] == TARGET_TYPE_ASSET].iloc[0]
    basket = flat[flat["target_type"] == TARGET_TYPE_PORTFOLIO]
    assert asset_row["position_set_uid"] == str(position_set_uid)
    assert asset_row["asset_uid"] == str(direct_asset_uid)
    assert asset_row["target_uid"] == str(direct_asset_uid)
    assert asset_row["quantity"] == 12.0
    assert asset_row["direction"] == 1
    assert set(basket["portfolio_uid"]) == {str(portfolio_uid)}
    assert set(basket["target_uid"]) == {str(portfolio_uid)}
    assert set(basket["asset_uid"]) == {str(uid) for uid in basket_asset_uids}
    short = basket[basket["asset_uid"] == str(basket_asset_uids[1])].iloc[0]
    assert (short["quantity"], short["direction"]) == (40.0, -1)
    assert str(flat["quantity"].dtype) == "float64"
    assert str(flat["direction"].dtype) == "int16"


def test_target_positions_frame_refuses_one_asset_twice_in_a_basket() -> None:
    portfolio_uid = uuid.uuid4()
    asset_uid = uuid.uuid4()

    with pytest.raises(ValueError, match="duplicate rows"):
        build_target_positions_frame(
            target_positions_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
            position_set_uid=uuid.uuid4(),
            positions=[
                {"portfolio_uid": portfolio_uid, "asset_uid": asset_uid, "quantity": 5},
                {"portfolio_uid": portfolio_uid, "asset_uid": asset_uid, "quantity": 7},
            ],
        )


def test_one_asset_can_be_a_direct_target_and_in_two_baskets() -> None:
    asset_uid = uuid.uuid4()

    frame = build_target_positions_frame(
        target_positions_date=dt.datetime(2026, 5, 25, 10, tzinfo=dt.UTC),
        position_set_uid=uuid.uuid4(),
        positions=[
            {"asset_uid": asset_uid, "quantity": 1},
            {"portfolio_uid": uuid.uuid4(), "asset_uid": asset_uid, "quantity": 500},
            {"portfolio_uid": uuid.uuid4(), "asset_uid": asset_uid, "quantity": 300},
        ],
    )

    assert len(frame) == 3


def test_target_positions_reject_stale_asset_identifier() -> None:
    with pytest.raises(ValueError, match="not asset_identifier"):
        validate_target_position_payload({"asset_identifier": "BTC", "quantity": 1})


def test_target_positions_require_an_asset() -> None:
    with pytest.raises(ValueError, match="must provide asset_uid"):
        validate_target_position_payload({"portfolio_uid": uuid.uuid4(), "quantity": 1})


@pytest.mark.parametrize("quantity", [None, 0, -5, "nan", "inf"])
def test_target_positions_require_a_positive_quantity(quantity) -> None:
    with pytest.raises(ValueError, match="quantity"):
        validate_target_position_payload({"asset_uid": uuid.uuid4(), "quantity": quantity})


@pytest.mark.parametrize("direction", [0, 2, -2, 0.5, "long"])
def test_target_positions_require_a_known_direction(direction) -> None:
    with pytest.raises(ValueError, match="direction must be 1 for long or -1 for short"):
        validate_target_position_payload(
            {"asset_uid": uuid.uuid4(), "quantity": 1, "direction": direction}
        )


def test_target_positions_default_to_long() -> None:
    payload = validate_target_position_payload({"asset_uid": uuid.uuid4(), "quantity": "2.5"})

    assert (payload["quantity"], payload["direction"]) == (2.5, 1)


@pytest.mark.parametrize(
    "field_name",
    ["weight_notional_exposure", "constant_notional_exposure", "single_asset_quantity"],
)
def test_target_positions_carry_no_value_exposure(field_name) -> None:
    with pytest.raises(ValueError, match="must provide a quantity"):
        validate_target_position_payload({"asset_uid": uuid.uuid4(), field_name: "0.25"})


def test_target_type_must_match_the_row() -> None:
    with pytest.raises(ValueError, match="target_type must be portfolio"):
        validate_target_position_payload(
            {
                "asset_uid": uuid.uuid4(),
                "portfolio_uid": uuid.uuid4(),
                "quantity": 1,
                "target_type": "asset",
            }
        )
    with pytest.raises(ValueError, match="target_uid must match portfolio_uid"):
        validate_target_position_payload(
            {
                "asset_uid": uuid.uuid4(),
                "portfolio_uid": uuid.uuid4(),
                "quantity": 1,
                "target_uid": uuid.uuid4(),
            }
        )
