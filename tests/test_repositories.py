from __future__ import annotations

import datetime as dt
import uuid

from msm.meta_tables import markets_meta_table_fullname
from msm.models import Asset, Order, markets_sqlalchemy_models
from msm.repositories import MarketsRepositoryContext
from msm.repositories.assets import (
    build_create_asset_operation,
    build_delete_asset_operation,
    build_get_asset_by_uid_operation,
    build_get_asset_by_unique_identifier_operation,
    build_search_assets_operation,
    build_upsert_asset_operation,
)
from msm.repositories.crud import build_search_model_operation
from msm.repositories.execution import build_create_order_operation


def _repository_context() -> MarketsRepositoryContext:
    return MarketsRepositoryContext(
        target_meta_table_uid_by_fullname={
            markets_meta_table_fullname(model): str(uuid.uuid4())
            for model in markets_sqlalchemy_models()
        },
        limits={"max_rows": 100, "statement_timeout_ms": 5000},
    )


def test_generic_search_operation_compiles_for_every_market_model() -> None:
    context = _repository_context()

    for model in markets_sqlalchemy_models():
        operation = build_search_model_operation(context, model=model, limit=10)

        assert operation.operation == "select"
        assert operation.limits is not None
        assert operation.limits.max_rows == 100
        assert operation.scope.tables[0].access == "read"
        assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(model)
        assert model.__table__.name in operation.statement.sql


def test_asset_create_operation_uses_write_scope() -> None:
    context = _repository_context()

    operation = build_create_asset_operation(
        context,
        unique_identifier="BTC",
        asset_type="crypto",
    )

    assert operation.operation == "insert"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(Asset)
    assert Asset.__table__.name in operation.statement.sql
    assert operation.statement.parameters["unique_identifier"] == "BTC"
    assert "metadata_json" not in operation.statement.parameters


def test_asset_upsert_operation_uses_compiled_upsert_protocol() -> None:
    context = _repository_context()

    operation = build_upsert_asset_operation(
        context,
        unique_identifier="ETH",
        asset_type="crypto",
    )

    assert operation.operation == "upsert"
    assert operation.scope.tables[0].access == "write"
    assert "ON CONFLICT" in operation.statement.sql
    assert "metadata_json" not in operation.statement.sql
    assert "metadata_json" not in operation.statement.parameters


def test_asset_get_by_unique_identifier_operation_uses_read_scope() -> None:
    context = _repository_context()

    operation = build_get_asset_by_unique_identifier_operation(
        context,
        unique_identifier="example-asset-btc",
    )

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(Asset)
    assert Asset.__table__.name in operation.statement.sql
    assert operation.statement.parameters["unique_identifier_1"] == "example-asset-btc"


def test_asset_get_by_uid_operation_uses_read_scope() -> None:
    context = _repository_context()
    asset_uid = uuid.uuid4()

    operation = build_get_asset_by_uid_operation(context, uid=asset_uid)

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(Asset)
    assert Asset.__table__.name in operation.statement.sql
    assert operation.statement.parameters["uid_1"] == asset_uid


def test_asset_search_operation_filters_by_identifier_and_type() -> None:
    context = _repository_context()

    operation = build_search_assets_operation(
        context,
        unique_identifier_contains="example-asset-",
        asset_type="crypto",
        limit=20,
    )

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(Asset)
    assert Asset.__table__.name in operation.statement.sql
    assert operation.statement.parameters["asset_type_1"] == "crypto"
    assert operation.statement.parameters["unique_identifier_1"] == "example-asset-"
    assert operation.statement.parameters["param_1"] == 20


def test_asset_delete_operation_uses_write_scope() -> None:
    context = _repository_context()
    asset_uid = uuid.uuid4()

    operation = build_delete_asset_operation(context, uid=asset_uid)

    assert operation.operation == "delete"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(Asset)
    assert Asset.__table__.name in operation.statement.sql
    assert operation.statement.parameters["uid_1"] == asset_uid


def test_order_create_operation_compiles_required_execution_fields() -> None:
    context = _repository_context()
    order_time = dt.datetime(2026, 5, 25, 10, 0, tzinfo=dt.UTC)

    operation = build_create_order_operation(
        context,
        order_remote_id="remote-1",
        client_order_id="client-1",
        order_type="market",
        order_time=order_time,
        order_side=1,
        quantity="1.5",
        asset_unique_identifier="BTC",
    )

    assert operation.operation == "insert"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(Order)
    assert Order.__table__.name in operation.statement.sql
    assert operation.statement.parameters["client_order_id"] == "client-1"
