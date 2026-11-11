"""A hook replaced on ``msm.services.accounts`` must not stay on its ``core`` module.

Tests replace account hooks on the package; its snapshot entry points hand them to
``core`` for the call. Each ``monkeypatch.context()`` below stands in for one test:
leaving it undoes the patches, as the end of a test does.
"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pandas as pd
import pytest

from msm.services import accounts as account_services
from msm.services.accounts import core

CORE_HOOKS = (
    "account_repository",
    "uuid",
    "get_account_by_uid",
    "_asset_row_by_unique_identifier",
    "_asset_snapshot_references_by_unique_identifier",
    "_build_account_holdings_frame",
    "_search_account_holdings_rows",
    "get_account_holdings_snapshot_response",
)


def _core_hooks() -> dict[str, object]:
    return {name: getattr(core, name) for name in CORE_HOOKS}


def test_patched_account_lookups_do_not_outlive_their_test(monkeypatch) -> None:
    account_uid = str(uuid.uuid4())
    core_hooks = _core_hooks()

    with monkeypatch.context() as test:
        test.setattr(
            account_services,
            "get_account_by_uid",
            lambda context, uid: {"row": {"uid": account_uid}},
        )
        test.setattr(account_services, "_search_account_holdings_rows", lambda context, **_: [])
        test.setattr(
            account_services,
            "_asset_row_by_unique_identifier",
            lambda context, unique_identifier: None,
        )

        snapshot = account_services.get_account_holdings_snapshot_response(
            object(),
            account_uid=account_uid,
        )
        with pytest.raises(ValueError, match="'unknown-asset' was not found"):
            account_services.add_account_holdings_snapshot_response(
                object(),
                account_uid=account_uid,
                holdings_date=dt.datetime(2026, 11, 11, tzinfo=dt.UTC),
                positions=[{"asset_identifier": "unknown-asset", "quantity": "1"}],
            )

    # The fakes reached core during the calls...
    assert snapshot == {"holdings_set_uid": None, "holdings_date": None, "holdings": []}
    # ...and core holds its own functions again, after a return and after a raise.
    assert _core_hooks() == core_hooks


def test_patched_snapshot_read_and_write_do_not_outlive_their_test(monkeypatch) -> None:
    account_uid = str(uuid.uuid4())
    written = {"holdings_set_uid": "written"}
    core_hooks = _core_hooks()

    with monkeypatch.context() as test:
        test.setattr(
            account_services,
            "get_account_by_uid",
            lambda context, uid: {"row": {"uid": account_uid}},
        )
        test.setattr(account_services, "_build_account_holdings_frame", lambda **_: pd.DataFrame())
        test.setattr(
            account_services,
            "account_repository",
            SimpleNamespace(
                replace_account_holdings_snapshot=lambda context, **_: {"rows": [{"uid": "x"}]},
            ),
        )
        test.setattr(
            account_services,
            "get_account_holdings_snapshot_response",
            lambda context, **_: written,
        )

        snapshot = account_services.add_account_holdings_snapshot_response(
            object(),
            account_uid=account_uid,
            holdings_date=dt.datetime(2026, 11, 11, tzinfo=dt.UTC),
            positions=[],
        )

    assert snapshot is written
    assert _core_hooks() == core_hooks
