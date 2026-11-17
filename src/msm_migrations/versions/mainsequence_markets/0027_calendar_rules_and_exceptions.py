"""Store a calendar as session rules and exceptions (ADR 0055).

``CalendarDate`` held one row per calendar day and ``CalendarSession`` one per
trading day. Two tables replace them: ``CalendarSessionRule``, the regular week
of a session, and ``CalendarException``, one dated departure from it. Dates and
sessions are computed from them.

Each stored calendar is converted from its own rows, not from the library that
wrote them, so a deployment keeps the calendar it had:

- the rule of each session label is its most frequent local open and close, on
  the weekdays most of the stored dates have a session;
- every stored date the rule does not reproduce becomes an exception, with the
  calendar's ``source`` as its ``source``, or ``user`` where it has none;
- ``valid_from`` and ``valid_to`` become the first and last stored date;
- a ``timezone`` that is not an IANA name becomes ``UTC``, which keeps the stored
  instants.

The converted calendar is then computed back and compared with the stored rows.
A difference stops the revision before anything is dropped.

``CalendarEvent`` is dropped with its rows; nothing in ms-markets wrote or read
it. ``Calendar.valid_from`` and ``Calendar.valid_to`` become nullable: a calendar
with nothing to project has no last date.

The downgrade recreates the three tables empty and drops the two new ones. The
rows of the dropped tables are not restored.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import Counter, defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str = "0026"
branch_labels = None
depends_on = None

CALENDAR_TABLE = "ms_markets__calendar"
DATE_TABLE = "ms_markets__calendardate"
SESSION_TABLE = "ms_markets__calendarsession"
EVENT_TABLE = "ms_markets__calendarevent"
RULE_TABLE = "ms_markets__calendarsessionrule"
EXCEPTION_TABLE = "ms_markets__calendarexception"

RULE_GRAIN = ["calendar_uid", "session_label", "effective_from"]
RULE_GRAIN_INDEX = "uix__ms_markets__calendarsessionrule__calendar_uid_a28bd18dfb"
RULE_CALENDAR_KEY = "fk__ms_markets__calendarsessionrule__calendar_uid__m_fa980b6b27"
EXCEPTION_GRAIN = ["calendar_uid", "local_date", "session_label", "exception_type", "source"]
EXCEPTION_GRAIN_INDEX = "uix__ms_markets__calendarexception__calendar_uid__lo_08334582ca"
EXCEPTION_CALENDAR_KEY = "fk__ms_markets__calendarexception__calendar_uid__ms_f7da9f402f"

NAMESPACE = "mainsequence.markets"
USER_SOURCE = "user"
DEFAULT_SESSION_LABEL = "regular"
WHOLE_DAY = ""

CLOSED = "CLOSED"
EARLY_CLOSE = "EARLY_CLOSE"
LATE_OPEN = "LATE_OPEN"
OPEN = "OPEN"

_INSERT_ROWS = 500


def _info(identifier: str) -> dict[str, str]:
    return {"namespace": NAMESPACE, "identifier": identifier, "markets_storage_app": "ms_markets"}


def _create_rule_table() -> None:
    op.create_table(
        RULE_TABLE,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("calendar_uid", sa.Uuid(), nullable=False),
        sa.Column("session_label", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("weekdays", sa.String(length=7), nullable=False),
        sa.Column("opens_at_local", sa.String(length=8), nullable=True),
        sa.Column("closes_at_local", sa.String(length=8), nullable=True),
        sa.Column("open_day_offset", sa.SmallInteger(), nullable=False),
        sa.Column("close_day_offset", sa.SmallInteger(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["calendar_uid"],
            [f"{CALENDAR_TABLE}.uid"],
            name=op.f(RULE_CALENDAR_KEY),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__calendarsessionrule")),
        info=_info("CalendarSessionRule"),
    )
    with op.batch_alter_table(RULE_TABLE, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(RULE_GRAIN_INDEX), RULE_GRAIN, unique=True)


def _create_exception_table() -> None:
    op.create_table(
        EXCEPTION_TABLE,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("calendar_uid", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("session_label", sa.String(length=64), nullable=False),
        sa.Column("exception_type", sa.String(length=32), nullable=False),
        sa.Column("opens_at_local", sa.String(length=8), nullable=True),
        sa.Column("closes_at_local", sa.String(length=8), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["calendar_uid"],
            [f"{CALENDAR_TABLE}.uid"],
            name=op.f(EXCEPTION_CALENDAR_KEY),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__calendarexception")),
        info=_info("CalendarException"),
    )
    with op.batch_alter_table(EXCEPTION_TABLE, schema=None) as batch_op:
        batch_op.create_index(batch_op.f(EXCEPTION_GRAIN_INDEX), EXCEPTION_GRAIN, unique=True)


def _tables(bind: sa.Connection) -> dict[str, sa.Table]:
    """The calendar tables as the database has them.

    They are reflected, so a uid is read and written in the dialect's own form:
    a UUID on PostgreSQL and 32 hex characters on SQLite.
    """

    metadata = sa.MetaData()
    names = {
        "calendar": CALENDAR_TABLE,
        "date": DATE_TABLE,
        "session": SESSION_TABLE,
        "rule": RULE_TABLE,
        "exception": EXCEPTION_TABLE,
    }
    existing = set(sa.inspect(bind).get_table_names())
    metadata.reflect(bind, only=[name for name in names.values() if name in existing])
    return {key: metadata.tables[name] for key, name in names.items() if name in metadata.tables}


def _new_uid(bind: sa.Connection) -> object:
    value = uuid.uuid4()
    return value if bind.dialect.name == "postgresql" else value.hex


def _local_parts(
    instant: dt.datetime | None,
    local_date: dt.date,
    zone: ZoneInfo,
) -> tuple[dt.time | None, int]:
    """A stored UTC instant as a wall-clock time and its day offset from the session's date."""

    if instant is None:
        return None, 0
    if instant.tzinfo is None:
        # SQLite returns the stored UTC instant without its offset.
        instant = instant.replace(tzinfo=dt.UTC)
    local = instant.astimezone(zone)
    return local.time().replace(microsecond=0), (local.date() - local_date).days


def _text(value: dt.time | None) -> str | None:
    return None if value is None else value.strftime("%H:%M:%S")


def _later(first: dt.time | None, second: dt.time | None) -> bool:
    return first is not None and second is not None and first > second


def calendar_zone(timezone: str | None) -> ZoneInfo:
    """The calendar's timezone, or UTC when its name is not an IANA timezone.

    ``Calendar.timezone`` was free text and the stored sessions were UTC instants,
    so a name no timezone database knows never mattered. Local times need a real
    one: such a calendar is converted in UTC and its ``timezone`` becomes ``UTC``,
    which keeps every stored instant.
    """

    try:
        return ZoneInfo(timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def convert_calendar(
    *,
    unique_identifier: str,
    timezone: str,
    source: str | None,
    date_rows: list[tuple[dt.date, bool, str | None]],
    session_rows: list[tuple[dt.date, str, dt.datetime | None, dt.datetime | None, bool]],
) -> dict | None:
    """Turn one calendar's stored date and session rows into rules and exceptions.

    Returns None for a calendar with no stored date or session. Raises when the
    converted calendar would not reproduce the stored rows.
    """

    zone = calendar_zone(timezone)
    flags = {local_date: bool(is_business_day) for local_date, is_business_day, _ in date_rows}
    names = {local_date: name for local_date, _, name in date_rows if name}
    stored: dict[str, dict[dt.date, tuple]] = defaultdict(dict)
    primary: dict[str, Counter] = defaultdict(Counter)
    for local_date, label, opens_at, closes_at, is_primary in session_rows:
        open_time, open_offset = _local_parts(opens_at, local_date, zone)
        close_time, close_offset = _local_parts(closes_at, local_date, zone)
        stored[label][local_date] = (open_time, close_time, open_offset, close_offset)
        primary[label][bool(is_primary)] += 1

    held = {local_date for sessions in stored.values() for local_date in sessions}
    for local_date, is_business_day in flags.items():
        if is_business_day and local_date not in held:
            # A business day stored without a session: a date-only session keeps it one.
            stored[DEFAULT_SESSION_LABEL][local_date] = (None, None, 0, 0)
            primary[DEFAULT_SESSION_LABEL][True] += 1
        elif not is_business_day and local_date in held:
            raise RuntimeError(
                f"Calendar {unique_identifier!r} stores {local_date.isoformat()} as not a "
                "business day and also stores a session on it. Correct the rows first."
            )

    covered = sorted(set(flags) | held)
    if not covered:
        return None
    dates_per_weekday = Counter(local_date.weekday() for local_date in covered)
    row_source = source or USER_SOURCE
    single_label = len(stored) <= 1
    rules: list[dict] = []
    exceptions: list[dict] = []

    for label in sorted(stored):
        sessions = stored[label]
        hours = Counter(sessions.values()).most_common(1)[0][0]
        rule_opens, rule_closes, rule_open_offset, rule_close_offset = hours
        sessions_per_weekday = Counter(local_date.weekday() for local_date in sessions)
        weekdays = "".join(
            "1" if sessions_per_weekday[weekday] * 2 > dates_per_weekday[weekday] else "0"
            for weekday in range(7)
        )
        rules.append(
            {
                "session_label": label,
                "effective_from": covered[0],
                "effective_to": None,
                "weekdays": weekdays,
                "opens_at_local": _text(rule_opens),
                "closes_at_local": _text(rule_closes),
                "open_day_offset": rule_open_offset,
                "close_day_offset": rule_close_offset,
                "is_primary": primary[label].most_common(1)[0][0],
            }
        )

        def add(local_date: dt.date, exception_type: str, opens=None, closes=None) -> None:
            closed = exception_type == CLOSED
            exceptions.append(
                {
                    "local_date": local_date,
                    "session_label": WHOLE_DAY if closed and single_label else label,
                    "exception_type": exception_type,
                    "opens_at_local": _text(opens),
                    "closes_at_local": _text(closes),
                    "name": names.get(local_date) if closed else None,
                    "source": row_source,
                    "metadata_json": None,
                }
            )

        for local_date in covered:
            scheduled = weekdays[local_date.weekday()] == "1"
            actual = sessions.get(local_date)
            if actual is None:
                if scheduled:
                    add(local_date, CLOSED)
                continue
            opens, closes, open_offset, close_offset = actual
            if (open_offset, close_offset) != (rule_open_offset, rule_close_offset):
                raise RuntimeError(
                    f"Calendar {unique_identifier!r} session {label!r} on "
                    f"{local_date.isoformat()} opens or closes on another day than its "
                    "regular week. An exception cannot store that; correct the row first."
                )
            same_open, same_close = opens == rule_opens, closes == rule_closes
            if scheduled and same_open and same_close:
                continue
            later_open, earlier_close = _later(opens, rule_opens), _later(rule_closes, closes)
            if scheduled and (same_open or later_open) and (same_close or earlier_close):
                if later_open:
                    add(local_date, LATE_OPEN, opens=opens)
                if earlier_close:
                    add(local_date, EARLY_CLOSE, closes=closes)
                continue
            add(
                local_date,
                OPEN,
                opens=None if same_open else opens,
                closes=None if same_close else closes,
            )

    _verify(unique_identifier, covered, stored, rules, exceptions)
    return {
        "valid_from": covered[0],
        "valid_to": covered[-1],
        "timezone": zone.key,
        "rules": rules,
        "exceptions": exceptions,
    }


def _verify(
    unique_identifier: str,
    covered: list[dt.date],
    stored: dict[str, dict[dt.date, tuple]],
    rules: list[dict],
    exceptions: list[dict],
) -> None:
    """Compute the converted calendar back and compare it with the stored sessions."""

    by_date: dict[dt.date, list[dict]] = defaultdict(list)
    for row in exceptions:
        by_date[row["local_date"]].append(row)
    for rule in rules:
        label = rule["session_label"]
        for local_date in covered:
            mine = [row for row in by_date[local_date] if row["session_label"] in (WHOLE_DAY, label)]
            types = {row["exception_type"] for row in mine}
            computed = None
            scheduled = rule["weekdays"][local_date.weekday()] == "1"
            if CLOSED not in types and (scheduled or OPEN in types):
                opens, closes = rule["opens_at_local"], rule["closes_at_local"]
                for row in mine:
                    if row["exception_type"] in (OPEN, LATE_OPEN) and row["opens_at_local"]:
                        opens = row["opens_at_local"]
                    if row["exception_type"] in (OPEN, EARLY_CLOSE) and row["closes_at_local"]:
                        closes = row["closes_at_local"]
                computed = (opens, closes)
            actual = stored[label].get(local_date)
            expected = None if actual is None else (_text(actual[0]), _text(actual[1]))
            if computed != expected:
                raise RuntimeError(
                    f"Calendar {unique_identifier!r}: the converted session {label!r} on "
                    f"{local_date.isoformat()} is {computed}, and the stored one is {expected}."
                )


def _convert_calendars() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    calendars = bind.execute(
        sa.select(
            tables["calendar"].c.uid,
            tables["calendar"].c.unique_identifier,
            tables["calendar"].c.timezone,
            tables["calendar"].c.source,
        )
    ).all()
    for calendar_uid, unique_identifier, timezone, source in calendars:
        date_rows = bind.execute(
            sa.select(
                tables["date"].c.local_date,
                tables["date"].c.is_business_day,
                tables["date"].c.holiday_name,
            ).where(tables["date"].c.calendar_uid == calendar_uid)
        ).all()
        session_rows = bind.execute(
            sa.select(
                tables["session"].c.local_date,
                tables["session"].c.session_label,
                tables["session"].c.opens_at,
                tables["session"].c.closes_at,
                tables["session"].c.is_primary,
            ).where(tables["session"].c.calendar_uid == calendar_uid)
        ).all()
        converted = convert_calendar(
            unique_identifier=unique_identifier,
            timezone=timezone,
            source=source,
            date_rows=[tuple(row) for row in date_rows],
            session_rows=[tuple(row) for row in session_rows],
        )
        if converted is None:
            continue
        for name in ("rule", "exception"):
            rows = [
                {"uid": _new_uid(bind), "calendar_uid": calendar_uid, **row}
                for row in converted[f"{name}s"]
            ]
            for index in range(0, len(rows), _INSERT_ROWS):
                bind.execute(tables[name].insert(), rows[index : index + _INSERT_ROWS])
        bind.execute(
            tables["calendar"]
            .update()
            .where(tables["calendar"].c.uid == calendar_uid)
            .values(
                valid_from=converted["valid_from"],
                valid_to=converted["valid_to"],
                timezone=converted["timezone"],
            )
        )


def upgrade() -> None:
    _create_rule_table()
    _create_exception_table()
    _convert_calendars()

    for table in (DATE_TABLE, SESSION_TABLE, EVENT_TABLE):
        op.drop_table(table)
    with op.batch_alter_table(CALENDAR_TABLE, schema=None) as batch_op:
        batch_op.alter_column("valid_from", existing_type=sa.Date(), nullable=True)
        batch_op.alter_column("valid_to", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    calendar = _tables(bind)["calendar"]
    # The columns were required; a calendar without a range gets the widest one.
    bind.execute(
        calendar.update()
        .where(calendar.c.valid_from.is_(None))
        .values(valid_from=dt.date(1900, 1, 1))
    )
    bind.execute(
        calendar.update().where(calendar.c.valid_to.is_(None)).values(valid_to=dt.date(2200, 12, 31))
    )
    with op.batch_alter_table(CALENDAR_TABLE, schema=None) as batch_op:
        batch_op.alter_column("valid_from", existing_type=sa.Date(), nullable=False)
        batch_op.alter_column("valid_to", existing_type=sa.Date(), nullable=False)

    op.drop_table(EXCEPTION_TABLE)
    op.drop_table(RULE_TABLE)

    op.create_table(
        DATE_TABLE,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("calendar_uid", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("is_business_day", sa.Boolean(), nullable=False),
        sa.Column("is_holiday", sa.Boolean(), nullable=False),
        sa.Column("is_weekend", sa.Boolean(), nullable=False),
        sa.Column("is_early_close", sa.Boolean(), nullable=False),
        sa.Column("holiday_name", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["calendar_uid"],
            [f"{CALENDAR_TABLE}.uid"],
            name=op.f("fk__ms_markets__calendardate__calendar_uid__ms_marke_d1ea943953"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__calendardate")),
        info=_info("CalendarDate"),
    )
    with op.batch_alter_table(DATE_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendardate__calendar_uid__is_business_day"),
            ["calendar_uid", "is_business_day"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendardate__local_date"), ["local_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("uix__ms_markets__calendardate__calendar_uid__local_date"),
            ["calendar_uid", "local_date"],
            unique=True,
        )

    op.create_table(
        EVENT_TABLE,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("calendar_uid", sa.Uuid(), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_label", sa.String(length=255), nullable=False),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_uid", sa.Uuid(), nullable=True),
        sa.Column("target_identifier", sa.String(length=255), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["calendar_uid"],
            [f"{CALENDAR_TABLE}.uid"],
            name=op.f("fk__ms_markets__calendarevent__calendar_uid__ms_mark_82f9e66428"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__calendarevent")),
        info=_info("CalendarEvent"),
    )
    with op.batch_alter_table(EVENT_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendarevent__calendar_uid__event_date"),
            ["calendar_uid", "event_date"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendarevent__event_type"), ["event_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendarevent__target_type__target_uid"),
            ["target_type", "target_uid"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("uix__ms_markets__calendarevent__calendar_uid__event_5ff36d9c47"),
            [
                "calendar_uid",
                "event_date",
                "event_type",
                "event_label",
                "target_type",
                "target_identifier",
            ],
            unique=True,
        )

    op.create_table(
        SESSION_TABLE,
        sa.Column("uid", sa.Uuid(), nullable=False),
        sa.Column("calendar_uid", sa.Uuid(), nullable=False),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("session_label", sa.String(length=64), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ["calendar_uid"],
            [f"{CALENDAR_TABLE}.uid"],
            name=op.f("fk__ms_markets__calendarsession__calendar_uid__ms_ma_1b8e1a05d3"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("uid", name=op.f("pk__ms_markets__calendarsession")),
        info=_info("CalendarSession"),
    )
    with op.batch_alter_table(SESSION_TABLE, schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendarsession__calendar_uid__is_primary"),
            ["calendar_uid", "is_primary"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix__ms_markets__calendarsession__local_date"), ["local_date"], unique=False
        )
        batch_op.create_index(
            batch_op.f("uix__ms_markets__calendarsession__calendar_uid__loca_30b16604ba"),
            ["calendar_uid", "local_date", "session_label"],
            unique=True,
        )
