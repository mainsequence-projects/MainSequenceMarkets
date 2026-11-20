"""Renamed UID fields keep their pre-3.0 names through 3.x (ADR 0048)."""

from __future__ import annotations

import uuid
import warnings

import pytest

from msm.api.accounts import Account, AccountCreate, AccountHoldingsSet
from msm.api.base import _row_values
from msm.api.portfolios import Portfolio, PortfolioUpdate
from msm.api.virtual_funds import _renamed_updater_argument
from msm.settings import markets_data_node_identifier, markets_identifier
from tests.support.renamed_fields import STORAGE_TABLE_UID

PRE_3_0_STORAGE_TABLE_UID = uuid.UUID("0f2d6c1e-7a3b-4c5d-9e8f-1a2b3c4d5e6f")


def _account_row(**columns: object) -> dict[str, object]:
    return {
        "uid": uuid.uuid4(),
        "unique_identifier": "ACCOUNT_A",
        "account_name": "Account A",
        **columns,
    }


def test_payloads_accept_the_pre_3_0_name_with_a_warning() -> None:
    with pytest.warns(DeprecationWarning, match="AccountCreate.holdings_data_node_uid"):
        payload = AccountCreate(
            unique_identifier="ACCOUNT_A",
            account_name="Account A",
            holdings_data_node_uid=STORAGE_TABLE_UID,
        )

    assert payload.model_dump(exclude_unset=True)["holdings_storage_table_uid"] == STORAGE_TABLE_UID
    assert "holdings_data_node_uid" not in payload.model_dump()


def test_payloads_reject_different_values_under_both_names() -> None:
    with pytest.warns(DeprecationWarning), pytest.raises(ValueError, match="different values"):
        PortfolioUpdate(
            portfolio_table_update_uid=uuid.uuid4(),
            portfolio_data_node_uid=uuid.uuid4(),
        )


def test_rows_read_the_pre_3_0_column_while_2_x_writers_exist() -> None:
    # A 2.x writer updated only the pre-3.0 column after revision 0022 copied it.
    row = Account.model_validate(
        _account_row(
            holdings_storage_table_uid=STORAGE_TABLE_UID,
            holdings_data_node_uid=PRE_3_0_STORAGE_TABLE_UID,
        )
    )

    assert row.holdings_storage_table_uid == PRE_3_0_STORAGE_TABLE_UID
    assert row.model_dump()["holdings_data_node_uid"] == PRE_3_0_STORAGE_TABLE_UID


def test_rows_built_from_one_name_carry_both_and_warn_on_the_old_attribute() -> None:
    row = AccountHoldingsSet.model_validate(
        {
            "uid": uuid.uuid4(),
            "account_uid": uuid.uuid4(),
            "time_index": "2026-01-02T00:00:00Z",
            "source_storage_table_uid": STORAGE_TABLE_UID,
        }
    )

    assert row.model_dump()["source_data_node_uid"] == STORAGE_TABLE_UID
    with pytest.warns(DeprecationWarning, match="source_storage_table_uid"):
        assert row.source_data_node_uid == STORAGE_TABLE_UID


def test_row_keyword_writes_warn_on_pre_3_0_column_names() -> None:
    with pytest.warns(DeprecationWarning, match="Portfolio.portfolio_data_node_uid"):
        values = _row_values(Portfolio, None, {"portfolio_data_node_uid": STORAGE_TABLE_UID})

    assert values == {"portfolio_data_node_uid": STORAGE_TABLE_UID}
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        _row_values(
            Portfolio,
            None,
            {
                "portfolio_table_update_uid": STORAGE_TABLE_UID,
                "portfolio_data_node_uid": STORAGE_TABLE_UID,
            },
        )


def test_markets_data_node_identifier_is_a_deprecated_alias() -> None:
    with pytest.warns(DeprecationWarning, match="markets_data_node_identifier is deprecated"):
        identifier = markets_data_node_identifier("HoldingsTS", namespace="example")

    assert identifier == markets_identifier("HoldingsTS", namespace="example")


def test_virtual_fund_allocation_accepts_the_pre_3_0_data_node_keyword() -> None:
    updater = object()

    with pytest.warns(DeprecationWarning, match="data_node= is deprecated; use updater="):
        assert _renamed_updater_argument(None, updater) is updater
    with pytest.warns(DeprecationWarning), pytest.raises(TypeError, match="not also as data_node="):
        _renamed_updater_argument(object(), updater)
