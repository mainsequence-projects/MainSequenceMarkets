"""``msm rename-preflight`` reports what a host project changes for ADR 0048."""

from __future__ import annotations

import json
import textwrap

import pytest

from msm_cli import rename_preflight
from msm_cli.main import main
from tests.identity.test_pinned_identities import (
    PINNED_PRE_RENAME_UPDATE_HASHES,
    _built_updaters,
    namespace_is_default,
)

PRE_3_0_SOURCE = textwrap.dedent(
    '''
    from msm.data_nodes.assets.storage import AssetSnapshotsStorage
    from msm_pricing.data_nodes import DiscountCurvesNode
    from msm_portfolios.contrib.prices.data_nodes import InterpolatedPrices

    class Holdings(HoldingsDataNode):
        pass

    uid = getattr(binding, "data_node_uid", "")
    fund.allocate_from_account_holdings_set(data_node=holdings, run=True)
    data_node = load_holdings_updater()
    '''
)


def _findings(tmp_path):
    (tmp_path / "app.py").write_text(PRE_3_0_SOURCE)
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "ignored.py").write_text("from msm.data_nodes import x\n")
    return rename_preflight.scan([tmp_path])


def test_scan_reports_every_pre_3_0_name_with_its_replacement(tmp_path) -> None:
    findings = {(finding.kind, finding.old, finding.new) for finding in _findings(tmp_path)}

    assert findings == {
        ("import path", "msm.data_nodes.assets.storage", "msm.time_index.assets.storage"),
        ("import path", "msm_pricing.data_nodes", "msm_pricing.time_index"),
        (
            "import path",
            "msm_portfolios.contrib.prices.data_nodes",
            "msm_portfolios.contrib.prices.updaters",
        ),
        ("class name", "DiscountCurvesNode", "DiscountCurvesUpdater"),
        ("class name", "HoldingsDataNode", "HoldingsUpdater"),
        ("field name", "data_node_uid", "storage_table_uid"),
        (
            "silent default",
            'getattr(binding, "data_node_uid",',
            'getattr(..., "storage_table_uid") without a default',
        ),
        ("keyword", "data_node=", "updater="),
    }


def test_scan_command_exits_1_while_pre_3_0_names_remain(tmp_path, capsys) -> None:
    _findings(tmp_path)

    assert main(["rename-preflight", "scan", str(tmp_path), "--json"]) == 1
    assert {row["kind"] for row in json.loads(capsys.readouterr().out)} >= {"import path"}

    (tmp_path / "app.py").write_text("from msm.time_index.assets import AssetSnapshot\n")
    assert main(["rename-preflight", "scan", str(tmp_path)]) == 0


@namespace_is_default
def test_rotation_reports_the_pre_3_0_update_hash_of_each_updater() -> None:
    with _built_updaters() as updaters:
        report = rename_preflight.rotation([updaters["interpolated_prices"]])

    by_updater = {row["updater"].rsplit(":", 1)[1]: row for row in report}
    assert set(by_updater) == {"AssetSnapshot", "InterpolatedPrices"}
    assert by_updater["AssetSnapshot"]["rotated"] is True
    assert (
        by_updater["AssetSnapshot"]["pre_3_0_update_hash"]
        == PINNED_PRE_RENAME_UPDATE_HASHES["asset_snapshot"]
    )
    assert (
        by_updater["InterpolatedPrices"]["pre_3_0_update_hash"]
        == PINNED_PRE_RENAME_UPDATE_HASHES["interpolated_prices"]
    )


def test_load_objects_calls_a_module_callable(tmp_path, monkeypatch) -> None:
    (tmp_path / "host_updaters.py").write_text("def updaters():\n    return ['a', 'b']\n")
    monkeypatch.syspath_prepend(str(tmp_path))

    assert rename_preflight.load_objects("host_updaters:updaters") == ["a", "b"]
    with pytest.raises(ValueError, match="module:callable"):
        rename_preflight.load_objects("host_updaters")


def test_account_uids_classifies_each_stored_uid(monkeypatch, capsys) -> None:
    rows = [
        ("Account", "holdings_storage_table_uid", "table-1"),
        ("Account", "holdings_storage_table_uid", "table-1"),
        ("Account", "holdings_storage_table_uid", None),
        ("AccountHoldingsSet", "source_storage_table_uid", "update-1"),
    ]
    classes = {"table-1": "TimeIndexMetaTable", "update-1": "TimeIndexTableUpdate"}
    monkeypatch.setattr(rename_preflight, "_account_uid_rows", lambda limit: iter(rows))
    monkeypatch.setattr(rename_preflight, "classify_uid", classes.__getitem__)

    report = rename_preflight.account_uids()

    assert report == [
        {
            "table": "Account",
            "column": "holdings_storage_table_uid",
            "classification": "TimeIndexMetaTable",
            "count": 2,
            "examples": ["table-1"],
        },
        {
            "table": "AccountHoldingsSet",
            "column": "source_storage_table_uid",
            "classification": "TimeIndexTableUpdate",
            "count": 1,
            "examples": ["update-1"],
        },
    ]
    assert main(["rename-preflight", "account-uids", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == report
