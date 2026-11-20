"""An application keeps a portfolio's rebalance state in its own table (ADR 0060, decision 7).

``PortfoliosUpdater`` and ``PortfolioWeights`` publish values and weights to Markets and
take no output table for them; ``rebalance_output_table`` binds the ``PortfolioRebalance``
they build to the application's own ``PortfolioRebalanceStateTS`` instance. The instance
changes where the state lands, not the updater's identity: MetaTables keys each update
record by update hash and output table.
"""

from __future__ import annotations

import inspect

import pytest

from msm_portfolios.time_index import PortfoliosUpdater, PortfolioWeights
from msm_portfolios.time_index.contract_instances import (
    configured_portfolio_rebalance_state_storage,
)
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalanceStateStorage
from tests.support.pinned_identities import NESTED_PORTFOLIOS, _bound, _built_updaters

CORE_REBALANCE_UID = "a0000000-0000-4000-8000-000000000003"


def _rebalance_instance():
    return configured_portfolio_rebalance_state_storage(
        instance_key="engine", namespace="my-app", storage_app="my_app"
    )


def test_portfolios_updater_binds_the_rebalance_state_to_the_applications_table() -> None:
    rebalance = _rebalance_instance()
    with (
        _built_updaters() as updaters,
        _bound(PortfolioRebalanceStateStorage, CORE_REBALANCE_UID),
        _bound(rebalance, "b0000000-0000-4000-8000-000000000003"),
    ):
        configuration = NESTED_PORTFOLIOS["interpolated_prices_valuation"]
        core = PortfoliosUpdater(portfolio_configuration=configuration(updaters))
        application = PortfoliosUpdater(
            portfolio_configuration=configuration(updaters),
            rebalance_output_table=rebalance,
        )

    assert application.portfolio_weights.portfolio_rebalance.output_table is rebalance
    assert core.portfolio_weights.portfolio_rebalance.output_table is (
        PortfolioRebalanceStateStorage
    )
    assert (
        application.portfolio_weights.portfolio_rebalance.update_hash
        == core.portfolio_weights.portfolio_rebalance.update_hash
    )


@pytest.mark.parametrize("node", [PortfoliosUpdater, PortfolioWeights])
def test_published_nodes_take_no_output_table(node) -> None:
    parameters = inspect.signature(node.__init__).parameters

    assert "output_table" not in parameters
    assert "weights_output_table" not in parameters
    assert "rebalance_output_table" in parameters
    with pytest.raises(TypeError):
        node(output_table=PortfolioRebalanceStateStorage)


def test_interpolated_prices_can_live_in_a_provider_namespace() -> None:
    from msm.time_index.assets.storage import AssetSnapshotsStorage
    from msm_portfolios.contrib.prices.updaters import InterpolatedPrices, InterpolatedPricesConfig
    from msm_portfolios.time_index.prices.storage import configured_interpolated_prices_storage
    from tests.support.pinned_identities import (
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
