"""Upserts leave unchanged rows alone and report each row's status (MainSequenceMarkets#62).

These run the generic upserts end to end on a migrated SQLite DataSource, through
MetaTables' own SQLite backend, as ``test_sqlite_snapshot_writes`` does. A
``BEFORE UPDATE`` trigger on each table aborts any update that would rewrite a row
with the values it already holds, so a test that repeats an upsert proves the row
was not rewritten.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from metatables import MetaTableTransactionGuardError

from msm.models import (
    AssetCategoryMembershipTable,
    AssetTable,
    OpenFigiAssetDetailsTable,
)
from msm.repositories import crud
from msm.repositories.crud import UPSERT_STATUS_COLUMN, bulk_upsert_model, upsert_model
from tests.msm.repositories.test_sqlite_snapshot_writes import _count, _insert, make_sqlite_markets

GUARDED_TABLES = (
    "ms_markets__asset",
    "ms_markets__assetcategorymembership",
    "ms_markets__openfigiassetdetails",
    "ms_markets__currencyspotassetdetails",
)


def _refuse_identical_rewrites(engine) -> None:
    with engine.begin() as connection:
        for table in GUARDED_TABLES:
            columns = [column["name"] for column in sa.inspect(connection).get_columns(table)]
            same = " AND ".join(f'NEW."{name}" IS OLD."{name}"' for name in columns)
            connection.exec_driver_sql(
                f"CREATE TRIGGER refuse_identical_rewrite_{table} BEFORE UPDATE ON {table} "
                f"WHEN {same} BEGIN SELECT RAISE(ABORT, 'identical rewrite of {table}'); END"
            )


@pytest.fixture
def sqlite_markets(tmp_path, monkeypatch):
    return make_sqlite_markets(tmp_path, monkeypatch, prepare=_refuse_identical_rewrites)


def _rows(result) -> list[dict]:
    return result["rows"]


def _asset(context, identifier: str, asset_type: str = "equity") -> dict:
    return upsert_model(
        context,
        model=AssetTable,
        values={"unique_identifier": identifier, "asset_type": asset_type},
        conflict_columns=("unique_identifier",),
    )


def test_the_trigger_refuses_an_identical_rewrite(sqlite_markets) -> None:
    _insert(sqlite_markets.engine, "ms_markets__asset", unique_identifier="A", asset_type="equity")

    with pytest.raises(sa.exc.IntegrityError, match="identical rewrite"):
        with sqlite_markets.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE ms_markets__asset SET asset_type = 'equity' WHERE unique_identifier = 'A'"
            )


def test_the_trigger_catches_an_unconditional_upsert(sqlite_markets, monkeypatch) -> None:
    _asset(sqlite_markets.context, "A")
    # Every row differs: the update runs as it did before #62.
    monkeypatch.setattr(crud, "_differs", lambda target, value, source, *, dialect: sa.true())

    from metatables.api.backend.backends.contracts import SQLExecutionError

    with pytest.raises(SQLExecutionError, match="identical rewrite of ms_markets__asset"):
        _asset(sqlite_markets.context, "A")


def test_a_new_row_is_inserted(sqlite_markets) -> None:
    [row] = _rows(_asset(sqlite_markets.context, "A"))

    assert row["unique_identifier"] == "A"
    assert row[UPSERT_STATUS_COLUMN] == "inserted"
    assert "upsert_index" not in row
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 1


def test_an_unchanged_repeat_returns_its_row_without_rewriting_it(sqlite_markets) -> None:
    [first] = _rows(_asset(sqlite_markets.context, "A"))

    [again] = _rows(_asset(sqlite_markets.context, "A"))

    assert again[UPSERT_STATUS_COLUMN] == "unchanged"
    assert again["uid"] == first["uid"]
    assert again["asset_type"] == "equity"
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 1


def test_a_changed_row_is_updated(sqlite_markets) -> None:
    [first] = _rows(_asset(sqlite_markets.context, "A"))

    [changed] = _rows(_asset(sqlite_markets.context, "A", asset_type="bond"))

    assert changed[UPSERT_STATUS_COLUMN] == "updated"
    assert changed["uid"] == first["uid"]
    assert changed["asset_type"] == "bond"


def test_a_bulk_upsert_reports_every_row_in_input_order(sqlite_markets) -> None:
    _asset(sqlite_markets.context, "B")
    _asset(sqlite_markets.context, "C")

    result = bulk_upsert_model(
        sqlite_markets.context,
        model=AssetTable,
        values=[
            {"unique_identifier": "C", "asset_type": "bond"},
            {"unique_identifier": "A", "asset_type": "equity"},
            {"unique_identifier": "B", "asset_type": "equity"},
        ],
        conflict_columns=("unique_identifier",),
    )

    assert [(row["unique_identifier"], row[UPSERT_STATUS_COLUMN]) for row in _rows(result)] == [
        ("C", "updated"),
        ("A", "inserted"),
        ("B", "unchanged"),
    ]
    assert result["row_count"] == 3


def test_a_json_column_with_the_same_value_is_unchanged(sqlite_markets) -> None:
    [asset] = _rows(_asset(sqlite_markets.context, "A"))
    values = {
        "asset_uid": asset["uid"],
        "figi": "BBG000B9XRY4",
        "raw_payload": {"figi": "BBG000B9XRY4", "name": "APPLE INC"},
    }

    def upsert(payload):
        [row] = _rows(
            upsert_model(
                sqlite_markets.context,
                model=OpenFigiAssetDetailsTable,
                values=payload,
                conflict_columns=("asset_uid",),
            )
        )
        return row

    assert upsert(values)[UPSERT_STATUS_COLUMN] == "inserted"
    assert upsert(values)[UPSERT_STATUS_COLUMN] == "unchanged"
    changed = upsert({**values, "raw_payload": {"figi": "BBG000B9XRY4", "name": "APPLE"}})
    assert changed[UPSERT_STATUS_COLUMN] == "updated"


def test_a_row_of_keys_only_is_never_rewritten(sqlite_markets) -> None:
    category = _insert(sqlite_markets.engine, "ms_markets__assetcategory")
    [asset] = _rows(_asset(sqlite_markets.context, "A"))
    values = {"category_uid": uuid.UUID(category["uid"]), "asset_uid": asset["uid"]}

    def upsert():
        return _rows(
            bulk_upsert_model(
                sqlite_markets.context,
                model=AssetCategoryMembershipTable,
                values=[values],
                conflict_columns=("category_uid", "asset_uid"),
            )
        )

    [first] = upsert()
    [again] = upsert()

    assert first[UPSERT_STATUS_COLUMN] == "inserted"
    assert again[UPSERT_STATUS_COLUMN] == "unchanged"
    assert again["uid"] == first["uid"]


def test_the_row_api_returns_an_unchanged_row(sqlite_markets, monkeypatch) -> None:
    from msm.api.assets import Asset, CurrencySpot

    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=sqlite_markets.context),
    )
    usd = Asset.upsert(unique_identifier="USD", asset_type="currency")
    eur = Asset.upsert(unique_identifier="EUR", asset_type="currency")
    pair = {"unique_identifier": "EURUSD", "base_currency_uid": eur.uid, "quote_currency_uid": usd.uid}

    assert Asset.upsert(unique_identifier="USD", asset_type="currency") == usd
    assert [row.uid for row in Asset.upsert_many([{"unique_identifier": "USD", "asset_type": "currency"}])] == [usd.uid]
    spot = CurrencySpot.upsert(pair)
    assert CurrencySpot.upsert(pair) == spot
    assert CurrencySpot.upsert_many([pair]) == [spot]


def test_a_status_that_changed_after_it_was_read_is_read_again(sqlite_markets, monkeypatch) -> None:
    read = crud._read_upsert_statuses
    reads = []

    def stale_then_fresh(*args, **kwargs):
        statuses = read(*args, **kwargs)
        reads.append(statuses)
        return ["unchanged"] * len(statuses) if len(reads) == 1 else statuses

    monkeypatch.setattr(crud, "_read_upsert_statuses", stale_then_fresh)

    [row] = _rows(_asset(sqlite_markets.context, "A"))

    assert reads == [["inserted"], ["inserted"]]
    assert row[UPSERT_STATUS_COLUMN] == "inserted"
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 1


def test_statuses_that_keep_changing_raise_the_guard(sqlite_markets, monkeypatch) -> None:
    monkeypatch.setattr(
        crud, "_read_upsert_statuses", lambda *args, **kwargs: ["unchanged"]
    )

    with pytest.raises(MetaTableTransactionGuardError) as refused:
        _asset(sqlite_markets.context, "A")

    assert refused.value.label == crud.UPSERT_STATUS_GUARD
    assert _count(sqlite_markets.engine, "ms_markets__asset") == 0


def test_a_null_conflict_key_is_refused(sqlite_markets) -> None:
    with pytest.raises(ValueError, match="a NULL never conflicts"):
        _asset(sqlite_markets.context, None)


def test_a_conflict_key_given_twice_is_refused(sqlite_markets) -> None:
    with pytest.raises(ValueError, match="more than once"):
        bulk_upsert_model(
            sqlite_markets.context,
            model=AssetTable,
            values=[{"unique_identifier": "A"}, {"unique_identifier": "A"}],
            conflict_columns=("unique_identifier",),
        )
