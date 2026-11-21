"""Linking assets to their trading calendars in bulk, on a SQLite DataSource (ADR 0057)."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from msm.api.assets import (
    Asset,
    AssetCalendar,
    AssetCalendarLinkResult,
    AssetType,
    AssetUpsert,
    Bond,
    CurrencySpot,
)
from msm.api.calendars import Calendar
from msm.api.issuers import Issuer
from msm.api.remote import WRITE_OPERATIONS, remote_operations
from msm.repositories.asset_calendars import (
    LINK_IDENTIFIERS_PER_STATEMENT,
    link_assets_statements,
)
from msm.services import register_account
from msm.services.calendars import CalendarInUseConflictError, delete_calendar_record
from tests.support.account_registration import _record_operations, _request
from tests.support.sqlite_markets import _rows, serve_row_operations


@pytest.fixture
def markets(sqlite_markets, monkeypatch):
    serve_row_operations(monkeypatch, sqlite_markets)
    AssetType.upsert(asset_type="equity", display_name="Equity")
    sqlite_markets.nyse = Calendar.create(
        unique_identifier="NYSE", display_name="NYSE", calendar_type="TRADING"
    )
    sqlite_markets.desk = Calendar.create(
        unique_identifier="DESK", display_name="Desk", calendar_type="CUSTOM"
    )
    return sqlite_markets


def assets(*identifiers: str) -> list[Asset]:
    return Asset.upsert_many(
        [{"unique_identifier": identifier, "asset_type": "equity"} for identifier in identifiers]
    )


def links(markets) -> dict[str, str]:
    """Each linked asset's identifier with its calendar's identifier."""

    return {
        row["asset"]: row["calendar"]
        for row in _rows(
            markets.engine,
            "SELECT a.unique_identifier AS asset, c.unique_identifier AS calendar "
            "FROM ms_markets__assetcalendar l "
            "JOIN ms_markets__asset a ON a.uid = l.asset_uid "
            "JOIN ms_markets__calendar c ON c.uid = l.calendar_uid ORDER BY 1",
        )
    }


def writes(markets) -> int:
    return sum(1 for sql in markets.statements if not sql.lstrip().upper().startswith("SELECT"))


def test_link_many_links_assets_by_identifier_in_one_transaction(markets, monkeypatch) -> None:
    assets("A0", "A1", "A2")
    operations = _record_operations(monkeypatch)

    result = AssetCalendar.link_many(["A0", "A1", "A2", "NOPE"], calendar_identifier="NYSE")

    assert isinstance(result, AssetCalendarLinkResult)
    assert result.calendar_uid == markets.nyse.uid
    assert result.model_dump(exclude={"calendar_uid"}) == {
        "linked": ["A0", "A1", "A2"],
        "moved": [],
        "unchanged": [],
        "kept": [],
        "unknown": ["NOPE"],
    }
    # The calendar, the current links, then one write.
    assert operations == ["read", "read", "transaction"]
    assert links(markets) == {"A0": "NYSE", "A1": "NYSE", "A2": "NYSE"}


def test_link_many_moves_or_keeps_an_asset_on_another_calendar(markets) -> None:
    assets("A0", "A1", "A2")
    AssetCalendar.link_many(["A0", "A1"], calendar_identifier="NYSE")

    moved = AssetCalendar.link_many(["A0", "A2"], calendar_uid=markets.desk.uid)
    kept = AssetCalendar.link_many(["A1", "A2"], calendar_uid=markets.desk.uid, relink=False)

    assert (moved.linked, moved.moved) == (["A2"], ["A0"])
    assert (kept.kept, kept.unchanged, kept.linked) == (["A1"], ["A2"], [])
    assert links(markets) == {"A0": "DESK", "A1": "NYSE", "A2": "DESK"}


def test_link_many_writes_nothing_when_nothing_changes(markets) -> None:
    assets("A0", "A1")
    AssetCalendar.link_many(["A0", "A1"], calendar_identifier="NYSE")
    before = writes(markets)

    again = AssetCalendar.link_many(["A1", "A0", "A0"], calendar_identifier="NYSE")

    assert again.unchanged == ["A1", "A0"]
    assert writes(markets) == before
    only_unknown = AssetCalendar.link_many(["NOPE"], calendar_identifier="NYSE")
    assert (only_unknown.unknown, writes(markets)) == (["NOPE"], before)


def test_link_many_refuses_an_unknown_calendar_and_bad_arguments(markets) -> None:
    assets("A0")
    before = writes(markets)

    with pytest.raises(LookupError, match="Calendar 'MISSING' was not found"):
        AssetCalendar.link_many(["A0"], calendar_identifier="MISSING")
    with pytest.raises(LookupError):
        AssetCalendar.link_many(["A0"], calendar_uid=uuid.uuid4())
    with pytest.raises(ValueError, match="calendar_uid or calendar_identifier, not both"):
        AssetCalendar.link_many(["A0"], calendar_uid=markets.nyse.uid, calendar_identifier="NYSE")
    with pytest.raises(ValueError, match="calendar_uid or calendar_identifier, not both"):
        AssetCalendar.link_many(["A0"])
    with pytest.raises(ValueError, match="at least one asset"):
        AssetCalendar.link_many([], calendar_identifier="NYSE")
    assert writes(markets) == before
    assert links(markets) == {}


def test_link_many_splits_a_long_list_into_statements_of_one_transaction(markets, monkeypatch) -> None:
    count = LINK_IDENTIFIERS_PER_STATEMENT + 500
    identifiers = [f"BULK{index:05d}" for index in range(count)]
    assets(*identifiers)
    operations = _record_operations(monkeypatch)
    before = writes(markets)

    result = AssetCalendar.link_many(identifiers, calendar_identifier="NYSE")

    assert len(result.linked) == count
    assert operations.count("transaction") == 1
    assert writes(markets) - before == 2
    assert AssetCalendar.count(calendar_uid=markets.nyse.uid) == count
    statements = link_assets_statements(
        {markets.nyse.uid: identifiers}, dialect="postgresql", relink=True
    )
    assert len(statements) == 2


def test_unlinked_assets_lists_what_a_price_update_would_refuse(markets) -> None:
    AssetType.upsert(asset_type="future", display_name="Future")
    assets("A0", "A1", "A2")
    Asset.upsert(unique_identifier="F0", asset_type="future")
    AssetCalendar.link_many(["A1"], calendar_identifier="NYSE")

    assert [asset.unique_identifier for asset in AssetCalendar.unlinked_assets()] == ["A0", "A2", "F0"]
    assert [a.unique_identifier for a in AssetCalendar.unlinked_assets(asset_type="Future")] == ["F0"]
    assert [a.unique_identifier for a in AssetCalendar.unlinked_assets(limit=1, offset=1)] == ["A2"]


def test_a_link_is_deleted_by_its_asset_uid_and_delete_is_offered_remotely(markets) -> None:
    (asset,) = assets("A0")
    AssetCalendar.link_many(["A0"], calendar_identifier="NYSE")

    AssetCalendar.delete(asset.uid)

    assert links(markets) == {}
    assert "delete" in vars(AssetCalendar)
    operations = remote_operations(AssetCalendar)
    assert {"delete", "link_many", "unlinked_assets"} <= set(operations)
    assert "link_many" in WRITE_OPERATIONS


def test_bulk_asset_registration_links_each_asset_to_the_calendar_it_names(markets, monkeypatch) -> None:
    operations = _record_operations(monkeypatch)

    registered = Asset.upsert_many(
        [
            {"unique_identifier": "B0", "asset_type": "equity", "calendar_identifier": "NYSE"},
            {"unique_identifier": "B1", "asset_type": "equity", "calendar_uid": markets.desk.uid},
            {"unique_identifier": "B2", "asset_type": "equity", "calendar_identifier": "NYSE"},
            {"unique_identifier": "B3", "asset_type": "equity"},
        ]
    )

    assert [asset.unique_identifier for asset in registered] == ["B0", "B1", "B2", "B3"]
    assert not hasattr(registered[0], "calendar_identifier")
    assert links(markets) == {"B0": "NYSE", "B1": "DESK", "B2": "NYSE"}
    # All links of the call go in one transaction, after the assets.
    assert operations.count("transaction") == 1 or operations[-1] == "transaction"

    # Naming a calendar again moves the asset; leaving it out keeps the link.
    Asset.upsert_many(
        [
            {"unique_identifier": "B0", "asset_type": "equity", "calendar_identifier": "DESK"},
            {"unique_identifier": "B1", "asset_type": "equity"},
        ]
    )
    assert links(markets) == {"B0": "DESK", "B1": "DESK", "B2": "NYSE"}


def test_a_bulk_registration_without_calendars_reads_and_writes_nothing_more(markets) -> None:
    before = len(markets.statements)
    assets("C0", "C1")
    plain = len(markets.statements) - before

    before = len(markets.statements)
    Asset.upsert_many(
        [{"unique_identifier": "C2", "asset_type": "equity"}, {"unique_identifier": "C3", "asset_type": "equity"}]
    )

    assert len(markets.statements) - before == plain
    assert links(markets) == {}


def test_single_asset_writes_take_a_calendar_too(markets) -> None:
    created = Asset.create(unique_identifier="D0", asset_type="equity", calendar_identifier="NYSE")
    upserted = Asset.upsert(unique_identifier="D1", asset_type="equity", calendar_uid=markets.desk.uid)
    Asset.upsert(unique_identifier="D2", asset_type="equity")

    assert (created.unique_identifier, upserted.unique_identifier) == ("D0", "D1")
    assert links(markets) == {"D0": "NYSE", "D1": "DESK"}


def test_an_unknown_calendar_fails_the_registration_call(markets) -> None:
    with pytest.raises(LookupError, match="Calendar 'MISSING' was not found"):
        Asset.upsert_many(
            [
                {"unique_identifier": "E0", "asset_type": "equity", "calendar_identifier": "NYSE"},
                {"unique_identifier": "E1", "asset_type": "equity", "calendar_identifier": "MISSING"},
            ]
        )

    # The assets were written; no link was. The same call with a stored calendar finishes it.
    assert links(markets) == {}
    assert [a.unique_identifier for a in AssetCalendar.unlinked_assets()] == ["E0", "E1"]
    Asset.upsert_many(
        [
            {"unique_identifier": "E0", "asset_type": "equity", "calendar_identifier": "NYSE"},
            {"unique_identifier": "E1", "asset_type": "equity", "calendar_identifier": "DESK"},
        ]
    )
    assert links(markets) == {"E0": "NYSE", "E1": "DESK"}


def test_a_payload_names_its_calendar_once() -> None:
    with pytest.raises(ValidationError, match="not both"):
        AssetUpsert(
            unique_identifier="X",
            asset_type="equity",
            calendar_uid=uuid.uuid4(),
            calendar_identifier="NYSE",
        )
    with pytest.raises(ValidationError):
        AssetUpsert(unique_identifier="X", asset_type="equity", calendar_identifier="")
    assert AssetUpsert(unique_identifier="X", asset_type="equity").calendar_identifier is None


def test_every_asset_registration_payload_carries_the_calendar_reference() -> None:
    from msm.api.assets import BondUpsert, CurrencySpotUpsert, TradingCalendarReference
    from msm.api.derivatives import FutureUpsert

    for payload in (AssetUpsert, CurrencySpotUpsert, BondUpsert, FutureUpsert):
        assert issubclass(payload, TradingCalendarReference)
        assert {"calendar_uid", "calendar_identifier"} <= set(payload.model_fields)


def test_composite_registrations_take_a_calendar(markets) -> None:
    usd = Asset.get_or_create_currency("USD")
    eur = Asset.get_or_create_currency("EUR")
    gbp = Asset.get_or_create_currency("GBP")
    issuer = Issuer.upsert(unique_identifier="ACME", display_name="Acme")

    CurrencySpot.upsert(
        unique_identifier="EURUSD",
        base_currency_uid=eur.uid,
        quote_currency_uid=usd.uid,
        calendar_identifier="DESK",
    )
    CurrencySpot.upsert_many(
        [
            {"unique_identifier": "GBPUSD", "base_currency_uid": gbp.uid, "quote_currency_uid": usd.uid, "calendar_identifier": "DESK"},
            {"unique_identifier": "EURGBP", "base_currency_uid": eur.uid, "quote_currency_uid": gbp.uid},
        ]
    )
    Bond.upsert(
        unique_identifier="ACME-2030",
        issuer_uid=issuer.uid,
        currency_asset_uid=usd.uid,
        issue_date=dt.date(2020, 1, 1),
        maturity_date=dt.date(2030, 1, 1),
        status="active",
        calendar_identifier="NYSE",
    )

    assert links(markets) == {"ACME-2030": "NYSE", "EURUSD": "DESK", "GBPUSD": "DESK"}


def test_account_registration_links_new_assets_in_its_one_transaction(markets, monkeypatch) -> None:
    request = _request(
        assets=[
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "venue_equity"},
                "calendar_identifier": "NYSE",
            },
            {
                "unique_identifier": "venue::MSFT",
                "asset_type": {"asset_type": "venue_equity"},
                "calendar_identifier": "NYSE",
            },
        ]
    )
    operations = _record_operations(monkeypatch)

    result = register_account(markets.context, request)

    # The two reads of a registration, the calendar, then one transaction for everything.
    assert operations == ["read", "read", "read", "transaction"]
    assert result.response["written"]["asset_calendars"] == {"created": 2, "changed": 0}
    assert links(markets) == {"venue::AAPL": "NYSE", "venue::MSFT": "NYSE"}
    audit = [write for write in result.writes if write.resource == "asset-calendar"]
    assert [(write.action, write.details["asset_identifiers"]) for write in audit] == [
        ("create", ["venue::AAPL", "venue::MSFT"])
    ]
    # The cash currency names no calendar and gets none.
    assert "USD" not in links(markets)


def test_account_registration_keeps_a_link_an_asset_already_has(markets, monkeypatch) -> None:
    def request(calendar: str, **values):
        return _request(
            assets=[
                {
                    "unique_identifier": "venue::AAPL",
                    "asset_type": {"asset_type": "venue_equity"},
                    "calendar_identifier": calendar,
                }
            ],
            positions=[{"asset_identifier": "venue::AAPL", "quantity": "3"}],
            cash_currency=None,
            **values,
        )

    register_account(markets.context, request("NYSE"))
    AssetCalendar.link_many(["venue::AAPL"], calendar_identifier="DESK")
    operations = _record_operations(monkeypatch)

    # A later sync names NYSE again: the link someone moved to DESK is kept.
    again = register_account(markets.context, request("NYSE"))

    assert links(markets) == {"venue::AAPL": "DESK"}
    assert again.response["written"]["asset_calendars"] == {"created": 0, "changed": 0}
    # An identical repeat still needs no transaction: reads only.
    assert "transaction" not in operations


def test_account_registration_refuses_an_unknown_calendar_before_any_write(markets) -> None:
    request = _request(
        assets=[
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "venue_equity"},
                "calendar_identifier": "MISSING",
            }
        ],
        positions=[{"asset_identifier": "venue::AAPL", "quantity": "3"}],
        cash_currency=None,
    )
    before = writes(markets)

    with pytest.raises(ValueError, match="Calendar 'MISSING' was not found. Create the calendar"):
        register_account(markets.context, request)

    assert writes(markets) == before
    assert _rows(markets.engine, "SELECT uid FROM ms_markets__account") == []


def test_a_calendar_in_use_cannot_be_deleted(markets) -> None:
    assets("A0", "A1")
    AssetCalendar.link_many(["A0", "A1"], calendar_identifier="NYSE")

    with pytest.raises(CalendarInUseConflictError, match="'NYSE' is the trading calendar of 2 asset"):
        delete_calendar_record(markets.context, uid=str(markets.nyse.uid))
    assert Calendar.get_by_unique_identifier("NYSE") is not None

    AssetCalendar.link_many(["A0", "A1"], calendar_identifier="DESK")
    assert delete_calendar_record(markets.context, uid=str(markets.nyse.uid)) is True
    assert Calendar.get_by_unique_identifier("NYSE") is None
