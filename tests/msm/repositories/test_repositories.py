from __future__ import annotations

import uuid

import pytest

from msm.maintenance.models import MarketsMetaTableCatalogRow, MarketsMetaTableCatalogTable
from msm.models.registration import markets_meta_table_identifier
from msm.models import (
    AccountGroupTable,
    AccountTargetPortfolioTable,
    AccountTable,
    AssetTypeTable,
    AssetTable,
    OpenFigiAssetDetailsTable,
    PositionSetTable,
    markets_sqlalchemy_models,
)
from msm.repositories import MarketsMetaTableHandle, MarketsRepositoryContext
from msm.repositories.assets import (
    build_create_asset_operation,
    build_delete_asset_operation,
    build_get_asset_by_uid_operation,
    build_get_asset_by_unique_identifier_operation,
    build_search_assets_operation,
    build_upsert_asset_operation,
)
from msm.repositories.crud import (
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_upsert_model_operation,
)
from msm.repositories.accounts import (
    build_create_account_operation,
    build_create_account_target_portfolio_operation,
    build_create_position_set_operation,
)


@pytest.fixture(autouse=True)
def bind_test_meta_table_uids(monkeypatch) -> None:
    for model in [MarketsMetaTableCatalogTable, *markets_sqlalchemy_models()]:
        monkeypatch.setattr(model, "__metatable_uid__", str(uuid.uuid4()), raising=False)


def _repository_context() -> MarketsRepositoryContext:
    return MarketsRepositoryContext(
        limits={"max_rows": 100, "statement_timeout_ms": 5000},
    )


def _asset_table() -> MarketsMetaTableHandle:
    return _repository_context().table(AssetTable)


def test_repository_context_resolves_identifier_after_physical_binding(monkeypatch) -> None:
    identifier = markets_meta_table_identifier(AssetTypeTable)
    meta_table_uid = str(uuid.uuid4())
    context = MarketsRepositoryContext()

    monkeypatch.setitem(AssetTypeTable.__table__.info, "identifier", identifier)
    monkeypatch.setattr(AssetTypeTable, "__metatable_uid__", meta_table_uid, raising=False)
    monkeypatch.setattr(AssetTypeTable.__table__, "name", "backend_physical_asset_type")
    monkeypatch.setattr(
        AssetTypeTable.__table__,
        "fullname",
        "public.backend_physical_asset_type",
        raising=False,
    )

    assert context.meta_table_uid_for_model(AssetTypeTable) == meta_table_uid
    assert context.table(AssetTypeTable).meta_table_uid == meta_table_uid


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
    asset = _asset_table()

    operation = build_create_asset_operation(
        asset,
        unique_identifier="BTC",
        asset_type="crypto",
    )

    assert operation.operation == "insert"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == asset.meta_table_uid
    assert AssetTable.__table__.name in operation.statement.sql
    assert isinstance(operation.statement.parameters["uid"], uuid.UUID)
    assert operation.statement.parameters["unique_identifier"] == "BTC"
    assert "metadata_json" not in operation.statement.parameters


def test_asset_upsert_operation_uses_compiled_upsert_protocol() -> None:
    asset = _asset_table()

    operation = build_upsert_asset_operation(
        asset,
        unique_identifier="ETH",
        asset_type="crypto",
    )

    assert operation.operation == "upsert"
    assert operation.scope.tables[0].access == "write"
    assert "ON CONFLICT" in operation.statement.sql
    assert isinstance(operation.statement.parameters["uid"], uuid.UUID)
    assert "metadata_json" not in operation.statement.sql
    assert "metadata_json" not in operation.statement.parameters


def test_generic_upsert_operation_populates_python_defaults_for_backend_sql() -> None:
    context = MarketsRepositoryContext()
    row = MarketsMetaTableCatalogRow(
        namespace="ms-markets",
        table_name="ms_markets__asset",
        description=None,
        model_name="AssetTable",
        meta_table_uid=str(uuid.uuid4()),
        sdk_version="0.0.test",
    )

    operation = build_upsert_model_operation(
        context,
        model=MarketsMetaTableCatalogTable,
        values=row.to_payload(),
        conflict_columns=["table_name"],
    )

    assert isinstance(operation.statement.parameters["uid"], uuid.UUID)
    assert operation.statement.parameter_types["created_at"] == "timestamp with time zone"
    assert operation.statement.parameter_types["updated_at"] == "timestamp with time zone"
    assert operation.statement.parameters["created_at"].endswith("Z")
    assert operation.statement.parameters["updated_at"].endswith("Z")
    assert "updated_at =" in operation.statement.sql


def test_generic_upsert_operation_uses_physical_name_for_aliased_columns() -> None:
    context = _repository_context()

    operation = build_upsert_model_operation(
        context,
        model=OpenFigiAssetDetailsTable,
        values={
            "asset_uid": uuid.uuid4(),
            "metadata_text": None,
            "raw_payload": {"figi": "BBG00FNFPQH4"},
        },
        conflict_columns=["asset_uid"],
    )

    assert operation.operation == "upsert"
    assert "metadata_text" not in operation.statement.sql
    assert " metadata," in operation.statement.sql
    assert "metadata =" in operation.statement.sql
    assert operation.statement.parameters["metadata"] is None
    assert operation.statement.parameters["raw_payload"] == {"figi": "BBG00FNFPQH4"}


def test_position_set_operation_requires_utc_timestamp() -> None:
    context = _repository_context()
    account_target_portfolio_uid = uuid.uuid4()

    with pytest.raises(ValueError):
        build_create_position_set_operation(
            context,
            account_target_portfolio_uid=account_target_portfolio_uid,
            position_set_time="eod",
        )

    operation = build_create_position_set_operation(
        context,
        account_target_portfolio_uid=account_target_portfolio_uid,
        position_set_time="2026-05-25T00:00:00Z",
    )

    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        PositionSetTable,
    )
    assert operation.statement.parameter_types["position_set_time"] == "timestamp with time zone"
    assert operation.statement.parameters["position_set_time"] == "2026-05-25T00:00:00Z"


def test_account_target_portfolio_operation_uses_account_and_model_portfolio_links() -> None:
    context = _repository_context()
    account_uid = uuid.uuid4()
    model_portfolio_uid = uuid.uuid4()

    operation = build_create_account_target_portfolio_operation(
        context,
        unique_identifier="acct-main-target",
        account_uid=account_uid,
        account_model_portfolio_uid=model_portfolio_uid,
        display_name="Main Account Target",
    )

    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        AccountTargetPortfolioTable,
    )
    assert operation.statement.parameters["unique_identifier"] == "acct-main-target"
    assert operation.statement.parameters["account_uid"] == account_uid
    assert operation.statement.parameters["account_model_portfolio_uid"] == model_portfolio_uid


def test_account_create_operation_accepts_group_link_only() -> None:
    context = _repository_context()
    account_group_uid = uuid.uuid4()

    operation = build_create_account_operation(
        context,
        unique_identifier="acct-main",
        account_name="Main Account",
        account_group_uid=account_group_uid,
    )

    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        AccountGroupTable,
    )
    assert operation.scope.tables[1].meta_table_uid == context.meta_table_uid_for_model(
        AccountTable,
    )
    assert operation.statement.parameters["account_group_uid"] == account_group_uid
    assert "account_model_portfolio_uid" not in operation.statement.parameters


def test_generic_get_by_uid_uses_single_primary_key_when_uid_column_is_absent() -> None:
    context = _repository_context()
    asset_uid = uuid.uuid4()

    operation = build_get_model_by_uid_operation(
        context,
        model=OpenFigiAssetDetailsTable,
        uid=asset_uid,
    )

    assert operation.operation == "select"
    assert OpenFigiAssetDetailsTable.__table__.name in operation.statement.sql
    assert "asset_uid" in operation.statement.sql


def test_asset_get_by_unique_identifier_operation_uses_read_scope() -> None:
    asset = _asset_table()

    operation = build_get_asset_by_unique_identifier_operation(
        asset,
        unique_identifier="example-asset-btc",
    )

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == asset.meta_table_uid
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["unique_identifier_1"] == "example-asset-btc"


def test_asset_get_by_uid_operation_uses_read_scope() -> None:
    asset = _asset_table()
    asset_uid = uuid.uuid4()

    operation = build_get_asset_by_uid_operation(asset, uid=asset_uid)

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == asset.meta_table_uid
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["uid_1"] == asset_uid


def test_asset_search_operation_filters_by_identifier_and_type() -> None:
    asset = _asset_table()

    operation = build_search_assets_operation(
        asset,
        unique_identifier_contains="example-asset-",
        asset_type="crypto",
        limit=20,
    )

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == asset.meta_table_uid
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["asset_type_1"] == "crypto"
    assert operation.statement.parameters["unique_identifier_1"] == "example-asset-"
    assert operation.statement.parameters["param_1"] == 20


def test_asset_delete_operation_uses_write_scope() -> None:
    asset = _asset_table()
    asset_uid = uuid.uuid4()

    operation = build_delete_asset_operation(asset, uid=asset_uid)

    assert operation.operation == "delete"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == asset.meta_table_uid
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["uid_1"] == asset_uid
