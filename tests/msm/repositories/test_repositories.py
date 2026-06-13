from __future__ import annotations

import datetime as dt
import uuid

import pytest
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.models.registration import markets_meta_table_identifier
from msm.models import (
    AccountGroupTable,
    AccountTargetAllocationTable,
    AccountTable,
    AssetTypeTable,
    AssetTable,
    OpenFigiAssetDetailsTable,
    PositionSetTable,
    PortfolioGroupMembershipTable,
    PortfolioGroupTable,
    PortfolioTable,
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
    build_bulk_upsert_model_operation,
    build_count_model_operation,
    build_get_model_by_uid_operation,
    build_search_model_operation,
    build_upsert_model_operation,
)
from msm.repositories.accounts import (
    build_create_account_operation,
    build_create_account_target_allocation_operation,
    build_create_position_set_operation,
)
from msm.repositories.portfolios import (
    build_delete_portfolio_group_membership_by_pair_operation,
    build_list_portfolio_groups_for_portfolio_operation,
    build_list_portfolios_for_group_operation,
    build_search_portfolio_groups_operation,
    build_upsert_portfolio_group_membership_operation,
    build_upsert_portfolio_group_operation,
)


class RepositoryDefaultTable(MarketsMetaTableMixin, MarketsBase):
    __metatable_identifier__ = "test.RepositoryDefault"
    __metatable_description__ = (
        "Repository test table with Python defaults used to verify generic "
        "compiled SQL insert and upsert behavior."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        Index(None, "unique_identifier", unique=True),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
    )
    unique_identifier: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


@pytest.fixture(autouse=True)
def bind_test_meta_table_uids(monkeypatch) -> None:
    for model in [RepositoryDefaultTable, *markets_sqlalchemy_models()]:
        monkeypatch.setattr(model, "__metatable_uid__", str(uuid.uuid4()), raising=False)


def _repository_context() -> MarketsRepositoryContext:
    return MarketsRepositoryContext(
        data_source_uid=str(uuid.UUID("00000000-0000-0000-0000-000000000001")),
        limits={"max_rows": 100, "statement_timeout_ms": 5000},
    )


def _asset_table() -> MarketsMetaTableHandle:
    return _repository_context().table(AssetTable)


def test_repository_context_resolves_identifier_after_physical_binding(monkeypatch) -> None:
    identifier = markets_meta_table_identifier(AssetTypeTable)
    meta_table_uid = str(uuid.uuid4())
    context = _repository_context()

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
        operation = build_search_model_operation(context, model=model, limit=10, offset=5)

        assert operation.operation == "select"
        assert operation.limits is not None
        assert operation.limits.max_rows == 100
        assert operation.scope.tables[0].access == "read"
        assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(model)
        assert model.__table__.name in operation.statement.sql
        assert "LIMIT" in operation.statement.sql
        assert "OFFSET" in operation.statement.sql


def test_generic_count_operation_compiles_for_filtered_model() -> None:
    context = _repository_context()

    operation = build_count_model_operation(
        context,
        model=AccountTable,
        filters={"account_is_active": True},
    )

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        AccountTable
    )
    assert "count" in operation.statement.sql.lower()
    assert AccountTable.__table__.name in operation.statement.sql


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
    context = _repository_context()

    operation = build_upsert_model_operation(
        context,
        model=RepositoryDefaultTable,
        values={
            "unique_identifier": "test-defaults",
            "display_name": "Test Defaults",
        },
        conflict_columns=["unique_identifier"],
    )

    assert isinstance(operation.statement.parameters["uid"], uuid.UUID)
    assert operation.statement.parameter_types["created_at"] == "timestamp with time zone"
    assert operation.statement.parameter_types["updated_at"] == "timestamp with time zone"
    assert operation.statement.parameters["created_at"].endswith("Z")
    assert operation.statement.parameters["updated_at"].endswith("Z")
    assert "updated_at =" in operation.statement.sql


def test_generic_bulk_upsert_operation_compiles_one_statement_for_many_rows() -> None:
    context = _repository_context()
    rows = [
        {"unique_identifier": "test-bulk-1", "display_name": "Test Bulk 1"},
        {"unique_identifier": "test-bulk-2", "display_name": "Test Bulk 2"},
    ]

    operation = build_bulk_upsert_model_operation(
        context,
        model=RepositoryDefaultTable,
        values=rows,
        conflict_columns=["unique_identifier"],
    )

    assert operation.operation == "upsert"
    assert operation.scope.tables[0].access == "write"
    assert "ON CONFLICT" in operation.statement.sql
    assert operation.statement.sql.count("display_name") >= 2


def test_portfolio_group_upsert_operation_uses_unique_identifier_conflict() -> None:
    context = _repository_context()

    operation = build_upsert_portfolio_group_operation(
        context,
        unique_identifier="risk-parity",
        display_name="Risk Parity",
    )

    assert operation.operation == "upsert"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        PortfolioGroupTable
    )
    assert "ON CONFLICT" in operation.statement.sql
    assert "unique_identifier" in operation.statement.sql
    assert isinstance(operation.statement.parameters["uid"], uuid.UUID)


def test_portfolio_group_membership_upsert_operation_uses_pair_conflict() -> None:
    context = _repository_context()
    portfolio_group_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()

    operation = build_upsert_portfolio_group_membership_operation(
        context,
        portfolio_group_uid=portfolio_group_uid,
        portfolio_uid=portfolio_uid,
    )

    assert operation.operation == "upsert"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        PortfolioGroupMembershipTable
    )
    assert "ON CONFLICT" in operation.statement.sql
    assert "portfolio_group_uid" in operation.statement.sql
    assert "portfolio_uid" in operation.statement.sql


def test_portfolio_group_search_operation_uses_or_search() -> None:
    context = _repository_context()

    operation = build_search_portfolio_groups_operation(context, search="core", limit=10)

    assert operation.operation == "select"
    assert operation.scope.tables[0].access == "read"
    assert PortfolioGroupTable.__table__.name in operation.statement.sql
    assert " OR " in operation.statement.sql


def test_portfolio_group_relationship_queries_join_membership_table() -> None:
    context = _repository_context()
    portfolio_group_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()

    portfolios_operation = build_list_portfolios_for_group_operation(
        context,
        portfolio_group_uid=portfolio_group_uid,
    )
    groups_operation = build_list_portfolio_groups_for_portfolio_operation(
        context,
        portfolio_uid=portfolio_uid,
    )

    assert portfolios_operation.operation == "select"
    assert groups_operation.operation == "select"
    assert PortfolioTable.__table__.name in portfolios_operation.statement.sql
    assert PortfolioGroupTable.__table__.name in groups_operation.statement.sql
    assert PortfolioGroupMembershipTable.__table__.name in portfolios_operation.statement.sql
    assert PortfolioGroupMembershipTable.__table__.name in groups_operation.statement.sql


def test_portfolio_group_membership_delete_by_pair_operation_is_scoped_to_pair() -> None:
    context = _repository_context()
    portfolio_group_uid = uuid.uuid4()
    portfolio_uid = uuid.uuid4()

    operation = build_delete_portfolio_group_membership_by_pair_operation(
        context,
        portfolio_group_uid=portfolio_group_uid,
        portfolio_uid=portfolio_uid,
    )

    assert operation.operation == "delete"
    assert operation.scope.tables[0].access == "write"
    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        PortfolioGroupMembershipTable
    )
    assert "portfolio_group_uid" in operation.statement.sql
    assert "portfolio_uid" in operation.statement.sql


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
    account_target_allocation_uid = uuid.uuid4()

    with pytest.raises(ValueError):
        build_create_position_set_operation(
            context,
            account_target_allocation_uid=account_target_allocation_uid,
            position_set_time="eod",
        )

    operation = build_create_position_set_operation(
        context,
        account_target_allocation_uid=account_target_allocation_uid,
        position_set_time="2026-05-25T00:00:00Z",
    )

    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        PositionSetTable,
    )
    assert operation.statement.parameter_types["position_set_time"] == "timestamp with time zone"
    assert operation.statement.parameters["position_set_time"] == "2026-05-25T00:00:00Z"


def test_account_target_allocation_operation_uses_account_and_allocation_model_links() -> None:
    context = _repository_context()
    account_uid = uuid.uuid4()
    allocation_model_uid = uuid.uuid4()

    operation = build_create_account_target_allocation_operation(
        context,
        unique_identifier="acct-main-target",
        account_uid=account_uid,
        account_allocation_model_uid=allocation_model_uid,
        display_name="Main Account Target",
    )

    assert operation.scope.tables[0].meta_table_uid == context.meta_table_uid_for_model(
        AccountTargetAllocationTable,
    )
    assert operation.statement.parameters["unique_identifier"] == "acct-main-target"
    assert operation.statement.parameters["account_uid"] == account_uid
    assert operation.statement.parameters["account_allocation_model_uid"] == allocation_model_uid


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
    assert "account_allocation_model_uid" not in operation.statement.parameters


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
    assert "example-asset-" in set(operation.statement.parameters.values())
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
