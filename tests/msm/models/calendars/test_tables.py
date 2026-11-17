from __future__ import annotations

import pytest

import msm.models
from msm.models import (
    CalendarExceptionTable,
    CalendarSessionRuleTable,
    CalendarTable,
    markets_sqlalchemy_models,
)


def test_calendar_models_are_in_core_dependency_order() -> None:
    models = markets_sqlalchemy_models()

    assert models.index(CalendarTable) < models.index(CalendarSessionRuleTable)
    assert models.index(CalendarTable) < models.index(CalendarExceptionTable)


def test_per_date_calendar_tables_are_gone() -> None:
    identifiers = {model.__metatable_identifier__ for model in markets_sqlalchemy_models()}

    assert not identifiers & {"CalendarDate", "CalendarSession", "CalendarEvent"}
    for name in ("CalendarDateTable", "CalendarSessionTable", "CalendarEventTable"):
        with pytest.raises(AttributeError):
            getattr(msm.models, name)


def test_calendar_range_is_optional() -> None:
    columns = CalendarTable.__table__.columns

    assert columns["valid_from"].nullable
    assert columns["valid_to"].nullable
    assert not columns["unique_identifier"].nullable


def test_calendar_child_tables_reference_calendar_and_cascade() -> None:
    for model in [CalendarSessionRuleTable, CalendarExceptionTable]:
        keys = list(model.__table__.foreign_key_constraints)
        assert [key.referred_table.name for key in keys] == [CalendarTable.__table__.name]
        assert keys[0].ondelete == "CASCADE"


def test_calendar_natural_keys_are_unique() -> None:
    def unique_indexes(model) -> list[list[str]]:
        return [
            [column.name for column in index.columns]
            for index in model.__table__.indexes
            if index.unique
        ]

    assert unique_indexes(CalendarSessionRuleTable) == [
        ["calendar_uid", "session_label", "effective_from"]
    ]
    assert unique_indexes(CalendarExceptionTable) == [
        ["calendar_uid", "local_date", "session_label", "exception_type", "source"]
    ]


def test_local_times_are_stored_as_text() -> None:
    for model in [CalendarSessionRuleTable, CalendarExceptionTable]:
        for name in ("opens_at_local", "closes_at_local"):
            column = model.__table__.columns[name]
            assert column.type.python_type is str
            assert column.type.length == 8
            assert column.nullable
