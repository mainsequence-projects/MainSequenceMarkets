from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from msm.data_nodes.utils.data_node_updates import data_node_update_storage
from msm.data_nodes.utils.storage_schema import storage_column_dtypes_map
from msm.data_nodes.utils.storage_schema import storage_index_names, storage_time_index_name
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.asset_scope import ASSET_IDENTIFIER
from msm_portfolios.data_nodes.portfolio_weights import PortfolioWeights
from msm_portfolios.data_nodes.portfolios import PortfoliosDataNode
from msm_portfolios.data_nodes.signal_weights import SignalWeights
from msm_portfolios.data_nodes.storage import (
    InterpolatedPricesStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
    SignalWeightsStorage,
    TargetPositionsStorage,
    VirtualFundHoldingsStorage,
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
    assert InterpolatedPricesStorage.metatable_identifier() == "InterpolatedPricesTS"
    assert TargetPositionsStorage.metatable_identifier() == "TargetPositionsTS"
    assert VirtualFundHoldingsStorage.metatable_identifier() == "VirtualFundHoldingsTS"


def test_portfolio_storage_readiness_uses_data_node_update_storage(monkeypatch) -> None:
    storage = SimpleNamespace(
        uid=uuid4(),
        source_table_configuration=_source_table_configuration(SignalWeightsStorage),
    )
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=storage)
    monkeypatch.setattr(
        SignalWeights,
        "data_node_update",
        property(lambda _self: data_node_update),
    )
    node = object.__new__(SignalWeights)
    node._storage_table = SignalWeightsStorage

    assert data_node_update_storage(node._require_ready_data_node_update()) is storage
    assert node.ensure_storage_ready() == str(data_node_update.uid)


def test_portfolio_force_update_returns_data_node_update_uid(monkeypatch) -> None:
    storage = SimpleNamespace(
        uid=uuid4(),
        source_table_configuration=_source_table_configuration(PortfolioWeightsStorage),
    )
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=storage)
    state = {"data_node_update": None, "run_calls": 0}

    monkeypatch.setattr(
        PortfolioWeights,
        "data_node_update",
        property(lambda _self: state["data_node_update"]),
    )

    def run(_self, **_kwargs):
        state["run_calls"] += 1
        state["data_node_update"] = data_node_update

    monkeypatch.setattr(PortfolioWeights, "run", run)
    node = object.__new__(PortfolioWeights)
    node._storage_table = PortfolioWeightsStorage

    assert node.ensure_storage_ready(force_update=True) == str(data_node_update.uid)
    assert state["run_calls"] == 1


def test_portfolio_readiness_uses_storage_metadata_when_update_storage_is_uid(
    monkeypatch,
) -> None:
    storage_uid = uuid4()
    storage_metadata = SimpleNamespace(
        uid=storage_uid,
        source_table_configuration=_source_table_configuration(PortfoliosStorage),
    )
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=str(storage_uid))
    monkeypatch.setattr(
        PortfoliosDataNode,
        "data_node_update",
        property(lambda _self: data_node_update),
    )
    monkeypatch.setattr(
        PortfoliosDataNode,
        "storage_metadata",
        property(lambda _self: storage_metadata),
    )
    node = object.__new__(PortfoliosDataNode)
    node._storage_table = PortfoliosStorage

    assert node.ensure_storage_ready() == str(data_node_update.uid)


def test_portfolio_readiness_raises_for_update_without_storage(monkeypatch) -> None:
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=None)
    monkeypatch.setattr(
        SignalWeights,
        "data_node_update",
        property(lambda _self: data_node_update),
    )

    def run(_self, **_kwargs):
        raise AssertionError("strict readiness must not rerun malformed existing updates")

    monkeypatch.setattr(SignalWeights, "run", run)
    node = object.__new__(SignalWeights)
    node._storage_table = SignalWeightsStorage

    with pytest.raises(ValueError, match="data_node_update.data_node_storage"):
        node.ensure_storage_ready()


def test_portfolio_readiness_raises_for_update_without_uid(monkeypatch) -> None:
    data_node_update = SimpleNamespace(uid=None)
    monkeypatch.setattr(
        SignalWeights,
        "data_node_update",
        property(lambda _self: data_node_update),
    )

    def run(_self, **_kwargs):
        raise AssertionError("strict readiness must not rerun malformed existing updates")

    monkeypatch.setattr(SignalWeights, "run", run)
    node = object.__new__(SignalWeights)
    node._storage_table = SignalWeightsStorage

    with pytest.raises(ValueError, match="data_node_update"):
        node.ensure_storage_ready()


def _source_table_configuration(storage_table) -> SimpleNamespace:
    return SimpleNamespace(
        time_index_name=storage_time_index_name(storage_table),
        index_names=storage_index_names(storage_table),
        column_dtypes_map=storage_column_dtypes_map(storage_table),
    )
