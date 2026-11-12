from __future__ import annotations

import datetime as dt
import uuid

import pytest
from metatables import DataSourceResolutionError
from sqlalchemy import DateTime, Index, String, select
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.models.registration import markets_meta_table_identifier
from msm.models import (
    AccountTable,
    AssetTypeTable,
    AssetTable,
    OpenFigiAssetDetailsTable,
    PortfolioGroupMembershipTable,
    PortfolioGroupTable,
    PortfolioTable,
    markets_sqlalchemy_models,
)
from msm.repositories import (
    MarketsMetaTableHandle,
    MarketsRepositoryContext,
    compile_markets_statement,
)
from msm.repositories.assets import (
    build_create_asset_operation,
    build_delete_asset_operation,
    build_get_asset_by_uid_operation,
    build_get_asset_by_unique_identifier_operation,
    build_search_assets_operation,
    build_upsert_asset_operation,
)
from msm.repositories.asset_categories import (
    build_replace_asset_category_memberships_operations,
    replace_asset_category_memberships,
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


OTHER_DATA_SOURCE_UID = str(uuid.UUID("00000000-0000-0000-0000-000000000002"))

pytestmark = pytest.mark.usefixtures("offline_postgresql_runtime")


@pytest.fixture(autouse=True)
def bind_test_meta_table_uids(monkeypatch) -> None:
    for model in [RepositoryDefaultTable, *markets_sqlalchemy_models()]:
        monkeypatch.setattr(model, "__metatable_uid__", str(uuid.uuid4()), raising=False)


def _repository_context(data_source_uid: str | None = None) -> MarketsRepositoryContext:
    return MarketsRepositoryContext(
        data_source_uid=data_source_uid,
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


def test_generic_search_operation_compiles_for_every_market_model(
    offline_postgresql_runtime,
) -> None:
    context = _repository_context()
    runtime_data_source_uid = offline_postgresql_runtime.require_data_source_uid()

    for model in markets_sqlalchemy_models():
        operation = build_search_model_operation(context, model=model, limit=10, offset=5)

        assert operation.operation == "select"
        assert operation.data_source_uid == runtime_data_source_uid
        assert operation.dialect == "postgresql"
        assert operation.statement.paramstyle == "pyformat"
        assert operation.limits is not None
        assert operation.limits.max_rows == 100
        assert operation.limits.statement_timeout_ms == 5000
        assert model.__table__.name in operation.statement.sql
        assert "LIMIT" in operation.statement.sql
        assert "OFFSET" in operation.statement.sql


def test_explicit_data_source_must_match_runtime_unless_dialect_is_supplied(
    offline_postgresql_runtime,
) -> None:
    statement = select(AssetTable.uid)
    runtime_data_source_uid = offline_postgresql_runtime.require_data_source_uid()

    matching = compile_markets_statement(
        statement,
        context=_repository_context(runtime_data_source_uid),
        operation="select",
    )
    assert matching.data_source_uid == runtime_data_source_uid
    assert matching.dialect == "postgresql"

    with pytest.raises(DataSourceResolutionError):
        compile_markets_statement(
            statement,
            context=_repository_context(OTHER_DATA_SOURCE_UID),
            operation="select",
        )

    offline = compile_markets_statement(
        statement,
        context=_repository_context(OTHER_DATA_SOURCE_UID),
        operation="select",
        dialect="postgresql",
    )
    assert offline.data_source_uid == OTHER_DATA_SOURCE_UID
    assert offline.dialect == "postgresql"


def test_generic_count_operation_compiles_for_filtered_model() -> None:
    context = _repository_context()

    operation = build_count_model_operation(
        context,
        model=AccountTable,
        filters={"account_is_active": True},
    )

    assert operation.operation == "select"
    assert "count" in operation.statement.sql.lower()
    assert AccountTable.__table__.name in operation.statement.sql


def test_asset_create_operation_compiles_insert() -> None:
    asset = _asset_table()

    operation = build_create_asset_operation(
        asset,
        unique_identifier="BTC",
        asset_type="crypto",
    )

    assert operation.operation == "insert"
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


def test_upsert_updates_a_row_only_when_a_value_differs() -> None:
    operation = build_upsert_model_operation(
        _repository_context(),
        model=RepositoryDefaultTable,
        values={"unique_identifier": "test-defaults", "display_name": "Test Defaults"},
        conflict_columns=["unique_identifier"],
    )
    sql = " ".join(operation.statement.sql.split())

    # The onupdate column is set with the change but never makes the row differ;
    # the conflict key and the primary key are neither set nor compared.
    assert (
        "ON CONFLICT (unique_identifier) DO UPDATE SET display_name = excluded.display_name, "
        "updated_at = %(param_3)s::TIMESTAMP WITH TIME ZONE "
        "WHERE ms_markets__test_repositorydefault.display_name IS DISTINCT FROM "
        "excluded.display_name RETURNING"
    ) in sql
    assert "updated_at IS DISTINCT FROM" not in sql
    assert "unique_identifier IS DISTINCT FROM" not in sql
    assert "uid IS DISTINCT FROM" not in sql
    # Unchanged rows, which the conditional update leaves out of RETURNING, come back
    # from the statement's own snapshot, in input order, each with its status.
    assert "upsert_existing AS (SELECT" in sql
    assert "UNION ALL SELECT upsert_existing.uid" in sql
    assert "'unchanged' AS upsert_status" in sql
    assert "THEN 'updated' ELSE 'inserted' END AS upsert_status" in sql
    assert sql.endswith("ORDER BY upsert_input.upsert_index")


def test_upsert_of_a_none_value_differs_from_any_stored_value() -> None:
    operation = build_upsert_model_operation(
        _repository_context(),
        model=OpenFigiAssetDetailsTable,
        values={"asset_uid": uuid.uuid4(), "metadata_text": None, "figi": "BBG00FNFPQH4"},
        conflict_columns=["asset_uid"],
    )
    sql = " ".join(operation.statement.sql.split())

    assert "openfigiassetdetails.metadata IS NOT NULL" in sql
    assert "openfigiassetdetails.figi IS DISTINCT FROM excluded.figi" in sql


def test_upsert_compares_json_columns_as_jsonb() -> None:
    """The Markets migrations create ``json`` columns, which have no equality operator."""

    operation = build_upsert_model_operation(
        _repository_context(),
        model=OpenFigiAssetDetailsTable,
        values={"asset_uid": uuid.uuid4(), "raw_payload": {"figi": "BBG00FNFPQH4"}},
        conflict_columns=["asset_uid"],
    )
    sql = " ".join(operation.statement.sql.split())

    assert (
        "CAST(ms_markets__openfigiassetdetails.raw_payload AS JSONB) IS DISTINCT FROM "
        "CAST(excluded.raw_payload AS JSONB)"
    ) in sql


def test_upsert_of_keys_only_does_nothing_on_conflict() -> None:
    operation = build_upsert_portfolio_group_membership_operation(
        _repository_context(),
        portfolio_group_uid=uuid.uuid4(),
        portfolio_uid=uuid.uuid4(),
    )

    assert "ON CONFLICT (portfolio_group_uid, portfolio_uid) DO NOTHING" in operation.statement.sql


def test_upsert_reads_back_a_row_a_concurrent_write_hid(monkeypatch) -> None:
    """A row committed after the statement's snapshot with the same values is unchanged."""

    from msm.repositories import crud

    reads = []
    monkeypatch.setattr(
        crud,
        "execute_markets_write",
        lambda write, *, context: {
            "ok": True,
            "rows": [{"unique_identifier": "A", "upsert_status": "inserted", "upsert_index": 0}],
            "row_count": 1,
            "truncated": False,
        },
    )

    def reread(operation, *, context):
        reads.append(operation)
        return {"rows": [{"unique_identifier": "B", "upsert_status": "unchanged", "upsert_index": 1}]}

    monkeypatch.setattr(crud, "execute_markets_operation", reread)

    result = crud.bulk_upsert_model(
        _repository_context(),
        model=AssetTable,
        values=[{"unique_identifier": "A"}, {"unique_identifier": "B"}],
        conflict_columns=("unique_identifier",),
    )

    assert result["rows"] == [
        {"unique_identifier": "A", "upsert_status": "inserted"},
        {"unique_identifier": "B", "upsert_status": "unchanged"},
    ]
    assert result["row_count"] == 2
    [operation] = reads
    assert operation.operation == "select"
    assert "'unchanged' AS upsert_status" in operation.statement.sql
    assert "B" in operation.statement.parameters.values()
    assert "A" not in operation.statement.parameters.values()


def test_a_truncated_upsert_result_is_not_read_back(monkeypatch) -> None:
    from msm.repositories import crud

    monkeypatch.setattr(
        crud,
        "execute_markets_write",
        lambda write, *, context: {
            "rows": [{"unique_identifier": "A", "upsert_status": "inserted", "upsert_index": 0}],
            "truncated": True,
        },
    )
    monkeypatch.setattr(crud, "execute_markets_operation", pytest.fail)

    result = crud.bulk_upsert_model(
        _repository_context(),
        model=AssetTable,
        values=[{"unique_identifier": "A"}, {"unique_identifier": "B"}],
        conflict_columns=("unique_identifier",),
    )

    assert result["rows"] == [{"unique_identifier": "A", "upsert_status": "inserted"}]


def test_statuses_are_read_first_only_on_sqlite() -> None:
    with pytest.raises(ValueError, match="only on SQLite"):
        build_upsert_model_operation(
            _repository_context(),
            model=AssetTable,
            values={"unique_identifier": "A"},
            conflict_columns=["unique_identifier"],
            statuses=["inserted"],
        )
    with pytest.raises(ValueError, match="needs the status of every row"):
        build_upsert_model_operation(
            _repository_context(OTHER_DATA_SOURCE_UID),
            model=AssetTable,
            values={"unique_identifier": "A"},
            conflict_columns=["unique_identifier"],
            dialect="sqlite",
        )


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
    assert "ON CONFLICT" in operation.statement.sql
    assert operation.statement.sql.count("display_name") >= 2


def test_replace_asset_category_memberships_compiles_two_operations_and_deduplicates() -> None:
    context = _repository_context()
    category_uid = uuid.uuid4()
    first_asset_uid = uuid.uuid4()
    second_asset_uid = uuid.uuid4()

    operations = build_replace_asset_category_memberships_operations(
        context,
        category_uid=category_uid,
        asset_uids=[first_asset_uid, str(second_asset_uid), first_asset_uid],
    )

    assert [operation.operation for operation in operations] == ["upsert", "delete"]
    assert "ON CONFLICT (category_uid, asset_uid)" in operations[0].statement.sql
    assert "NOT IN" in operations[1].statement.sql
    assert {
        value
        for key, value in operations[0].statement.parameters.items()
        if key.startswith("asset_uid_m")
    } == {first_asset_uid, second_asset_uid}
    assert {
        value
        for key, value in operations[1].statement.parameters.items()
        if key.startswith("asset_uid_")
    } == {first_asset_uid, second_asset_uid}


def test_replace_asset_category_memberships_executes_bulk_upsert_before_stale_delete(
    monkeypatch,
) -> None:
    context = _repository_context()
    category_uid = uuid.uuid4()
    asset_uids = [uuid.uuid4(), uuid.uuid4()]
    calls = []
    upsert_result = {
        "rows": [
            {
                "uid": str(uuid.uuid4()),
                "category_uid": str(category_uid),
                "asset_uid": str(asset_uid),
            }
            for asset_uid in asset_uids
        ]
    }

    def fake_upsert(active_context, *, model, values, conflict_columns):
        calls.append(("upsert", active_context, values, conflict_columns))
        return upsert_result

    def fake_execute(operation, *, context):
        calls.append((operation.operation, context, None, None))
        return {"rows": []}

    monkeypatch.setattr("msm.repositories.asset_categories.bulk_upsert_model", fake_upsert)
    monkeypatch.setattr(
        "msm.repositories.asset_categories.execute_markets_operation",
        fake_execute,
    )

    results = replace_asset_category_memberships(
        context,
        category_uid=category_uid,
        asset_uids=asset_uids,
    )

    assert [call[0] for call in calls] == ["upsert", "delete"]
    assert all(call[1] is context for call in calls)
    assert calls[0][2] == [
        {"category_uid": category_uid, "asset_uid": asset_uid} for asset_uid in asset_uids
    ]
    assert calls[0][3] == ("category_uid", "asset_uid")
    assert results == [upsert_result, {"rows": []}]


def test_replace_asset_category_memberships_empty_set_executes_one_delete(
    monkeypatch,
) -> None:
    context = _repository_context()
    calls = []

    def fake_execute(operation, *, context):
        calls.append((operation, context))
        return {"rows": []}

    monkeypatch.setattr(
        "msm.repositories.asset_categories.execute_markets_operation",
        fake_execute,
    )

    results = replace_asset_category_memberships(
        context,
        category_uid=uuid.uuid4(),
        asset_uids=[],
    )

    assert len(calls) == 1
    assert calls[0][0].operation == "delete"
    assert "NOT IN" not in calls[0][0].statement.sql
    assert results == [{"rows": []}]


def test_portfolio_group_upsert_operation_uses_unique_identifier_conflict() -> None:
    context = _repository_context()

    operation = build_upsert_portfolio_group_operation(
        context,
        unique_identifier="risk-parity",
        display_name="Risk Parity",
    )

    assert operation.operation == "upsert"
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
    assert "ON CONFLICT" in operation.statement.sql
    assert "portfolio_group_uid" in operation.statement.sql
    assert "portfolio_uid" in operation.statement.sql


def test_portfolio_group_search_operation_uses_or_search() -> None:
    context = _repository_context()

    operation = build_search_portfolio_groups_operation(context, search="core", limit=10)

    assert operation.operation == "select"
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


def test_asset_get_by_unique_identifier_operation_compiles_select() -> None:
    asset = _asset_table()

    operation = build_get_asset_by_unique_identifier_operation(
        asset,
        unique_identifier="example-asset-btc",
    )

    assert operation.operation == "select"
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["unique_identifier_1"] == "example-asset-btc"


def test_asset_get_by_uid_operation_compiles_select() -> None:
    asset = _asset_table()
    asset_uid = uuid.uuid4()

    operation = build_get_asset_by_uid_operation(asset, uid=asset_uid)

    assert operation.operation == "select"
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
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["asset_type_1"] == "crypto"
    assert "example-asset-" in set(operation.statement.parameters.values())
    assert operation.statement.parameters["param_1"] == 20


def test_asset_delete_operation_compiles_delete() -> None:
    asset = _asset_table()
    asset_uid = uuid.uuid4()

    operation = build_delete_asset_operation(asset, uid=asset_uid)

    assert operation.operation == "delete"
    assert AssetTable.__table__.name in operation.statement.sql
    assert operation.statement.parameters["uid_1"] == asset_uid
