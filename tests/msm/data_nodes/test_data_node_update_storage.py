from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from msm.data_nodes.accounts import AccountHoldings
from msm.data_nodes.storage import AccountHoldingsStorage
from msm.data_nodes.utils.data_node_updates import data_node_update_storage
from msm.data_nodes.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_index_names,
    storage_time_index_name,
)


def test_account_holdings_storage_readiness_uses_data_node_update_storage(monkeypatch) -> None:
    storage = SimpleNamespace(
        uid=uuid4(),
        source_table_configuration=_source_table_configuration(AccountHoldingsStorage),
    )
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=storage)
    monkeypatch.setattr(
        AccountHoldings,
        "data_node_update",
        property(lambda _self: data_node_update),
    )
    node = object.__new__(AccountHoldings)
    node._storage_table = AccountHoldingsStorage

    assert data_node_update_storage(node._require_ready_data_node_update()) is storage
    assert node.ensure_storage_ready() == str(data_node_update.uid)


def test_account_holdings_force_update_returns_data_node_update_uid(monkeypatch) -> None:
    storage = SimpleNamespace(
        uid=uuid4(),
        source_table_configuration=_source_table_configuration(AccountHoldingsStorage),
    )
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=storage)
    state = {"data_node_update": None, "run_calls": 0}

    monkeypatch.setattr(
        AccountHoldings,
        "data_node_update",
        property(lambda _self: state["data_node_update"]),
    )

    def run(_self, **_kwargs):
        state["run_calls"] += 1
        state["data_node_update"] = data_node_update

    monkeypatch.setattr(AccountHoldings, "run", run)
    node = object.__new__(AccountHoldings)
    node._storage_table = AccountHoldingsStorage

    assert node.ensure_storage_ready(force_update=True) == str(data_node_update.uid)
    assert state["run_calls"] == 1


def test_account_holdings_readiness_uses_storage_metadata_when_update_storage_is_uid(
    monkeypatch,
) -> None:
    storage_uid = uuid4()
    storage_metadata = SimpleNamespace(
        uid=storage_uid,
        source_table_configuration=_source_table_configuration(AccountHoldingsStorage),
    )
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=str(storage_uid))
    monkeypatch.setattr(
        AccountHoldings,
        "data_node_update",
        property(lambda _self: data_node_update),
    )
    monkeypatch.setattr(
        AccountHoldings,
        "storage_metadata",
        property(lambda _self: storage_metadata),
    )
    node = object.__new__(AccountHoldings)
    node._storage_table = AccountHoldingsStorage

    assert node.ensure_storage_ready() == str(data_node_update.uid)


def test_account_holdings_readiness_raises_for_update_without_storage(monkeypatch) -> None:
    data_node_update = SimpleNamespace(uid=uuid4(), data_node_storage=None)
    monkeypatch.setattr(
        AccountHoldings,
        "data_node_update",
        property(lambda _self: data_node_update),
    )

    def run(_self, **_kwargs):
        raise AssertionError("strict readiness must not rerun malformed existing updates")

    monkeypatch.setattr(AccountHoldings, "run", run)
    node = object.__new__(AccountHoldings)
    node._storage_table = AccountHoldingsStorage

    with pytest.raises(ValueError, match="data_node_update.data_node_storage"):
        node.ensure_storage_ready()


def test_account_holdings_readiness_raises_for_update_without_uid(monkeypatch) -> None:
    data_node_update = SimpleNamespace(uid=None)
    monkeypatch.setattr(
        AccountHoldings,
        "data_node_update",
        property(lambda _self: data_node_update),
    )

    def run(_self, **_kwargs):
        raise AssertionError("strict readiness must not rerun malformed existing updates")

    monkeypatch.setattr(AccountHoldings, "run", run)
    node = object.__new__(AccountHoldings)
    node._storage_table = AccountHoldingsStorage

    with pytest.raises(ValueError, match="data_node_update"):
        node.ensure_storage_ready()


def _source_table_configuration(storage_table) -> SimpleNamespace:
    return SimpleNamespace(
        time_index_name=storage_time_index_name(storage_table),
        index_names=storage_index_names(storage_table),
        column_dtypes_map=storage_column_dtypes_map(storage_table),
    )
