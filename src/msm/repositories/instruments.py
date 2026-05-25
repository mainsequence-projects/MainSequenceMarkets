from __future__ import annotations

import uuid
from typing import Any

from mainsequence.client.models_metatables import MetaTableCompiledSQLOperation

from msm.models import InstrumentsConfiguration

from .base import MarketsRepositoryContext, execute_markets_operation
from .crud import (
    build_create_model_operation,
    build_delete_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_update_model_operation,
)


def build_create_instruments_configuration_operation(
    context: MarketsRepositoryContext,
    *,
    configuration_key: str = "default",
    discount_curves_data_node_uid: uuid.UUID | str | None = None,
    reference_rates_fixings_data_node_uid: uuid.UUID | str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_create_model_operation(
        context,
        model=InstrumentsConfiguration,
        values={
            "configuration_key": configuration_key,
            "discount_curves_data_node_uid": discount_curves_data_node_uid,
            "reference_rates_fixings_data_node_uid": reference_rates_fixings_data_node_uid,
            "metadata_json": metadata_json,
        },
    )


def create_instruments_configuration(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_create_instruments_configuration_operation(context, **kwargs),
        context=context,
    )


def build_get_instruments_configuration_by_uid_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_get_model_by_uid_operation(context, model=InstrumentsConfiguration, uid=uid)


def build_search_instruments_configurations_operation(
    context: MarketsRepositoryContext,
    *,
    configuration_key: str | None = None,
    limit: int = 500,
) -> MetaTableCompiledSQLOperation:
    filters: dict[str, Any] = {}
    if configuration_key not in (None, ""):
        filters["configuration_key"] = configuration_key
    return build_search_model_operation(
        context,
        model=InstrumentsConfiguration,
        filters=filters,
        limit=limit,
    )


def search_instruments_configurations(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_search_instruments_configurations_operation(context, **kwargs),
        context=context,
    )


def build_update_instruments_configuration_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
    discount_curves_data_node_uid: uuid.UUID | str | None = None,
    reference_rates_fixings_data_node_uid: uuid.UUID | str | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> MetaTableCompiledSQLOperation:
    return build_update_model_operation(
        context,
        model=InstrumentsConfiguration,
        uid=uid,
        values={
            "discount_curves_data_node_uid": discount_curves_data_node_uid,
            "reference_rates_fixings_data_node_uid": reference_rates_fixings_data_node_uid,
            "metadata_json": metadata_json,
        },
    )


def update_instruments_configuration(
    context: MarketsRepositoryContext,
    **kwargs: Any,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_update_instruments_configuration_operation(context, **kwargs),
        context=context,
    )


def build_delete_instruments_configuration_operation(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> MetaTableCompiledSQLOperation:
    return build_delete_model_operation(context, model=InstrumentsConfiguration, uid=uid)


def delete_instruments_configuration(
    context: MarketsRepositoryContext,
    *,
    uid: uuid.UUID | str,
) -> dict[str, Any]:
    return execute_markets_operation(
        build_delete_instruments_configuration_operation(context, uid=uid),
        context=context,
    )


__all__ = [
    "build_create_instruments_configuration_operation",
    "build_delete_instruments_configuration_operation",
    "build_get_instruments_configuration_by_uid_operation",
    "build_search_instruments_configurations_operation",
    "build_update_instruments_configuration_operation",
    "create_instruments_configuration",
    "delete_instruments_configuration",
    "search_instruments_configurations",
    "update_instruments_configuration",
]
