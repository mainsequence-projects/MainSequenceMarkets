from __future__ import annotations

from typing import Any

from msm.repositories import MarketsRepositoryContext
from msm.repositories.account_groups import (
    create_account_group as repository_create_account_group,
    create_account_model_portfolio as repository_create_account_model_portfolio,
    delete_account_group as repository_delete_account_group,
    search_account_groups as repository_search_account_groups,
    search_account_model_portfolios as repository_search_account_model_portfolios,
    update_account_group as repository_update_account_group,
)
from msm.repositories.calendars import (
    create_calendar as repository_create_calendar,
    delete_calendar as repository_delete_calendar,
    get_calendar_by_uid as repository_get_calendar_by_uid,
    search_calendars as repository_search_calendars,
    update_calendar as repository_update_calendar,
)
from msm.repositories.instruments import (
    create_instruments_configuration as repository_create_instruments_configuration,
    delete_instruments_configuration as repository_delete_instruments_configuration,
    search_instruments_configurations as repository_search_instruments_configurations,
    update_instruments_configuration as repository_update_instruments_configuration,
)


def create_calendar(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_create_calendar(context, **kwargs)


def get_calendar_by_uid(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_get_calendar_by_uid(context, **kwargs)


def search_calendars(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_search_calendars(context, **kwargs)


def update_calendar(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_update_calendar(context, **kwargs)


def delete_calendar(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_delete_calendar(context, **kwargs)


def create_account_model_portfolio(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_create_account_model_portfolio(context, **kwargs)


def search_account_model_portfolios(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_search_account_model_portfolios(context, **kwargs)


def create_account_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_create_account_group(context, **kwargs)


def search_account_groups(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_search_account_groups(context, **kwargs)


def update_account_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_update_account_group(context, **kwargs)


def delete_account_group(context: MarketsRepositoryContext, **kwargs: Any) -> dict[str, Any]:
    return repository_delete_account_group(context, **kwargs)


def create_instruments_configuration(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_create_instruments_configuration(context, **kwargs)


def search_instruments_configurations(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_search_instruments_configurations(context, **kwargs)


def update_instruments_configuration(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_update_instruments_configuration(context, **kwargs)


def delete_instruments_configuration(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return repository_delete_instruments_configuration(context, **kwargs)


__all__ = [
    "create_account_group",
    "create_account_model_portfolio",
    "create_calendar",
    "create_instruments_configuration",
    "delete_account_group",
    "delete_calendar",
    "delete_instruments_configuration",
    "get_calendar_by_uid",
    "search_account_groups",
    "search_account_model_portfolios",
    "search_calendars",
    "search_instruments_configurations",
    "update_account_group",
    "update_calendar",
    "update_instruments_configuration",
]
