from __future__ import annotations

import datetime as dt

PORTFOLIO_CANONICAL_TIME_INDEX_NAME = "time_index"
PORTFOLIO_INDEX_ASSET_UNIQUE_IDENTIFIER = "portfolio_index_asset_unique_identifier"
ASSET_UNIQUE_IDENTIFIER = "unique_identifier"
PORTFOLIO_METADATA_UNIQUE_IDENTIFIER = "unique_identifier"
PORTFOLIO_DESCRIPTION = "description"
SIGNAL_UID = "signal_uid"
SIGNAL_DESCRIPTION = "signal_description"
REBALANCE_STRATEGY_UID = "rebalance_strategy_uid"
REBALANCE_STRATEGY_DESCRIPTION = "rebalance_strategy_description"

PORTFOLIO_WEIGHTS_INDEX_NAMES = [
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    PORTFOLIO_INDEX_ASSET_UNIQUE_IDENTIFIER,
    ASSET_UNIQUE_IDENTIFIER,
]

SIGNAL_WEIGHTS_INDEX_NAMES = [
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    SIGNAL_UID,
    ASSET_UNIQUE_IDENTIFIER,
]

PORTFOLIOS_INDEX_NAMES = [
    PORTFOLIO_CANONICAL_TIME_INDEX_NAME,
    ASSET_UNIQUE_IDENTIFIER,
]

SCHEMA_BOOTSTRAP_TIME_INDEX = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
SCHEMA_BOOTSTRAP_PORTFOLIO_IDENTIFIER = "__schema_bootstrap_portfolio__"
SCHEMA_BOOTSTRAP_ASSET_IDENTIFIER = "__schema_bootstrap_asset__"
SCHEMA_BOOTSTRAP_SIGNAL_UID = "__schema_bootstrap_signal__"
SIGNAL_UID_EXCLUDED_CONFIGURATION_KEYS = frozenset(
    {
        "hash_namespace",
        "namespace",
        "storage_hash",
        "update_hash",
        "storage_id",
        "storage_uid",
        "update_id",
        "update_uid",
        "data_node_storage_id",
        "data_node_storage_uid",
        "data_node_update_id",
        "data_node_update_uid",
        "data_source_id",
        "portfolio_consumers",
        "portfolio_id",
        "portfolio_uid",
        "portfolio_index_asset_unique_identifier",
        "display_name",
        "display_label",
        "signal_name",
        "signal_description",
        "run_id",
        "run_timestamp",
        "created_at",
        "updated_at",
        "creation_date",
    }
)
REBALANCE_STRATEGY_UID_EXCLUDED_CONFIGURATION_KEYS = frozenset(
    {
        "hash_namespace",
        "namespace",
        "storage_hash",
        "update_hash",
        "storage_id",
        "storage_uid",
        "update_id",
        "update_uid",
        "data_node_storage_id",
        "data_node_storage_uid",
        "data_node_update_id",
        "data_node_update_uid",
        "data_source_id",
        "portfolio_consumers",
        "portfolio_id",
        "portfolio_uid",
        "portfolio_index_asset_unique_identifier",
        "display_name",
        "display_label",
        "rebalance_strategy_name",
        "rebalance_strategy_description",
        "description",
        "run_id",
        "run_timestamp",
        "created_at",
        "updated_at",
        "creation_date",
    }
)
PORTFOLIO_CONFIGURATION_HASH_EXCLUDED_KEYS = frozenset(
    {
        "hash_namespace",
        "namespace",
        "storage_hash",
        "update_hash",
        "storage_id",
        "storage_uid",
        "update_id",
        "update_uid",
        "data_node_storage_id",
        "data_node_storage_uid",
        "data_node_update_id",
        "data_node_update_uid",
        "data_source_id",
        "run_id",
        "run_timestamp",
        "created_at",
        "updated_at",
        "creation_date",
    }
)
PORTFOLIO_WEIGHT_SOURCE_COLUMN_ALIASES = {
    "weights_current": "weight",
    "weights_before": "weight_before",
}
