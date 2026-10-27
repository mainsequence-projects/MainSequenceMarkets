"""ADR 0047: ``PortfoliosUpdater`` binds the updaters it builds to provider instances.

A provider that computes portfolios into its own ``PortfoliosTS`` instance also
needs the executed weights and the rebalance state in its own
``PortfolioWeightsTS`` and ``PortfolioRebalanceStateTS`` instances. The instance
tables change where rows land, not the producers' identities: MetaTables keys
each update record by update hash and output table.
"""

from __future__ import annotations

from msm_portfolios.time_index import PortfoliosUpdater, PortfolioWeights
from msm_portfolios.time_index.contract_instances import (
    configured_portfolio_rebalance_state_storage,
    configured_portfolio_weights_storage,
    configured_portfolios_storage,
)
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalanceStateStorage
from msm_portfolios.time_index.portfolios.storage import PortfoliosStorage, PortfolioWeightsStorage
from tests.identity.test_pinned_identities import NESTED_PORTFOLIOS, _bound, _built_updaters

CORE_UIDS = {
    PortfoliosStorage: "a0000000-0000-4000-8000-000000000001",
    PortfolioWeightsStorage: "a0000000-0000-4000-8000-000000000002",
    PortfolioRebalanceStateStorage: "a0000000-0000-4000-8000-000000000003",
}


def _instances():
    values = configured_portfolios_storage(
        instance_key="engine", namespace="my-provider", storage_app="my_provider"
    )
    weights = configured_portfolio_weights_storage(
        instance_key="engine", namespace="my-provider", storage_app="my_provider"
    )
    rebalance = configured_portfolio_rebalance_state_storage(
        instance_key="engine", namespace="my-provider", storage_app="my_provider"
    )
    return values, weights, rebalance


def test_portfolios_updater_binds_internal_updaters_to_instance_tables() -> None:
    values, weights, rebalance = _instances()
    with (
        _built_updaters() as updaters,
        _bound(PortfoliosStorage, CORE_UIDS[PortfoliosStorage]),
        _bound(PortfolioWeightsStorage, CORE_UIDS[PortfolioWeightsStorage]),
        _bound(PortfolioRebalanceStateStorage, CORE_UIDS[PortfolioRebalanceStateStorage]),
        _bound(values, "b0000000-0000-4000-8000-000000000001"),
        _bound(weights, "b0000000-0000-4000-8000-000000000002"),
        _bound(rebalance, "b0000000-0000-4000-8000-000000000003"),
    ):
        configuration = NESTED_PORTFOLIOS["interpolated_prices_valuation"]
        core = PortfoliosUpdater(portfolio_configuration=configuration(updaters))
        provider = PortfoliosUpdater(
            portfolio_configuration=configuration(updaters),
            output_table=values,
            weights_output_table=weights,
            rebalance_output_table=rebalance,
        )

    assert provider.output_table is values
    assert provider.portfolio_weights.output_table is weights
    assert provider.portfolio_weights.portfolio_rebalance.output_table is rebalance
    assert core.portfolio_weights.output_table is PortfolioWeightsStorage
    assert core.portfolio_weights.portfolio_rebalance.output_table is PortfolioRebalanceStateStorage

    assert provider.update_hash == core.update_hash
    assert provider.portfolio_weights.update_hash == core.portfolio_weights.update_hash
    assert (
        provider.portfolio_weights.portfolio_rebalance.update_hash
        == core.portfolio_weights.portfolio_rebalance.update_hash
    )
    assert "weights_output_table" not in provider.build_configuration
    assert "rebalance_output_table" not in provider.build_configuration


def test_portfolio_weights_binds_its_rebalance_updater_without_changing_its_hash() -> None:
    _, weights, rebalance = _instances()
    with (
        _built_updaters() as updaters,
        _bound(PortfolioWeightsStorage, CORE_UIDS[PortfolioWeightsStorage]),
        _bound(PortfolioRebalanceStateStorage, CORE_UIDS[PortfolioRebalanceStateStorage]),
        _bound(weights, "b0000000-0000-4000-8000-000000000002"),
        _bound(rebalance, "b0000000-0000-4000-8000-000000000003"),
    ):
        configuration = NESTED_PORTFOLIOS["time_weighted_rebalance"]
        core = PortfolioWeights(portfolio_configuration=configuration(updaters))
        provider = PortfolioWeights(
            portfolio_configuration=configuration(updaters),
            output_table=weights,
            rebalance_output_table=rebalance,
        )
        storage_only_core = PortfolioWeights()
        storage_only_provider = PortfolioWeights(rebalance_output_table=rebalance)

    assert provider.output_table is weights
    assert provider.portfolio_rebalance.output_table is rebalance
    assert provider.update_hash == core.update_hash
    assert provider.portfolio_rebalance.update_hash == core.portfolio_rebalance.update_hash
    assert storage_only_provider.update_hash == storage_only_core.update_hash


def test_interpolated_prices_can_live_in_a_provider_namespace() -> None:
    from msm.time_index.assets.storage import AssetSnapshotsStorage
    from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
    from msm_portfolios.time_index.prices.storage import configured_interpolated_prices_storage
    from tests.identity.test_pinned_identities import (
        PRICES_TABLE_UID,
        SOURCE_TABLE_UID,
        _interpolated_prices_storage,
    )
    from msm.time_index.assets import AssetSnapshot

    provider_storage = configured_interpolated_prices_storage(
        source_time_index_meta_table_uid=SOURCE_TABLE_UID,
        source_cadence="1d",
        upsample_frequency_id="1d",
        intraday_bar_interpolation_rule="ffill",
        namespace="my-provider",
        storage_app="my_provider",
    )
    core_storage = _interpolated_prices_storage()

    assert provider_storage is not core_storage
    assert provider_storage.__table__.name.startswith("my_provider__interpolated_prices__")
    assert provider_storage.__table__.info["namespace"] == "my-provider"
    assert provider_storage.__metatable_identifier__.endswith(
        core_storage.__metatable_identifier__.split(".", 1)[1]
    )
    assert provider_storage.__metatable_extra_hash_components__ == (
        core_storage.__metatable_extra_hash_components__
    )

    with (
        _bound(AssetSnapshotsStorage, SOURCE_TABLE_UID, cadence="1d"),
        _bound(core_storage, PRICES_TABLE_UID),
        _bound(provider_storage, "c0000000-0000-4000-8000-000000000001"),
    ):
        config = InterpolatedPricesConfig(
            source_price_instance=AssetSnapshot(),
            intraday_bar_interpolation_rule="ffill",
            upsample_frequency_id="1d",
            asset_list=["ASSET_A"],
        )
        core = InterpolatedPrices(config)
        provider = InterpolatedPrices(
            config, storage_namespace="my-provider", storage_app="my_provider"
        )

    assert core.output_table is core_storage
    assert provider.output_table is provider_storage
    assert provider.update_hash == core.update_hash
    assert "storage_namespace" not in provider.build_configuration
