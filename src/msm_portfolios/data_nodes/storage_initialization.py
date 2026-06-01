from __future__ import annotations

from typing import Any

from mainsequence.client.models_metatables import TimeIndexMetaData as DataNodeStorage

from .base import PortfolioCanonicalDataNode, _storage_source_config


def initialize_portfolio_storage_source_tables(
    *,
    portfolio_weights: PortfolioCanonicalDataNode | None = None,
    signal_weights: PortfolioCanonicalDataNode | None = None,
    portfolio_data: PortfolioCanonicalDataNode | None = None,
    anchor_node: PortfolioCanonicalDataNode | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Validate canonical Portfolios storage metadata for the storage family."""
    family = _resolve_storage_family(
        portfolio_weights=portfolio_weights,
        signal_weights=signal_weights,
        portfolio_data=portfolio_data,
        anchor_node=anchor_node,
    )
    storages = {
        payload_key: _ensure_storage_metadata(node, timeout=timeout)
        for payload_key, node in family.items()
    }
    result: dict[str, Any] = {}

    for payload_key, node in family.items():
        storage = storages[payload_key]
        source_config = _storage_source_config(storage)
        if source_config is None:
            refreshed_storage = _refresh_storage(storage, timeout=timeout)
            if refreshed_storage is not None:
                _set_node_storage(node, refreshed_storage)
                storage = refreshed_storage
                source_config = _storage_source_config(storage)

        if source_config is None:
            raise RuntimeError(
                f"Portfolio storage {payload_key} does not expose a source-table "
                "configuration. Register the storage MetaTable before writing."
            )
        node._validate_storage_contract(source_config)
        result[payload_key] = source_config

    return result


def _resolve_storage_family(
    *,
    portfolio_weights: PortfolioCanonicalDataNode | None,
    signal_weights: PortfolioCanonicalDataNode | None,
    portfolio_data: PortfolioCanonicalDataNode | None,
    anchor_node: PortfolioCanonicalDataNode | None,
) -> dict[str, PortfolioCanonicalDataNode]:
    from .portfolio_weights import PortfolioWeights
    from .portfolios import PortfoliosDataNode
    from .signal_weights import SignalWeights

    namespace = _node_namespace(
        anchor_node or portfolio_weights or signal_weights or portfolio_data
    )
    if anchor_node is not None:
        if isinstance(anchor_node, PortfolioWeights):
            portfolio_weights = portfolio_weights or anchor_node
        elif isinstance(anchor_node, SignalWeights):
            signal_weights = signal_weights or anchor_node
        elif isinstance(anchor_node, PortfoliosDataNode):
            portfolio_data = portfolio_data or anchor_node
        else:
            raise TypeError(
                "anchor_node must be PortfolioWeights, SignalWeights, or PortfoliosDataNode."
            )

    return {
        "portfolio_weights": portfolio_weights or PortfolioWeights(namespace=namespace),
        "signal_weights": signal_weights or SignalWeights(namespace=namespace),
        "portfolio_data": portfolio_data or PortfoliosDataNode(namespace=namespace),
    }


def _node_namespace(node: PortfolioCanonicalDataNode | None) -> str | None:
    if node is None:
        return None
    namespace = getattr(node, "hash_namespace", "") or ""
    return namespace or None


def _ensure_storage_metadata(
    node: PortfolioCanonicalDataNode,
    *,
    timeout: int | None,
) -> Any:
    storage = getattr(node, "data_node_storage", None)
    if _coerce_optional_uid(storage) is None:
        node.verify_and_build_remote_objects()
        storage = getattr(node, "data_node_storage", None)
    if _coerce_optional_uid(storage) is None:
        raise RuntimeError(
            f"{node.__class__.__name__} must have a DataNodeStorage uid before "
            "the portfolio storage source tables can be initialized."
        )
    return storage


def _refresh_storage(storage: Any, *, timeout: int | None) -> Any | None:
    storage_uid = _coerce_optional_uid(storage)
    if storage_uid is None:
        return None
    return DataNodeStorage.get(
        uid=storage_uid,
        include_relations_detail=True,
        timeout=timeout,
    )


def _set_node_storage(node: PortfolioCanonicalDataNode, storage: Any) -> None:
    try:
        node.local_persist_manager.data_node_storage = storage
    except Exception:
        pass


def _coerce_required_uid(value: Any) -> str:
    uid = _coerce_optional_uid(value)
    if uid is None:
        raise ValueError("DataNodeStorage must expose a public uid.")
    return uid


def _coerce_optional_uid(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        uid = value.get("uid")
    else:
        uid = getattr(value, "uid", None)
    if uid in (None, ""):
        return None
    return str(uid)
