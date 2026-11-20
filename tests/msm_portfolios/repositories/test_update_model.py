"""``msm_portfolios``' patch helpers write only the columns they are given (MainSequenceMarkets#87).

Split from ``tests/msm/repositories/test_update_model.py``, whose helpers and setup it
shares through ``tests/support/update_model.py``.
"""

from __future__ import annotations

import pytest

from msm.repositories.account_groups import build_update_account_group_operation
from msm_portfolios.repositories.market_metadata import build_update_signal_metadata_operation
from tests.support.update_model import ROW_UID, _context, _set_clause
from tests.support.update_model import bind_test_meta_table_uids as _bind_test_meta_table_uids

pytestmark = pytest.mark.usefixtures("offline_postgresql_runtime")


@pytest.fixture(autouse=True)
def bind_test_meta_table_uids(monkeypatch) -> None:
    _bind_test_meta_table_uids(monkeypatch)


def test_patch_helpers_leave_the_columns_they_are_not_given() -> None:
    operation = build_update_account_group_operation(
        _context(), uid=ROW_UID, group_description="Long-only accounts"
    )

    assert _set_clause(operation).split("=")[0] == "group_description"
    with pytest.raises(ValueError, match="names no column"):
        build_update_account_group_operation(_context(), uid=ROW_UID)
    with pytest.raises(ValueError, match="names no column"):
        build_update_signal_metadata_operation(_context(), uid=ROW_UID, signal_description=None)
