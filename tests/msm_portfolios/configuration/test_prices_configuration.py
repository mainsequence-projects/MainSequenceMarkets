from __future__ import annotations

import pytest
from pydantic import ValidationError

from msm_portfolios.configuration import PricesConfiguration
from msm_portfolios.contrib.prices.data_nodes import (
    InterpolatedPricesConfig,
    _source_time_indexed_profile_cadence,
)

SOURCE_TIME_INDEX_META_TABLE_UID = "00000000-0000-0000-0000-000000000001"


def test_prices_configuration_uses_time_index_meta_table_uid() -> None:
    assert "source_time_index_meta_table_uid" in PricesConfiguration.model_fields
    assert "bar_frequency_id" not in PricesConfiguration.model_fields
    assert "markets_time_series" not in PricesConfiguration.model_fields
    assert "source_bars_data_node" not in PricesConfiguration.model_fields

    configuration = PricesConfiguration(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
    )

    assert str(configuration.source_time_index_meta_table_uid) == (
        SOURCE_TIME_INDEX_META_TABLE_UID
    )


def test_prices_configuration_requires_source_time_index_meta_table_uid() -> None:
    with pytest.raises(ValidationError):
        PricesConfiguration(
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
        )


def test_prices_configuration_rejects_user_supplied_bar_frequency_id() -> None:
    with pytest.raises(ValidationError):
        PricesConfiguration(
            bar_frequency_id="1d",
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        )


def test_interpolated_prices_config_uses_storage_uid_not_live_source_node() -> None:
    assert "source_time_index_meta_table_uid" in InterpolatedPricesConfig.model_fields
    assert "bar_frequency_id" not in InterpolatedPricesConfig.model_fields
    assert "source_bars_data_node" not in InterpolatedPricesConfig.model_fields

    configuration = InterpolatedPricesConfig(
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        asset_list=["example-asset-btc"],
    )

    assert str(configuration.source_time_index_meta_table_uid) == (
        SOURCE_TIME_INDEX_META_TABLE_UID
    )


def test_interpolated_prices_config_rejects_user_supplied_bar_frequency_id() -> None:
    with pytest.raises(ValidationError):
        InterpolatedPricesConfig(
            bar_frequency_id="1d",
            upsample_frequency_id="1d",
            intraday_bar_interpolation_rule="ffill",
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
            asset_list=["example-asset-btc"],
        )


class _Profile:
    cadence = "1D"


class _StorageTable:
    time_indexed_profile = _Profile()


class _SourceNode:
    storage_table = _StorageTable()


def test_source_time_indexed_profile_cadence_is_canonicalized() -> None:
    assert (
        _source_time_indexed_profile_cadence(
            _SourceNode(),
            source_time_index_meta_table_uid=SOURCE_TIME_INDEX_META_TABLE_UID,
        )
        == "1d"
    )
