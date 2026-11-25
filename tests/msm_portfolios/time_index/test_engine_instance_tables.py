"""An application keeps a portfolio's rebalance state and ledger in its own tables (ADR 0060).

``PortfolioValues`` and ``PortfolioWeights`` publish values and weights to Markets and
take no output table for them. ``rebalance_output_table`` and
``event_ledger_output_table`` bind the ``PortfolioRebalance`` and ``PortfolioEngine``
they build to the application's own ``PortfolioRebalanceStateTS`` and
``PortfolioEventLedgerTS`` instances (decision 7, ADR 0065). An instance changes where
the rows land, not the updater's identity: MetaTables keys each update record by update
hash and output table.
"""

from __future__ import annotations

import inspect

import pytest
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import sqlalchemy_naming_convention
from msm_portfolios.time_index import PortfolioValues, PortfolioWeights
from msm_portfolios.time_index.contract_instances import (
    PortfolioEventLedgerInstance,
    PortfolioRebalanceStateInstance,
)
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalanceStateStorage
from msm_portfolios.time_index.portfolios.storage import PortfolioEventLedgerStorage
from tests.support.pinned_identities import NESTED_PORTFOLIOS, _bound, _built_updaters

CORE_REBALANCE_UID = "a0000000-0000-4000-8000-000000000003"
CORE_LEDGER_UID = "a0000000-0000-4000-8000-000000000004"


class ProviderBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class EngineRebalanceState(PortfolioRebalanceStateInstance, ProviderBase):
    __instance_key__ = "engine"
    __metatable_namespace__ = "my-app"
    __markets_storage_app__ = "my_app"


class EngineEventLedger(PortfolioEventLedgerInstance, ProviderBase):
    __instance_key__ = "engine"
    __metatable_namespace__ = "my-app"
    __markets_storage_app__ = "my_app"


def _engine(values: PortfolioValues):
    """The ledger the values node builds, once its portfolio's identity is known."""
    weights = values.portfolio_weights
    weights.set_portfolio_configuration(
        values.portfolio_configuration, portfolio_identifier="pinned-portfolio"
    )
    return weights.ensure_portfolio_engine()


def test_the_nodes_bind_the_rebalance_state_and_ledger_to_the_applications_tables() -> None:
    rebalance = EngineRebalanceState
    ledger = EngineEventLedger
    with (
        _built_updaters() as updaters,
        _bound(PortfolioRebalanceStateStorage, CORE_REBALANCE_UID),
        _bound(PortfolioEventLedgerStorage, CORE_LEDGER_UID),
        _bound(rebalance, "b0000000-0000-4000-8000-000000000003"),
        _bound(ledger, "b0000000-0000-4000-8000-000000000004"),
    ):
        configuration = NESTED_PORTFOLIOS["interpolated_prices_valuation"]
        core = _engine(PortfolioValues(portfolio_configuration=configuration(updaters)))
        application = _engine(
            PortfolioValues(
                portfolio_configuration=configuration(updaters),
                rebalance_output_table=rebalance,
                event_ledger_output_table=ledger,
            )
        )

    assert application.config.portfolio_rebalance_instance.output_table is rebalance
    assert application.output_table is ledger
    assert core.config.portfolio_rebalance_instance.output_table is (
        PortfolioRebalanceStateStorage
    )
    assert core.output_table is PortfolioEventLedgerStorage
    assert (
        application.config.portfolio_rebalance_instance.update_hash
        == core.config.portfolio_rebalance_instance.update_hash
    )
    # The ledger's identity names the rebalance it reads, and so that rebalance's table.
    assert application.update_hash != core.update_hash


@pytest.mark.parametrize("node", [PortfolioValues, PortfolioWeights])
def test_published_nodes_take_no_output_table(node) -> None:
    parameters = inspect.signature(node.__init__).parameters

    assert "output_table" not in parameters
    assert "weights_output_table" not in parameters
    assert {"rebalance_output_table", "event_ledger_output_table"} <= set(parameters)
    with pytest.raises(TypeError):
        node(output_table=PortfolioRebalanceStateStorage)
