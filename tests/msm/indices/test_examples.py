from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_PROJECT_ROOT)]

from examples.msm.indices import (  # noqa: E402
    commodity_calendar_spread,
    delta_hedged_option_index,
    equity_beta_spread,
    extension_owned_index_storage,
    index_values_frequency_migration,
    m_bond_2s5s_yield_spread,
    plain_index_values,
    weighted_multi_leg_spreads,
)


def test_m_bond_example_publishes_basis_points_and_resolved_monthly_bonds() -> None:
    output = m_bond_2s5s_yield_spread.run()

    assert output["values"]["value"].tolist() == pytest.approx([117.0, 120.0])
    assert len(output["resolved_legs"]) == 4
    assert set(output["historical_meaning"]) == {
        m_bond_2s5s_yield_spread.ROLLING_IDENTIFIER,
        m_bond_2s5s_yield_spread.CURRENT_CONSTITUENTS_HISTORY_IDENTIFIER,
    }


def test_commodity_example_separates_fixed_and_rolling_contract_histories() -> None:
    output = commodity_calendar_spread.run()

    assert output["fixed_values"]["value"].tolist() == pytest.approx([2.0, 3.0])
    assert output["rolling_values"]["value"].tolist() == pytest.approx([2.0, 1.5])
    assert len(output["resolved_legs"]) == 4


def test_multi_leg_example_calculates_butterfly_and_unit_normalized_crack() -> None:
    output = weighted_multi_leg_spreads.run()

    assert output["butterfly"]["value"].tolist() == pytest.approx([0.0, 10.0])
    assert output["crack_spread"]["value"].tolist() == pytest.approx([63.0, 72.6])


def test_equity_beta_example_persists_lagged_coefficients_without_lookahead() -> None:
    output = equity_beta_spread.run()

    assert output["no_lookahead"] is True
    assert not output["values"].empty
    assert not output["resolved_legs"].empty


def test_delta_example_distinguishes_current_mark_from_self_financing_performance() -> None:
    output = delta_hedged_option_index.run()

    assert len(output["current_mark"]) == 5
    assert len(output["performance"]) == 5
    assert output["performance"].iloc[0]["value"] == pytest.approx(100.0)
    assert output["performance_uses_prior_positions"] is True
    assert len(output["resolved_deltas"]) == 5


def test_plain_index_values_share_identity_across_frequencies() -> None:
    output = plain_index_values.run()

    one_minute = output["frequency_datasets"]["1m"]
    daily = output["frequency_datasets"]["1d"]
    one_minute_values = one_minute["values"].reset_index()
    daily_values = daily["values"].reset_index()
    assert output["index_identifier"] == "USD_SWAP_10Y"
    assert output["index_identity"]["index_type"] == "interest_rate"
    assert one_minute["data_node"] is plain_index_values.Swap10YOneMinuteDataNode
    assert daily["data_node"] is plain_index_values.Swap10YDailyDataNode
    assert one_minute["data_node"] is not daily["data_node"]
    assert one_minute["storage_table"] is not daily["storage_table"]
    assert output["migration_models"] == (
        one_minute["storage_table"],
        daily["storage_table"],
    )
    assert one_minute["storage_table"].__cadence__ == "1m"
    assert daily["storage_table"].__cadence__ == "1d"
    assert one_minute["storage_table"].__table__.name != daily["storage_table"].__table__.name
    assert one_minute_values["index_identifier"].unique().tolist() == ["USD_SWAP_10Y"]
    assert daily_values["index_identifier"].unique().tolist() == ["USD_SWAP_10Y"]
    assert one_minute_values["definition_uid"].isna().all()
    assert daily_values["definition_uid"].isna().all()
    assert one_minute_values["observation_status"].tolist() == [
        "preliminary",
        "preliminary",
    ]
    assert daily_values["observation_status"].tolist() == ["final"]
    assert output["methodology_identity"]["coexisting_methods"] == (
        "USD_SWAP_10Y_METHOD_A",
        "USD_SWAP_10Y_METHOD_B",
    )


def test_frequency_storage_models_are_built_before_migration_provider() -> None:
    models = index_values_frequency_migration.FREQUENCY_STORAGE_MODELS

    assert list(index_values_frequency_migration.migration.metatable_models) == list(models)
    assert [model.__cadence__ for model in models] == ["1m", "1d"]
    assert [model.__table__.name for model in models] == [
        "ms_markets__index_values__t_1m",
        "ms_markets__index_values__t_1d",
    ]


def test_extension_owns_rich_storage_without_core_index_data_node_base() -> None:
    output = extension_owned_index_storage.run()

    from msm.data_nodes.indices import IndexTimestampedDataNode

    extension = output["extension_values"].reset_index()
    canonical = output["canonical_values"].reset_index()
    foreign_key = next(
        iter(
            extension_owned_index_storage.ExtensionIndexObservationsStorage.__table__.c[
                "index_identifier"
            ].foreign_keys
        )
    )
    assert not issubclass(
        extension_owned_index_storage.ExtensionIndexObservationsDataNode,
        IndexTimestampedDataNode,
    )
    assert foreign_key.target_fullname == "ms_markets__index.unique_identifier"
    assert output["index_identity"]["unique_identifier"] == "USD_SWAP_10Y"
    assert extension_owned_index_storage.ExtensionIndexObservationsStorage.__cadence__ == "1m"
    assert (
        extension_owned_index_storage.ExtensionIndexObservationsStorage.__table__.name
        == "extension_example__index_observations__t_1m"
    )
    assert extension_owned_index_storage.CANONICAL_ONE_MINUTE_VALUES_STORAGE.__cadence__ == "1m"
    assert extension.loc[0, "bid"] == pytest.approx(0.04190)
    assert extension.loc[0, "ask"] == pytest.approx(0.04194)
    assert canonical.loc[0, "value"] == pytest.approx(extension.loc[0, "mid"])
    assert canonical.loc[0, "definition_uid"] is None
    assert canonical.loc[0, "observation_status"] == "preliminary"
