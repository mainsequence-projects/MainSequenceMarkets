"""Row classes count, bulk-upsert and order their filters (ADR 0047 remote parity)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from msm.api.accounts import AccountHoldingsSet
from msm.api.assets import Asset, AssetType


@pytest.fixture
def runtime(monkeypatch):
    monkeypatch.setattr(
        "msm.bootstrap.resolve_runtime",
        lambda **kwargs: SimpleNamespace(context=SimpleNamespace(timeout=None)),
    )


def test_upsert_many_validates_each_payload_and_upserts_once(monkeypatch, runtime) -> None:
    calls: list[dict[str, Any]] = []

    def bulk_upsert_model(context, *, model, values, conflict_columns):
        calls.append({"model": model.__name__, "values": values, "keys": conflict_columns})
        return {"rows": [{"uid": str(uuid.uuid4()), **value} for value in values]}

    monkeypatch.setattr("msm.repositories.crud.bulk_upsert_model", bulk_upsert_model)

    rows = Asset.upsert_many(
        [{"unique_identifier": "A", "asset_type": "Equity"}, {"unique_identifier": "B"}]
    )

    assert [row.unique_identifier for row in rows] == ["A", "B"]
    assert calls == [
        {
            "model": "AssetTable",
            "values": [{"unique_identifier": "A", "asset_type": "equity"}, {"unique_identifier": "B"}],
            "keys": ("unique_identifier",),
        }
    ]
    assert Asset.upsert_many([]) == []


def test_upsert_many_uses_the_types_upsert_payload(monkeypatch, runtime) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(
        "msm.repositories.crud.bulk_upsert_model",
        lambda context, *, model, values, conflict_columns: seen.extend(values)
        or {"rows": [{"uid": str(uuid.uuid4()), **value} for value in values]},
    )

    AssetType.upsert_many([{"asset_type": "Equity", "display_name": "Equity"}])

    assert seen[0]["asset_type"] == "equity"


def test_count_and_ordered_filters_compile_to_one_statement(monkeypatch, runtime) -> None:
    account_uid = uuid.uuid4()
    seen: dict[str, Any] = {}

    def search_model(context, **kwargs):
        seen["search"] = kwargs
        return {"rows": []}

    def count_model(context, **kwargs):
        seen["count"] = kwargs
        return {"rows": [{"count": 7}]}

    monkeypatch.setattr("msm.repositories.crud.search_model", search_model)
    monkeypatch.setattr("msm.repositories.crud.count_model", count_model)

    AccountHoldingsSet.filter(
        account_uid=account_uid, order_by="-time_index", limit=10, offset=20
    )
    assert AccountHoldingsSet.count(account_uid=account_uid) == 7

    assert seen["search"]["filters"] == {"account_uid": account_uid}
    assert seen["search"]["order_by"] == ["-time_index"]
    assert (seen["search"]["limit"], seen["search"]["offset"]) == (10, 20)
    assert seen["count"]["filters"] == {"account_uid": account_uid}


def test_in_filters_and_unknown_order_columns(monkeypatch, runtime) -> None:
    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "msm.repositories.crud.search_model",
        lambda context, **kwargs: seen.update(kwargs) or {"rows": []},
    )

    Asset.filter(unique_identifier__in=["A", "B"])
    assert seen["in_filters"] == {"unique_identifier": ["A", "B"]}

    with pytest.raises(ValueError, match="unknown column"):
        Asset.filter(order_by="-no_such_column")


def test_search_model_orders_by_validated_columns(offline_postgresql_runtime) -> None:
    from msm.models import AccountHoldingsSetTable
    from msm.repositories.crud import build_search_model_operation
    from msm.repositories.base import MarketsRepositoryContext

    operation = build_search_model_operation(
        MarketsRepositoryContext(),
        model=AccountHoldingsSetTable,
        order_by=["-time_index", "uid"],
        limit=5,
    )
    sql = str(getattr(operation, "sql", operation))

    assert "ORDER BY" in sql.upper()
    assert "DESC" in sql.upper()


def test_range_filters_split_by_suffix_and_compile_to_bounds(monkeypatch, runtime) -> None:
    from msm.api.calendars import CalendarSession
    from msm.models import CalendarSessionTable
    from msm.repositories.crud import _filtered_model_select

    seen: dict[str, Any] = {}
    monkeypatch.setattr(
        "msm.repositories.crud.search_model",
        lambda context, **kwargs: seen.update(kwargs) or {"rows": []},
    )

    CalendarSession.filter(
        session_label="regular",
        local_date__gte=dt.date(2026, 1, 1),
        local_date__lt=dt.date(2026, 2, 1),
    )

    assert seen["filters"] == {"session_label": "regular"}
    assert seen["range_filters"] == {
        "local_date": {"gte": dt.date(2026, 1, 1), "lt": dt.date(2026, 2, 1)}
    }
    statement = _filtered_model_select(CalendarSessionTable, range_filters=seen["range_filters"])
    compiled = statement.compile()
    assert "local_date >= :local_date_1" in str(compiled)
    assert "local_date < :local_date_2" in str(compiled)
    assert compiled.params == {"local_date_1": dt.date(2026, 1, 1), "local_date_2": dt.date(2026, 2, 1)}
    with pytest.raises(ValueError, match="Unknown range lookup"):
        _filtered_model_select(CalendarSessionTable, range_filters={"local_date": {"after": 1}})
    with pytest.raises(ValueError):
        CalendarSession.filter(unknown_column__gte=1)


def test_index_upsert_many_keeps_the_calculation_method_guard(monkeypatch, runtime) -> None:
    from msm.api.indices import Index

    existing_uid = uuid.uuid4()
    written: list[Any] = []

    def search_model(context, *, model, in_filters=None, **kwargs):
        return {
            "rows": [
                {
                    "uid": str(existing_uid),
                    "unique_identifier": "RATE28",
                    "index_type": "interest_rate",
                    "display_name": "Rate 28",
                    "calculation_method": "custom",
                    "value_format": "percent",
                }
            ]
        }

    monkeypatch.setattr("msm.repositories.crud.search_model", search_model)
    monkeypatch.setattr(
        "msm.repositories.crud.count_model",
        lambda context, *, model, filters=None, **kwargs: {"rows": [{"count": 1}]},
    )
    monkeypatch.setattr(
        "msm.repositories.crud.bulk_upsert_model",
        lambda context, *, model, values, conflict_columns: written.extend(values)
        or {"rows": [{"uid": str(uuid.uuid4()), **value} for value in values]},
    )
    payload = {
        "unique_identifier": "RATE28",
        "index_type": "interest_rate",
        "display_name": "Rate 28",
        "value_format": "percent",
    }

    with pytest.raises(ValueError, match="calculation_method cannot change"):
        Index.upsert_many([{**payload, "calculation_method": "formula"}])
    assert written == []

    rows = Index.upsert_many([{**payload, "calculation_method": "custom"}])
    assert [row.unique_identifier for row in rows] == ["RATE28"]
