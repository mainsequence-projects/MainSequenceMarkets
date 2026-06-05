from __future__ import annotations

from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.asset_scope import ASSET_IDENTIFIER
from msm_portfolios.data_nodes.portfolio_weights import PortfolioWeights
from msm_portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm_portfolios.data_nodes.signal_weights import SignalWeights
from msm_portfolios.data_nodes.storage import (
    ExternalPricesStorage,
    InterpolatedPricesStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
    SignalWeightsStorage,
    TargetPositionsStorage,
    VirtualFundHoldingsStorage,
    configured_interpolated_prices_storage,
    interpolated_prices_storage_table_name,
)
from msm_portfolios.data_nodes.target_positions import TargetPositions
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_portfolio_asset_scope_uses_markets_asset_dimension() -> None:
    assert ASSET_IDENTIFIER == ASSET_IDENTIFIER_DIMENSION


def test_portfolio_nodes_expose_storage_first_surface(monkeypatch) -> None:
    registered = set(portfolio_sqlalchemy_models())

    for node_cls in (PortfolioWeights, PortfoliosDataNode, SignalWeights, TargetPositions):
        assert "__data_node_identifier__" not in node_cls.__dict__
        assert "_default_identifier" not in node_cls.__dict__
        assert "_default_description" not in node_cls.__dict__
        storage_table = node_cls._required_storage_table()
        registered_identifier = f"registered.{storage_table.metatable_identifier()}"
        monkeypatch.setattr(
            storage_table,
            "get_identifier",
            classmethod(lambda _cls, identifier=registered_identifier: identifier),
        )
        assert node_cls._default_identifier() == registered_identifier
        assert node_cls._default_description() == storage_table.__metatable_description__
        assert storage_table in registered
        assert not hasattr(node_cls, "_required_column_dtypes_map")
        assert not hasattr(node_cls, "_required_index_names")
        assert not hasattr(node_cls, "_required_time_index_name")
        assert node_cls._column_dtypes_map_for_storage(storage_table) == storage_column_dtypes_map(
            storage_table
        )
        assert not hasattr(node_cls, "build_mock_frame")
        assert not hasattr(node_cls, "build_schema_bootstrap_frame")
        assert not hasattr(node_cls, "build_initialization_frame")


def test_portfolio_storage_identifiers_use_camel_case_ts_suffix() -> None:
    assert PortfolioWeightsStorage.metatable_identifier() == "PortfolioWeightsTS"
    assert SignalWeightsStorage.metatable_identifier() == "SignalWeightsTS"
    assert PortfoliosStorage.metatable_identifier() == "PortfoliosTS"
    assert ExternalPricesStorage.metatable_identifier() == "ExternalPricesTS"
    assert InterpolatedPricesStorage.metatable_identifier() == "InterpolatedPricesTS"
    assert TargetPositionsStorage.metatable_identifier() == "TargetPositionsTS"
    assert VirtualFundHoldingsStorage.metatable_identifier() == "VirtualFundHoldingsTS"


def test_external_price_storage_is_registered_by_portfolio_provider() -> None:
    assert ExternalPricesStorage in set(portfolio_sqlalchemy_models())
    assert ExternalPricesStorage.__cadence__ == "1d"


def test_interpolated_price_policy_changes_configured_storage_table_name() -> None:
    daily_storage = configured_interpolated_prices_storage(
        source_storage_hash=ExternalPricesStorage.__table__.name,
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    minute_storage = configured_interpolated_prices_storage(
        source_storage_hash=ExternalPricesStorage.__table__.name,
        source_cadence="5m",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )

    assert daily_storage.__table__.name == interpolated_prices_storage_table_name(
        source_storage_hash=ExternalPricesStorage.__table__.name,
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    assert daily_storage.__table__.name != minute_storage.__table__.name
    assert daily_storage.__metatable_extra_hash_components__["source_cadence"] == "1d"
    assert minute_storage.__metatable_extra_hash_components__["source_cadence"] == "5m"
    assert daily_storage.__cadence__ == "1d"
    assert minute_storage.__cadence__ == "1d"
    assert daily_storage.__index_names__ == ["time_index", ASSET_IDENTIFIER_DIMENSION]
    assert "source_cadence" not in daily_storage.__table__.c
    assert "upsample_frequency_id" not in daily_storage.__table__.c
    assert "intraday_bar_interpolation_rule" not in daily_storage.__table__.c
