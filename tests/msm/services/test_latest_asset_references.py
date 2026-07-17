from __future__ import annotations

import os
import uuid
from typing import Any

os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")


def test_account_holding_asset_references_use_backend_latest_reference_service(
    monkeypatch,
) -> None:
    import msm.services.accounts.core as account_services
    import msm.services.assets as asset_services

    context = object()
    asset_uid = uuid.uuid4()
    captured: dict[str, Any] = {}

    def fake_asset_reference_details(asset_identifiers, *, repository_context):
        captured["asset_identifiers"] = asset_identifiers
        captured["repository_context"] = repository_context
        return [
            {
                "asset_uid": str(asset_uid),
                "asset_identifier": "btc_spot",
                "name": "Bitcoin",
                "ticker": "BTC",
            }
        ]

    monkeypatch.setattr(asset_services, "asset_reference_details", fake_asset_reference_details)

    references = account_services._asset_snapshot_references_by_unique_identifier(
        context,
        rows=[{"asset_identifier": "btc_spot"}],
    )

    assert captured == {
        "asset_identifiers": ["btc_spot"],
        "repository_context": context,
    }
    assert references == {
        "btc_spot": {
            "uid": str(asset_uid),
            "asset_identifier": "btc_spot",
            "current_snapshot": {"name": "Bitcoin", "ticker": "BTC"},
        }
    }


def test_target_position_asset_references_use_backend_latest_reference_service(
    monkeypatch,
) -> None:
    import msm.services.target_positions as target_position_services

    context = object()
    asset_uid = uuid.uuid4()
    captured: dict[str, Any] = {}

    def fake_asset_reference_details_by_uids(asset_uids, *, repository_context):
        captured["asset_uids"] = asset_uids
        captured["repository_context"] = repository_context
        return [
            {
                "asset_uid": str(asset_uid),
                "asset_identifier": "btc_spot",
                "name": "Bitcoin",
                "ticker": "BTC",
            }
        ]

    monkeypatch.setattr(
        target_position_services,
        "asset_reference_details_by_uids",
        fake_asset_reference_details_by_uids,
    )

    references = target_position_services._asset_references_by_uid(
        context,
        rows=[{"asset_uid": str(asset_uid)}],
    )

    assert captured == {
        "asset_uids": [str(asset_uid)],
        "repository_context": context,
    }
    assert references == {
        str(asset_uid): {
            "uid": str(asset_uid),
            "unique_identifier": "btc_spot",
            "current_snapshot": {"name": "Bitcoin", "ticker": "BTC"},
        }
    }


def test_virtual_fund_asset_references_use_backend_latest_reference_service(
    monkeypatch,
) -> None:
    import msm.services.accounts.virtual_funds_public_api as virtual_fund_services
    import msm.services.assets as asset_services

    context = object()
    asset_uid = uuid.uuid4()
    captured: dict[str, Any] = {}

    def fake_asset_reference_details(asset_identifiers, *, repository_context):
        captured["asset_identifiers"] = asset_identifiers
        captured["repository_context"] = repository_context
        return [
            {
                "asset_uid": str(asset_uid),
                "asset_identifier": "btc_spot",
                "name": "Bitcoin",
                "ticker": "BTC",
            }
        ]

    monkeypatch.setattr(asset_services, "asset_reference_details", fake_asset_reference_details)

    references = virtual_fund_services._asset_references_by_unique_identifier(
        context,
        rows=[{"asset_identifier": "btc_spot"}],
    )

    assert captured == {
        "asset_identifiers": ["btc_spot"],
        "repository_context": context,
    }
    assert references == {
        "btc_spot": {
            "uid": str(asset_uid),
            "asset_identifier": "btc_spot",
            "current_snapshot": {"name": "Bitcoin", "ticker": "BTC"},
        }
    }
