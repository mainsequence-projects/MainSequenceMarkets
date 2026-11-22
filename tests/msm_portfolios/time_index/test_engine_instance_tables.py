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
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm_portfolios.time_index import PortfoliosUpdater, PortfolioWeights
from msm_portfolios.time_index.contract_instances import (
    configured_portfolio_rebalance_state_storage,
)
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalanceStateStorage
from tests.support.pinned_identities import NESTED_PORTFOLIOS, _bound, _built_updaters

CORE_REBALANCE_UID = "a0000000-0000-4000-8000-000000000003"


class ProviderBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


def _rebalance_instance():
    return configured_portfolio_rebalance_state_storage(
        instance_key="engine", namespace="my-app", storage_app="my_app", base=ProviderBase
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
