"""ms-markets 3.x writes each renamed UID column under both names (ADR 0048)."""

from __future__ import annotations

import importlib
import uuid

import pytest

from msm.models import AssetTable, PortfolioTable, markets_sqlalchemy_models
from msm.repositories.accounts import build_create_account_operation, build_update_account_operation
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import (
    build_bulk_upsert_model_operation,
    build_create_model_operation,
    build_update_model_operation,
    build_upsert_model_operation,
    mirror_renamed_columns,
)
from msm.repositories.portfolios import build_create_portfolio_operation
from msm_pricing.models.market_data_bindings import PricingMarketDataSetBindingTable
from msm_pricing.meta_tables import pricing_sqlalchemy_models

pytestmark = pytest.mark.usefixtures("offline_postgresql_runtime")

MIGRATION = importlib.import_module(
    "msm_migrations.versions.mainsequence_markets.0022_identity_named_uid_columns"
)
STORAGE_TABLE_UID = uuid.UUID("3f2a1c4e-5b6d-4e7f-8a9b-0c1d2e3f4a5b")


@pytest.fixture(autouse=True)
def bind_test_meta_table_uids(monkeypatch) -> None:
    for model in [*markets_sqlalchemy_models(), *pricing_sqlalchemy_models()]:
        monkeypatch.setattr(model, "__metatable_uid__", str(uuid.uuid4()), raising=False)


def _context() -> MarketsRepositoryContext:
    return MarketsRepositoryContext(limits={"max_rows": 100, "statement_timeout_ms": 5000})


def _renamed_models() -> list[type]:
    models = [*markets_sqlalchemy_models(), *pricing_sqlalchemy_models()]
    return [model for model in models if getattr(model, "__renamed_columns__", None)]


def test_renamed_columns_match_the_expand_migration() -> None:
    declared = {
        model.__table__.name: tuple(
            (previous, current) for current, previous in model.__renamed_columns__.items()
        )
        for model in _renamed_models()
    }

    assert declared == MIGRATION.RENAMED_COLUMNS
    for model in _renamed_models():
        for current, previous in model.__renamed_columns__.items():
            assert {current, previous} <= set(model.__table__.columns.keys())


@pytest.mark.parametrize("name", ["storage_table_uid", "data_node_uid"])
def test_a_value_under_either_name_fills_both_columns(name: str) -> None:
    payload = mirror_renamed_columns(PricingMarketDataSetBindingTable, {name: STORAGE_TABLE_UID})

    assert payload == {"storage_table_uid": STORAGE_TABLE_UID, "data_node_uid": STORAGE_TABLE_UID}


def test_equal_values_under_both_names_are_accepted() -> None:
    payload = mirror_renamed_columns(
        PricingMarketDataSetBindingTable,
        {"storage_table_uid": STORAGE_TABLE_UID, "data_node_uid": str(STORAGE_TABLE_UID)},
    )

    assert payload["storage_table_uid"] == STORAGE_TABLE_UID


def test_conflicting_values_under_both_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="different values for storage_table_uid"):
        mirror_renamed_columns(
            PricingMarketDataSetBindingTable,
            {"storage_table_uid": STORAGE_TABLE_UID, "data_node_uid": uuid.uuid4()},
        )


def test_models_without_renamed_columns_are_unchanged() -> None:
    payload = {"unique_identifier": "ASSET_A"}

    assert mirror_renamed_columns(AssetTable, payload) == payload


def _parameters(operation) -> dict:
    return operation.statement.parameters


def test_crud_create_upsert_and_update_write_both_columns() -> None:
    values = {
        "market_data_set_uid": uuid.uuid4(),
        "concept_key": "discount_curves",
        "storage_table_uid": STORAGE_TABLE_UID,
    }
    model = PricingMarketDataSetBindingTable
    operations = [
        build_create_model_operation(_context(), model=model, values=values),
        build_upsert_model_operation(
            _context(), model=model, values=values, conflict_columns=["market_data_set_uid"]
        ),
        build_update_model_operation(
            _context(), model=model, uid=uuid.uuid4(), values={"storage_table_uid": STORAGE_TABLE_UID}
        ),
    ]

    for operation in operations:
        parameters = _parameters(operation)
        assert STORAGE_TABLE_UID in parameters.values()
        written = [key for key, value in parameters.items() if value == STORAGE_TABLE_UID]
        assert any(key.startswith("storage_table_uid") for key in written)
        assert any(key.startswith("data_node_uid") for key in written)


def test_crud_bulk_upsert_writes_both_columns_for_every_row() -> None:
    rows = [
        {
            "market_data_set_uid": uuid.uuid4(),
            "concept_key": concept,
            "data_node_uid": STORAGE_TABLE_UID,
        }
        for concept in ("discount_curves", "index_fixings")
    ]

    operation = build_bulk_upsert_model_operation(
        _context(),
        model=PricingMarketDataSetBindingTable,
        values=rows,
        conflict_columns=["market_data_set_uid", "concept_key"],
    )

    written = [key for key, value in _parameters(operation).items() if value == STORAGE_TABLE_UID]
    assert sum(key.startswith("storage_table_uid") for key in written) == 2
    assert sum(key.startswith("data_node_uid") for key in written) == 2


def test_account_and_portfolio_repositories_write_both_columns() -> None:
    account = build_create_account_operation(
        _context(),
        unique_identifier="ACCOUNT_A",
        account_name="Account A",
        holdings_data_node_uid=STORAGE_TABLE_UID,
    )
    account_update = build_update_account_operation(
        _context(), uid=uuid.uuid4(), holdings_data_node_uid=STORAGE_TABLE_UID
    )
    update_uid = uuid.uuid4()
    portfolio = build_create_portfolio_operation(
        _context(),
        unique_identifier="PORTFOLIO_A",
        calendar_uid=uuid.uuid4(),
        portfolio_data_node_uid=update_uid,
    )

    for operation in (account, account_update):
        assert _parameters(operation)["holdings_storage_table_uid"] == STORAGE_TABLE_UID
        assert _parameters(operation)["holdings_data_node_uid"] == STORAGE_TABLE_UID
    assert _parameters(portfolio)["portfolio_table_update_uid"] == update_uid
    assert _parameters(portfolio)["portfolio_data_node_uid"] == update_uid
    assert PortfolioTable.__renamed_columns__["portfolio_table_update_uid"] == "portfolio_data_node_uid"
