from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from mainsequence.meta_tables import APIDataNode
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.models.assets.core import AssetTable
from msm.models.portfolios import PortfolioTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.asset_scope import ASSET_IDENTIFIER
from msm_portfolios.contrib.prices.data_nodes import (
    _asset_calendar_map,
    _normalize_time_indexed_frame_ns_utc,
    _source_time_indexed_profile_cadence,
)
from msm_portfolios.data_nodes.portfolios.weights import PortfolioWeights
from msm_portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm_portfolios.data_nodes.portfolios.storage import (
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.data_nodes.prices.storage import (
    ExternalPricesStorage,
    InterpolatedPricesStorage,
    configured_interpolated_prices_storage,
    interpolated_prices_storage_table_name,
)
from msm_portfolios.data_nodes.signals import SignalWeights
from msm_portfolios.data_nodes.signals.storage import (
    SignalWeightsStorage,
)
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_portfolio_asset_scope_uses_markets_asset_dimension() -> None:
    assert ASSET_IDENTIFIER == ASSET_IDENTIFIER_DIMENSION


def test_portfolio_nodes_expose_storage_first_surface(monkeypatch) -> None:
    registered = set(portfolio_sqlalchemy_models())

    for node_cls in (PortfolioWeights, PortfoliosDataNode, SignalWeights):
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
    assert PortfolioWeightsStorage.metatable_identifier().endswith("PortfolioWeightsTS")
    assert SignalWeightsStorage.metatable_identifier().endswith("SignalWeightsTS")
    assert PortfoliosStorage.metatable_identifier().endswith("PortfoliosTS")
    assert ExternalPricesStorage.metatable_identifier().endswith("ExternalPricesTS")
    assert InterpolatedPricesStorage.metatable_identifier().endswith("InterpolatedPricesTS")


def test_external_price_storage_is_registered_by_portfolio_provider() -> None:
    assert ExternalPricesStorage in set(portfolio_sqlalchemy_models())
    assert ExternalPricesStorage.__cadence__ == "1d"


def test_portfolio_price_storage_has_asset_identifier_foreign_key() -> None:
    expected_target = f"{AssetTable.__table__.fullname}.unique_identifier"

    for storage_table in (ExternalPricesStorage, InterpolatedPricesStorage):
        foreign_keys = storage_table.__table__.c.asset_identifier.foreign_keys
        assert len(foreign_keys) == 1
        assert next(iter(foreign_keys)).target_fullname == expected_target


def test_portfolio_values_storage_has_portfolio_identifier_foreign_key() -> None:
    foreign_keys = PortfoliosStorage.__table__.c.portfolio_identifier.foreign_keys

    assert len(foreign_keys) == 1
    foreign_key = next(iter(foreign_keys))
    assert foreign_key.column is PortfolioTable.__table__.c.unique_identifier
    assert foreign_key.ondelete == "RESTRICT"


def test_interpolated_prices_accepts_registered_top_level_source_cadence() -> None:
    source_prices_ts = SimpleNamespace(
        uid="source-uid",
        time_indexed_profile=None,
        cadence="1D",
    )
    source_price = APIDataNode(
        data_source_uid="source-data-source",
        storage_hash="source-prices",
        storage_table=source_prices_ts,
    )

    assert (
        _source_time_indexed_profile_cadence(
            source_price,
            source_time_index_meta_table_uid="source-uid",
        )
        == "1d"
    )


def test_interpolated_prices_asset_calendar_map_accepts_string_scope_items() -> None:
    assert _asset_calendar_map(
        [
            "example-asset-btc",
            {"unique_identifier": "example-asset-eth", "calendar": "NYSE"},
            {"metadata": {"unique_identifier": "example-asset-sol"}},
        ]
    ) == {
        "example-asset-btc": "24/7",
        "example-asset-eth": "NYSE",
        "example-asset-sol": "24/7",
    }


def test_interpolated_prices_normalizes_time_index_output_to_ns_utc() -> None:
    time_values = pd.to_datetime(
        [
            "2026-05-23T00:00:00Z",
            "2026-05-24T00:00:00Z",
        ],
        utc=True,
    ).astype("datetime64[us, UTC]")
    frame = pd.DataFrame(
        {
            "time_index": time_values,
            ASSET_IDENTIFIER_DIMENSION: ["example-asset-btc", "example-asset-eth"],
            "open_time": time_values,
            "close": [100.0, 200.0],
        }
    ).set_index(["time_index", ASSET_IDENTIFIER_DIMENSION])

    normalized = _normalize_time_indexed_frame_ns_utc(frame)

    assert str(normalized.index.get_level_values("time_index").dtype) == "datetime64[ns, UTC]"
    assert str(normalized["open_time"].dtype) == "datetime64[ns, UTC]"


def test_interpolated_price_policy_changes_configured_storage_table_name() -> None:
    daily_storage = configured_interpolated_prices_storage(
        source_time_index_meta_table_uid="source-uid",
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    minute_storage = configured_interpolated_prices_storage(
        source_time_index_meta_table_uid="source-uid",
        source_cadence="5m",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )

    assert daily_storage.__table__.name == interpolated_prices_storage_table_name(
        source_time_index_meta_table_uid="source-uid",
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
    )
    assert daily_storage.__table__.name != minute_storage.__table__.name
    assert daily_storage.metatable_identifier() != minute_storage.metatable_identifier()
    assert "InterpolatedPricesTS" in daily_storage.metatable_identifier()
    assert "InterpolatedPricesTS" in minute_storage.metatable_identifier()
    assert daily_storage.__metatable_extra_hash_components__["source_cadence"] == "1d"
    assert minute_storage.__metatable_extra_hash_components__["source_cadence"] == "5m"
    assert daily_storage.__cadence__ == "1d"
    assert minute_storage.__cadence__ == "1d"
    assert daily_storage.__index_names__ == ["time_index", ASSET_IDENTIFIER_DIMENSION]
    foreign_keys = daily_storage.__table__.c.asset_identifier.foreign_keys
    assert len(foreign_keys) == 1
    assert next(iter(foreign_keys)).target_fullname == (
        f"{AssetTable.__table__.fullname}.unique_identifier"
    )
    assert "source_cadence" not in daily_storage.__table__.c
    assert "upsample_frequency_id" not in daily_storage.__table__.c
    assert "intraday_bar_interpolation_rule" not in daily_storage.__table__.c
