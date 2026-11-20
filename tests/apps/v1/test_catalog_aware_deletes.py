"""ADR 0047: deletes respect the Markets catalog.

Markets never deletes rows in a contract instance another application owns. A
signal delete removes the Markets rows and reports the instance it left in place,
and time-series deletes that would have to remove rows from someone else's table
are refused. The portfolio delete refuses while such an instance holds rows of
the portfolio; `tests/msm_portfolios/services/test_sqlite_portfolio_delete.py`
covers it end to end.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from msm_portfolios.services.portfolio_reads import PortfolioDatasetTables

CORE_WEIGHTS_TABLE_UID = "0a0a0a0a-0000-4000-8000-000000000001"
PROVIDER_WEIGHTS_TABLE_UID = "2c2c2c2c-0000-4000-8000-000000000003"
PROVIDER_SIGNAL_TABLE_UID = "3d3d3d3d-0000-4000-8000-000000000004"


def _portfolio_row(uid: uuid.UUID) -> dict[str, object]:
    return {
        "uid": str(uid),
        "unique_identifier": "provider-sleeve",
        "calendar_uid": str(uuid.uuid4()),
        "signal_uid": "provider-signal",
    }


def _tables(portfolio_uid: uuid.UUID, *, weights: str | None = None) -> PortfolioDatasetTables:
    return PortfolioDatasetTables(
        portfolio_uid=portfolio_uid,
        portfolio_identifier="provider-sleeve",
        signal_uid="provider-signal",
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
