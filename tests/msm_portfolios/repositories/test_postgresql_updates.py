"""Unregistering a signal dataset on PostgreSQL, the hosted dialect (MainSequenceMarkets#87).

Skipped unless ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` names a disposable
``markets_*`` database on localhost. Split from ``tests/msm/repositories/test_postgresql_updates.py``.
"""

from __future__ import annotations

from msm.models import SignalMetadataTable
from msm.repositories.crud import create_model
from msm_portfolios.services.portfolio_datasets import unregister_signal_dataset
from tests.support.postgresql_markets import _scalar_rows


def test_unregister_signal_clears_the_binding(postgresql_markets) -> None:
    engine, context, _operations = postgresql_markets
    create_model(
        context,
        model=SignalMetadataTable,
        values={"signal_uid": "momentum", "meta_table_uid": "signal-instance"},
    )

    removed = unregister_signal_dataset(context, signal_uid="momentum")

    assert removed is not None and removed.signal_meta_table_uid == "signal-instance"
    assert _scalar_rows(
        engine, "SELECT signal_uid, meta_table_uid FROM ms_markets__signalmetadata"
    ) == [("momentum", None)]
    assert unregister_signal_dataset(context, signal_uid="momentum") is None
