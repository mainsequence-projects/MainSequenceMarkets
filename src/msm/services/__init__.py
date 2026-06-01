from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    "append_asset_category_membership": ".asset_categories",
    "bulk_delete_asset_category_records": ".asset_master_lists",
    "build_account_holdings_frame": ".holdings",
    "build_holdings_frame": ".holdings",
    "build_target_positions_frame": ".target_positions",
    "create_account": ".accounts",
    "create_account_group": ".reference_data",
    "create_account_model_portfolio": ".reference_data",
    "create_account_target_portfolio": ".accounts",
    "create_position_set": ".accounts",
    "create_asset": ".assets",
    "create_asset_category": ".asset_categories",
    "create_asset_category_record": ".asset_master_lists",
    "create_calendar": ".reference_data",
    "create_openfigi_details": ".provider_details",
    "create_order_manager": ".execution",
    "catalog_repository_context": ".catalog",
    "delete_account": ".accounts",
    "delete_account_group": ".reference_data",
    "delete_account_target_portfolio": ".accounts",
    "delete_position_set": ".accounts",
    "delete_asset": ".assets",
    "delete_asset_category": ".asset_categories",
    "delete_asset_category_record": ".asset_master_lists",
    "delete_catalog_table_row": ".catalog",
    "delete_index_record": ".asset_master_lists",
    "delete_calendar": ".reference_data",
    "delete_openfigi_details": ".provider_details",
    "get_account_by_unique_identifier": ".accounts",
    "get_account_by_uid": ".accounts",
    "get_account_frontend_detail_summary": ".accounts",
    "get_account_holdings_snapshot_response": ".accounts",
    "get_asset_frontend_detail_summary": ".asset_master_lists",
    "get_asset_by_uid": ".assets",
    "get_asset_by_unique_identifier": ".assets",
    "get_asset_category_by_uid": ".asset_categories",
    "get_asset_category_by_unique_identifier": ".asset_categories",
    "get_asset_category_frontend_detail": ".asset_master_lists",
    "get_asset_category_row": ".asset_master_lists",
    "get_asset_category_record": ".asset_master_lists",
    "get_index_record": ".asset_master_lists",
    "get_calendar_by_uid": ".reference_data",
    "get_openfigi_details_by_uid": ".provider_details",
    "list_asset_category_memberships": ".asset_categories",
    "list_account_rows_response": ".accounts",
    "list_asset_catalog_rows": ".asset_master_lists",
    "list_asset_rows": ".asset_master_lists",
    "list_asset_category_rows": ".asset_master_lists",
    "list_asset_category_rows_response": ".asset_master_lists",
    "list_catalog_table_rows": ".catalog",
    "list_catalog_tables": ".catalog",
    "list_index_catalog_rows": ".asset_master_lists",
    "register_index_from_figi": ".assets.openfigi",
    "register_index_future_from_figis": ".assets.openfigi",
    "remove_asset_category_membership": ".asset_categories",
    "remove_asset_category_membership_by_pair": ".asset_categories",
    "replace_asset_category_memberships": ".asset_categories",
    "search_account_groups": ".reference_data",
    "search_account_model_portfolios": ".reference_data",
    "search_account_target_portfolios": ".accounts",
    "search_accounts": ".accounts",
    "search_position_sets": ".accounts",
    "search_asset_categories": ".asset_categories",
    "search_assets": ".assets",
    "search_calendars": ".reference_data",
    "search_openfigi_details": ".provider_details",
    "search_order_managers": ".execution",
    "update_account": ".accounts",
    "update_account_group": ".reference_data",
    "update_asset": ".assets",
    "update_asset_category": ".asset_categories",
    "update_asset_category_record": ".asset_master_lists",
    "update_calendar": ".reference_data",
    "update_openfigi_details": ".provider_details",
    "update_order_manager": ".execution",
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
