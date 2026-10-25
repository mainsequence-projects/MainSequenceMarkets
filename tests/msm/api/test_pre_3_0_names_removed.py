"""ms-markets 4.0 rejects the pre-3.0 UID names instead of ignoring them (ADR 0048)."""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from msm.api.accounts import AccountCreate
from msm.api.portfolios import PortfolioUpdate
from msm.models import AccountTable, markets_sqlalchemy_models
from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import build_create_model_operation
from msm_pricing.api.market_data_bindings import PricingMarketDataSetBindingCreate
from msm_pricing.config import PricingMarketDataConfiguration
from msm_pricing.meta_tables import pricing_sqlalchemy_models


def test_models_no_longer_map_the_pre_3_0_columns() -> None:
    for model in [*markets_sqlalchemy_models(), *pricing_sqlalchemy_models()]:
        assert not [name for name in model.__table__.columns.keys() if "data_node" in name]


def test_payloads_reject_pre_3_0_field_names() -> None:
    with pytest.raises(ValidationError, match="holdings_data_node_uid"):
        AccountCreate(
            unique_identifier="ACCOUNT_A",
            account_name="Account A",
            holdings_data_node_uid=uuid.uuid4(),
        )
    with pytest.raises(ValidationError, match="portfolio_data_node_uid"):
        PortfolioUpdate(portfolio_data_node_uid=uuid.uuid4())
    with pytest.raises(ValidationError, match="data_node_uid"):
        PricingMarketDataSetBindingCreate(
            market_data_set_uid=uuid.uuid4(),
            concept_key="discount_curves",
            data_node_uid=uuid.uuid4(),
        )
    with pytest.raises(ValidationError, match="data_node_uids"):
        PricingMarketDataConfiguration(market_data_set="default", data_node_uids={})


def test_row_writes_reject_pre_3_0_column_names() -> None:
    context = MarketsRepositoryContext(limits={"max_rows": 100, "statement_timeout_ms": 5000})

    with pytest.raises(ValueError, match="no SQLAlchemy column 'holdings_data_node_uid'"):
        build_create_model_operation(
            context,
            model=AccountTable,
            values={
                "unique_identifier": "ACCOUNT_A",
                "account_name": "Account A",
                "holdings_data_node_uid": uuid.uuid4(),
            },
        )
