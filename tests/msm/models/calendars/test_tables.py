from __future__ import annotations

from msm.models import (
    CalendarDateTable,
    CalendarEventTable,
    CalendarSessionTable,
    CalendarTable,
    markets_sqlalchemy_models,
)


def test_calendar_models_are_in_core_dependency_order() -> None:
    models = markets_sqlalchemy_models()

    assert models.index(CalendarTable) < models.index(CalendarDateTable)
    assert models.index(CalendarTable) < models.index(CalendarSessionTable)
    assert models.index(CalendarTable) < models.index(CalendarEventTable)


def test_calendar_table_replaces_json_only_shape() -> None:
    columns = {column.name for column in CalendarTable.__table__.columns}

    assert "unique_identifier" in columns
    assert "valid_from" in columns
    assert "valid_to" in columns
    assert "calendar_dates" not in columns
    assert "name" not in columns


def test_calendar_child_tables_reference_calendar() -> None:
    for model in [CalendarDateTable, CalendarSessionTable, CalendarEventTable]:
        fk_targets = {foreign_key.column.table.name for foreign_key in model.__table__.foreign_keys}
        assert CalendarTable.__table__.name in fk_targets


def test_calendar_natural_key_indexes_are_unique() -> None:
    date_unique_indexes = [
        [column.name for column in index.columns]
        for index in CalendarDateTable.__table__.indexes
        if index.unique
    ]
    session_unique_indexes = [
        [column.name for column in index.columns]
        for index in CalendarSessionTable.__table__.indexes
        if index.unique
    ]
    event_unique_indexes = [
        [column.name for column in index.columns]
        for index in CalendarEventTable.__table__.indexes
        if index.unique
    ]

    assert ["calendar_uid", "local_date"] in date_unique_indexes
    assert ["calendar_uid", "local_date", "session_label"] in session_unique_indexes
    assert [
        "calendar_uid",
        "event_date",
        "event_type",
        "event_label",
        "target_type",
        "target_identifier",
    ] in event_unique_indexes
