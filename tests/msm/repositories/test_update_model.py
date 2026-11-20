"""``update_model`` writes exactly the values it is given, ``None`` as ``NULL`` (MainSequenceMarkets#87).

These tests compile the real statement. The unregister-signal test that missed #87
replaced ``update_model`` with a recorder, so it never saw the empty ``SET`` clause. The
patch-helper test that also covers ``msm_portfolios``' signal metadata is in
``tests/msm_portfolios/repositories/test_update_model.py``.
"""

from __future__ import annotations

import pytest

from msm.models import (
    AssetCategoryTable,
    PortfolioGroupTable,
    SignalMetadataTable,
)
from msm.repositories.asset_categories import build_update_asset_category_operation
from msm.repositories.crud import build_update_model_operation
from msm.repositories.portfolios import build_update_portfolio_group_operation
from tests.support.update_model import ROW_UID, _context, _set_clause
from tests.support.update_model import bind_test_meta_table_uids as _bind_test_meta_table_uids

pytestmark = pytest.mark.usefixtures("offline_postgresql_runtime")


@pytest.fixture(autouse=True)
def bind_test_meta_table_uids(monkeypatch) -> None:
    _bind_test_meta_table_uids(monkeypatch)


def test_none_sets_the_column_to_null() -> None:
    operation = build_update_model_operation(
        _context(),
        model=SignalMetadataTable,
        uid=ROW_UID,
        values={"meta_table_uid": None},
        returning=False,
    )

    assert _set_clause(operation) == "meta_table_uid=NULL"
    assert "meta_table_uid" not in operation.statement.parameters


def test_none_on_a_json_column_is_sql_null_not_json_null() -> None:
    operation = build_update_model_operation(
        _context(),
        model=AssetCategoryTable,
        uid=ROW_UID,
        values={"metadata_json": None, "description": "Kept"},
    )

    assert "metadata_json=NULL" in _set_clause(operation)
    assert "null" not in [str(value) for value in operation.statement.parameters.values()]


def test_an_update_naming_no_column_is_refused_before_compiling() -> None:
    with pytest.raises(ValueError, match=f"Update of SignalMetadataTable {ROW_UID} names no column"):
        build_update_model_operation(_context(), model=SignalMetadataTable, uid=ROW_UID, values={})


def test_none_on_a_not_null_column_is_refused_before_compiling() -> None:
    with pytest.raises(ValueError, match="cannot set signal_uid to NULL; the column is NOT NULL"):
        build_update_model_operation(
            _context(), model=SignalMetadataTable, uid=ROW_UID, values={"signal_uid": None}
        )


@pytest.mark.parametrize(
    ("build", "model"),
    [
        (build_update_asset_category_operation, AssetCategoryTable),
        (build_update_portfolio_group_operation, PortfolioGroupTable),
    ],
)
def test_category_and_group_updates_write_the_fields_given(build, model) -> None:
    cleared = build(_context(), uid=ROW_UID, description=None)

    assert _set_clause(cleared) == "description=NULL"
    renamed = build(_context(), uid=ROW_UID, display_name="Core")
    assert _set_clause(renamed).split("=")[0] == "display_name"
    with pytest.raises(ValueError, match=f"{model.__name__} .* cannot set display_name to NULL"):
        build(_context(), uid=ROW_UID, display_name=None)
    with pytest.raises(TypeError, match="cannot set unique_identifier"):
        build(_context(), uid=ROW_UID, unique_identifier="renamed")

