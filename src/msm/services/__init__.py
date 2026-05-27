from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "append_asset_category_membership": ".asset_categories",
    "build_account_holdings_frame": ".holdings",
    "build_fund_holdings_frame": ".holdings",
    "build_holdings_frame": ".holdings",
    "build_target_positions_frame": ".target_positions",
    "create_account": ".accounts",
    "create_account_group": ".reference_data",
    "create_account_model_portfolio": ".reference_data",
    "create_account_target_position_assignment": ".accounts",
    "create_asset": ".assets",
    "create_asset_category": ".asset_categories",
    "create_calendar": ".reference_data",
    "create_execution_error": ".execution",
    "create_fund": ".funds",
    "create_instruments_configuration": ".reference_data",
    "create_openfigi_details": ".provider_details",
    "create_order": ".execution",
    "create_order_manager": ".execution",
    "create_order_status_event": ".execution",
    "create_order_target_quantity": ".execution",
    "create_portfolio": ".portfolios",
    "create_portfolio_asset_detail": ".portfolios",
    "create_portfolio_metadata": ".market_metadata",
    "create_rebalance_strategy_metadata": ".market_metadata",
    "create_signal_metadata": ".market_metadata",
    "create_trade": ".execution",
    "delete_account": ".accounts",
    "delete_account_group": ".reference_data",
    "delete_account_target_position_assignment": ".accounts",
    "delete_asset": ".assets",
    "delete_asset_category": ".asset_categories",
    "delete_calendar": ".reference_data",
    "delete_instruments_configuration": ".reference_data",
    "delete_openfigi_details": ".provider_details",
    "delete_portfolio": ".portfolios",
    "delete_portfolio_asset_detail": ".portfolios",
    "delete_portfolio_metadata": ".market_metadata",
    "delete_rebalance_strategy_metadata": ".market_metadata",
    "delete_signal_metadata": ".market_metadata",
    "get_account_by_unique_identifier": ".accounts",
    "get_asset_by_uid": ".assets",
    "get_asset_by_unique_identifier": ".assets",
    "get_asset_category_by_uid": ".asset_categories",
    "get_asset_category_by_unique_identifier": ".asset_categories",
    "get_calendar_by_uid": ".reference_data",
    "get_funds_by_account": ".funds",
    "get_funds_by_portfolio": ".funds",
    "get_openfigi_details_by_uid": ".provider_details",
    "get_portfolio_by_unique_identifier": ".portfolios",
    "get_portfolio_metadata_by_unique_identifier": ".market_metadata",
    "holdings_source_table_kwargs": ".holdings",
    "initialize_data_node_source_table": ".holdings",
    "list_asset_category_memberships": ".asset_categories",
    "remove_asset_category_membership": ".asset_categories",
    "remove_asset_category_membership_by_pair": ".asset_categories",
    "replace_asset_category_memberships": ".asset_categories",
    "search_account_groups": ".reference_data",
    "search_account_model_portfolios": ".reference_data",
    "search_account_target_position_assignments": ".accounts",
    "search_accounts": ".accounts",
    "search_asset_categories": ".asset_categories",
    "search_assets": ".assets",
    "search_calendars": ".reference_data",
    "search_execution_errors": ".execution",
    "search_instruments_configurations": ".reference_data",
    "search_openfigi_details": ".provider_details",
    "search_order_managers": ".execution",
    "search_order_status_events": ".execution",
    "search_order_target_quantities": ".execution",
    "search_orders": ".execution",
    "search_portfolio_asset_details": ".portfolios",
    "search_portfolio_metadata": ".market_metadata",
    "search_portfolios": ".portfolios",
    "search_rebalance_strategy_metadata": ".market_metadata",
    "search_signal_metadata": ".market_metadata",
    "search_trades": ".execution",
    "target_positions_source_table_kwargs": ".target_positions",
    "update_account": ".accounts",
    "update_account_group": ".reference_data",
    "update_asset": ".assets",
    "update_asset_category": ".asset_categories",
    "update_calendar": ".reference_data",
    "update_instruments_configuration": ".reference_data",
    "update_openfigi_details": ".provider_details",
    "update_order": ".execution",
    "update_order_manager": ".execution",
    "update_portfolio": ".portfolios",
    "update_portfolio_asset_detail": ".portfolios",
    "update_portfolio_metadata": ".market_metadata",
    "update_rebalance_strategy_metadata": ".market_metadata",
    "update_signal_metadata": ".market_metadata",
    "upsert_asset": ".assets",
    "validate_holdings_frame": ".holdings",
    "validate_target_position_payload": ".target_positions",
    "validate_target_positions_frame": ".target_positions",
}


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_EXPORTS[name], __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


__all__ = sorted(_EXPORTS)
