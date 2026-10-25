"""ADR 0047: deletes respect the Markets catalog.

A portfolio whose values, weights or signal weights are catalogued in a contract
instance another application owns keeps those rows: Markets deletes only its own
core tables and reports what it left in place, and refuses time-series deletes
that would have to remove rows from someone else's table.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm_portfolios.services.portfolio_reads import PortfolioDatasetTables

CORE_WEIGHTS_TABLE_UID = "0a0a0a0a-0000-4000-8000-000000000001"
PROVIDER_VALUES_TABLE_UID = "1b1b1b1b-0000-4000-8000-000000000002"
PROVIDER_WEIGHTS_TABLE_UID = "2c2c2c2c-0000-4000-8000-000000000003"
PROVIDER_SIGNAL_TABLE_UID = "3d3d3d3d-0000-4000-8000-000000000004"


def _portfolio_row(uid: uuid.UUID) -> dict[str, object]:
    return {
        "uid": str(uid),
        "unique_identifier": "provider-sleeve",
        "calendar_uid": str(uuid.uuid4()),
        "signal_uid": "provider-signal",
    }


def _tables(
    portfolio_uid: uuid.UUID,
    *,
    values: str | None = None,
    weights: str | None = None,
) -> PortfolioDatasetTables:
    return PortfolioDatasetTables(
        portfolio_uid=portfolio_uid,
        portfolio_identifier="provider-sleeve",
        signal_uid="provider-signal",
        values_meta_table_uid=values,
        weights_meta_table_uid=weights,
    )


class _CoreMetaTable:
    def __init__(self, uid: str | None = None) -> None:
        self.uid = uid
        self.calls: list[dict[str, object]] = []

    def delete_after_date(self, after_date, *, dimension_filters, timeout=None):
        self.calls.append({"after_date": after_date, "dimension_filters": dimension_filters})
        return {"deleted_count": 2}


@pytest.fixture
def portfolio(monkeypatch):
    portfolio_uid = uuid.uuid4()
    row = _portfolio_row(portfolio_uid)
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_portfolio_row",
        lambda context, uid: row,
    )
    return portfolio_uid


def _catalog(monkeypatch, tables: PortfolioDatasetTables | None) -> None:
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._portfolio_dataset_tables",
        lambda context, portfolio_identifier: tables,
    )


def _core_tables(monkeypatch, *, weights_uid: str | None = None) -> dict[str, _CoreMetaTable]:
    tables = {
        "weights": _CoreMetaTable(weights_uid),
        "values": _CoreMetaTable(),
        "signals": _CoreMetaTable(),
    }
    for path, key in (
        ("msm_portfolios.time_index.portfolios.storage.PortfolioWeightsStorage", "weights"),
        ("msm_portfolios.time_index.portfolios.storage.PortfoliosStorage", "values"),
        ("msm_portfolios.time_index.signals.storage.SignalWeightsStorage", "signals"),
    ):
        monkeypatch.setattr(
            f"{path}.get_time_index_meta_table",
            classmethod(lambda cls, table=tables[key]: table),
        )
    return tables


def test_weights_delete_refuses_a_provider_owned_instance(monkeypatch, portfolio) -> None:
    _catalog(monkeypatch, _tables(portfolio, weights=PROVIDER_WEIGHTS_TABLE_UID))
    core = _core_tables(monkeypatch, weights_uid=CORE_WEIGHTS_TABLE_UID)

    from msm_portfolios.services.public_api import (
        PortfolioDatasetOwnershipError,
        delete_portfolio_weights,
    )

    with pytest.raises(PortfolioDatasetOwnershipError, match=PROVIDER_WEIGHTS_TABLE_UID):
        delete_portfolio_weights(SimpleNamespace(timeout=30), uid=str(portfolio))
    assert core["weights"].calls == []


def test_weights_delete_runs_when_the_catalog_names_the_core_table(monkeypatch, portfolio) -> None:
    _catalog(monkeypatch, _tables(portfolio, weights=CORE_WEIGHTS_TABLE_UID))
    core = _core_tables(monkeypatch, weights_uid=CORE_WEIGHTS_TABLE_UID)

    from msm_portfolios.services.public_api import delete_portfolio_weights

    response = delete_portfolio_weights(SimpleNamespace(timeout=30), uid=str(portfolio))

    assert response["deleted_count"] == 2
    assert core["weights"].calls == [
        {"after_date": None, "dimension_filters": {"portfolio_identifier": ["provider-sleeve"]}}
    ]


def test_portfolio_delete_reports_provider_datasets_it_left_in_place(
    monkeypatch, portfolio
) -> None:
    _catalog(
        monkeypatch,
        _tables(portfolio, values=PROVIDER_VALUES_TABLE_UID, weights=PROVIDER_WEIGHTS_TABLE_UID),
    )
    core = _core_tables(monkeypatch, weights_uid=CORE_WEIGHTS_TABLE_UID)
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._raise_if_portfolio_delete_is_blocked",
        lambda context, **kwargs: None,
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._compile_delete_portfolio_operation",
        lambda context, **kwargs: "delete-op",
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api.execute_markets_operation",
        lambda operation, context: {"rows": [{"uid": str(portfolio)}]},
    )

    from msm_portfolios.services.public_api import delete_portfolio_record

    response = delete_portfolio_record(SimpleNamespace(timeout=30), uid=str(portfolio))

    assert response["retained_datasets"] == [
        {
            "portfolio_uid": str(portfolio),
            "portfolio_identifier": "provider-sleeve",
            "dataset": "values",
            "meta_table_uid": PROVIDER_VALUES_TABLE_UID,
        },
        {
            "portfolio_uid": str(portfolio),
            "portfolio_identifier": "provider-sleeve",
            "dataset": "weights",
            "meta_table_uid": PROVIDER_WEIGHTS_TABLE_UID,
        },
    ]
    assert "left in place" in response["detail"]
    # Core leftovers from before the portfolio moved are still Markets' to remove.
    assert response["deleted_weights_count"] == 2
    assert response["deleted_values_count"] == 2
    assert len(core["weights"].calls) == 1
    assert len(core["values"].calls) == 1


def test_bulk_delete_collects_retained_datasets(monkeypatch) -> None:
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    retained = {
        "portfolio_uid": first,
        "portfolio_identifier": "provider-sleeve",
        "dataset": "values",
        "meta_table_uid": PROVIDER_VALUES_TABLE_UID,
    }
    monkeypatch.setattr(
        "msm_portfolios.services.public_api.delete_portfolio_record",
        lambda context, uid: {
            "detail": "Portfolio deleted.",
            "deleted_count": 1,
            "retained_datasets": [retained] if uid == first else [],
        },
    )

    from msm_portfolios.services.public_api import bulk_delete_portfolio_records

    response = bulk_delete_portfolio_records(object(), uids=[first, second])

    assert response["deleted_count"] == 2
    assert response["retained_datasets"] == [retained]


def test_signal_weights_delete_refuses_a_provider_owned_instance(monkeypatch) -> None:
    core = _core_tables(monkeypatch)
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_signal_metadata_row",
        lambda context, uid: {
            "uid": uid,
            "signal_uid": "provider-signal",
            "meta_table_uid": PROVIDER_SIGNAL_TABLE_UID,
        },
    )

    from msm_portfolios.services.public_api import (
        SignalDatasetOwnershipError,
        delete_signal_weights,
    )

    with pytest.raises(SignalDatasetOwnershipError, match=PROVIDER_SIGNAL_TABLE_UID):
        delete_signal_weights(SimpleNamespace(timeout=30), uid=str(uuid.uuid4()))
    assert core["signals"].calls == []


def test_signal_metadata_delete_reports_the_provider_instance(monkeypatch) -> None:
    core = _core_tables(monkeypatch)
    signal_metadata_uid = str(uuid.uuid4())
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._get_signal_metadata_row",
        lambda context, uid: {
            "uid": uid,
            "signal_uid": "provider-signal",
            "meta_table_uid": PROVIDER_SIGNAL_TABLE_UID,
        },
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._compile_delete_signal_metadata_operation",
        lambda context, **kwargs: "delete-op",
    )
    monkeypatch.setattr(
        "msm_portfolios.services.public_api.execute_markets_operation",
        lambda operation, context: {"rows": [{"uid": signal_metadata_uid}]},
    )

    from msm_portfolios.services.public_api import delete_signal_metadata_record

    response = delete_signal_metadata_record(SimpleNamespace(timeout=30), uid=signal_metadata_uid)

    assert response["retained_datasets"] == [
        {
            "signal_uid": "provider-signal",
            "dataset": "signal_weights",
            "meta_table_uid": PROVIDER_SIGNAL_TABLE_UID,
        }
    ]
    assert response["deleted_weights_count"] == 2
    assert len(core["signals"].calls) == 1


def test_weights_delete_route_returns_409_for_a_provider_owned_instance(monkeypatch) -> None:
    from msm_portfolios.services.public_api import PortfolioDatasetOwnershipError

    def refuse(uid, weights_date=None):
        raise PortfolioDatasetOwnershipError("owned by another application")

    monkeypatch.setattr("apps.v1.routers.portfolios.delete_portfolio_weights", refuse)

    response = TestClient(app).delete(f"/api/v1/portfolio/{uuid.uuid4()}/weights/")

    assert response.status_code == 409
    assert response.json()["detail"] == "owned by another application"


def test_signal_weights_service_and_route_return_409_for_a_provider_owned_instance(
    monkeypatch,
) -> None:
    from msm_portfolios.services.public_api import SignalDatasetOwnershipError

    def refuse(context, **kwargs):
        raise SignalDatasetOwnershipError("owned by another application")

    monkeypatch.setattr(
        "apps.v1.services.portfolio_signals._get_runtime",
        lambda: SimpleNamespace(context=object()),
    )
    monkeypatch.setattr("apps.v1.services.portfolio_signals._delete_signal_weights", refuse)

    from apps.v1.services.portfolio_signals import (
        PortfolioSignalDeleteConflictError,
        delete_portfolio_signal_weights,
    )

    with pytest.raises(PortfolioSignalDeleteConflictError, match="another application"):
        delete_portfolio_signal_weights(uid=str(uuid.uuid4()))

    response = TestClient(app).delete(f"/api/v1/portfolio-signal/{uuid.uuid4()}/weights/")

    assert response.status_code == 409


def test_bulk_delete_preflight_warns_about_provider_datasets(monkeypatch, portfolio) -> None:
    _catalog(monkeypatch, _tables(portfolio, values=PROVIDER_VALUES_TABLE_UID))
    _core_tables(monkeypatch)
    monkeypatch.setattr(
        "msm_portfolios.services.public_api._portfolio_delete_blockers",
        lambda context, portfolio_uid: [],
    )

    from apps.v1.services import portfolios

    exists, blockers, warnings = portfolios._portfolio_delete_preflight_item(
        object(),
        uid=str(portfolio),
    )

    assert exists is True
    assert blockers == []
    assert warnings == [
        f"its values rows in table {PROVIDER_VALUES_TABLE_UID} stay in place; "
        "the application that owns that table deletes them."
    ]
