from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

from msm.portfolios.data_nodes.constants import (
    PORTFOLIOS_COLUMN_DTYPES_MAP,
    PORTFOLIOS_INDEX_NAMES,
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    PORTFOLIO_WEIGHTS_COLUMN_DTYPES_MAP,
    PORTFOLIO_WEIGHTS_INDEX_NAMES,
    SIGNAL_WEIGHTS_COLUMN_DTYPES_MAP,
    SIGNAL_WEIGHTS_INDEX_NAMES,
)
from msm.portfolios.data_nodes.storage_initialization import (
    initialize_portfolio_storage_source_tables,
)


class FakeStorage:
    def __init__(self) -> None:
        self.uid = str(uuid.uuid4())
        self.calls: list[dict[str, Any]] = []
        self.sourcetableconfiguration = None

    def initialize_source_table(self, **kwargs):
        self.calls.append(kwargs)
        self.sourcetableconfiguration = SimpleNamespace(
            time_index_name=kwargs["time_index_name"],
            index_names=kwargs["index_names"],
            column_dtypes_map=kwargs["column_dtypes_map"],
        )
        return {"source_table_configuration": kwargs}

    def initialize_portfolio_storage_source_tables(self, **kwargs):  # pragma: no cover
        raise AssertionError("Legacy portfolio initializer must not be called.")


class FakePortfolioNode:
    def __init__(self, *, index_names: list[str], column_dtypes_map: dict[str, str]):
        self.hash_namespace = None
        self.data_node_storage = FakeStorage()
        self.validated_source_configs: list[Any] = []
        self._config = SimpleNamespace(
            time_index_name=PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
            index_names=index_names,
            column_dtypes_map=column_dtypes_map,
        )

    def _canonical_config(self):
        return self._config

    def _validate_storage_contract(self, source_config: Any) -> None:
        self.validated_source_configs.append(source_config)


def test_portfolio_storage_initialization_uses_generic_source_table_api() -> None:
    portfolio_weights = FakePortfolioNode(
        index_names=list(PORTFOLIO_WEIGHTS_INDEX_NAMES),
        column_dtypes_map=dict(PORTFOLIO_WEIGHTS_COLUMN_DTYPES_MAP),
    )
    signal_weights = FakePortfolioNode(
        index_names=list(SIGNAL_WEIGHTS_INDEX_NAMES),
        column_dtypes_map=dict(SIGNAL_WEIGHTS_COLUMN_DTYPES_MAP),
    )
    portfolio_data = FakePortfolioNode(
        index_names=list(PORTFOLIOS_INDEX_NAMES),
        column_dtypes_map=dict(PORTFOLIOS_COLUMN_DTYPES_MAP),
    )

    result = initialize_portfolio_storage_source_tables(
        portfolio_weights=portfolio_weights,
        signal_weights=signal_weights,
        portfolio_data=portfolio_data,
        timeout=5,
    )

    assert set(result) == {"portfolio_weights", "signal_weights", "portfolio_data"}
    for node in (portfolio_weights, signal_weights, portfolio_data):
        assert node.data_node_storage.calls == [
            {
                "time_index_name": node._config.time_index_name,
                "index_names": node._config.index_names,
                "column_dtypes_map": node._config.column_dtypes_map,
                "timeout": 5,
            }
        ]
        assert node.validated_source_configs
