"""``update_model`` statements on PostgreSQL, the hosted dialect (MainSequenceMarkets#87).

Skipped unless ``MS_MARKETS_REGISTRATION_TEST_POSTGRES_URL`` names a disposable
``markets_*`` database on localhost; see ``test_postgresql_account_registration``.
"""

from __future__ import annotations

import pytest

from msm.models import AssetCategoryTable, SignalMetadataTable
from msm.repositories.crud import create_model, update_model
from tests.support.postgresql_markets import _scalar_rows


def test_none_clears_a_signals_manager(postgresql_markets) -> None:
    engine, context, _operations = postgresql_markets
    row = create_model(
        context,
        model=SignalMetadataTable,
        values={"signal_uid": "momentum", "managed_by": "user:00000000-0000-4000-8000-000000000001"},
    )["rows"][0]

    update_model(context, model=SignalMetadataTable, uid=row["uid"], values={"managed_by": None})

    assert _scalar_rows(
        engine, "SELECT signal_uid, managed_by FROM ms_markets__signalmetadata"
    ) == [("momentum", None)]


def test_none_clears_a_json_column_to_sql_null(postgresql_markets) -> None:
    engine, context, _operations = postgresql_markets
    row = create_model(
        context,
        model=AssetCategoryTable,
        values={
            "unique_identifier": "core",
            "display_name": "Core",
            "description": "Core holdings",
            "metadata_json": {"source": "desk"},
        },
    )["rows"][0]

    update_model(
        context,
        model=AssetCategoryTable,
        uid=row["uid"],
        values={"description": None, "metadata_json": None},
    )

    assert _scalar_rows(
        engine,
        "SELECT display_name, description, metadata_json IS NULL FROM ms_markets__assetcategory",
    ) == [("Core", None, True)]
    with pytest.raises(ValueError, match="cannot set display_name to NULL"):
        update_model(context, model=AssetCategoryTable, uid=row["uid"], values={"display_name": None})
