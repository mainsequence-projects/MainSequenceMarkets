"""The asset, category and index lists answer every row on SQLite, past 500 (#116).

They read at most 500 rows and sliced them in Python, so a category's record answered 500
of its members, writing it back deleted the rest, and pages past 500 were empty. Each
read now pages or counts in the database, or reads every row (`complete_reads`).
"""

from __future__ import annotations

import uuid

import pytest

from msm.repositories import complete_reads
from msm.services import (
    bulk_delete_asset_category_records,
    create_asset_category_record,
    get_asset_category_frontend_detail,
    get_asset_category_record,
    list_asset_catalog_rows,
    list_asset_category_rows,
    list_asset_category_rows_page,
    list_asset_category_rows_response,
    list_asset_rows,
    list_asset_rows_response,
    list_index_catalog_rows,
    update_asset_category_record,
)
from tests.support.asset_master_lists import (
    category_count,
    membership_count,
    seed_assets,
    seed_categories,
    seed_indexes,
    seed_memberships,
)

PAGE = 200


def _every_page(read_page) -> list[dict]:
    """The rows of ``read_page(offset)`` for each page of `PAGE` until an empty one."""

    rows: list[dict] = []
    for offset in range(0, 100_000, PAGE):
        page = read_page(offset)
        if not page:
            return rows
        assert len(page) <= PAGE
        rows.extend(page)
    raise AssertionError("the pages never ended")


def _large_category(engine, members: int = 1_101) -> tuple[dict, list[uuid.UUID]]:
    assets = seed_assets(engine, members, prefix="member")
    (category,) = seed_categories(engine, 1, prefix="large")
    seed_memberships(engine, category["uid"], [asset["uid"] for asset in assets])
    return category, [asset["uid"] for asset in assets]


@pytest.fixture
def small_read_pages(monkeypatch):
    """Complete reads take several answers, as a category past 10,000 members would."""

    monkeypatch.setattr(complete_reads, "READ_PAGE_ROWS", 400)


def test_a_category_record_answers_every_member(sqlite_markets, small_read_pages) -> None:
    category, members = _large_category(sqlite_markets.engine)

    record = get_asset_category_record(sqlite_markets.context, uid=str(category["uid"]))

    # In the order of their asset uids, as the members came before.
    assert [uuid.UUID(uid) for uid in record["assets"]] == sorted(members)


def test_creating_a_category_answers_every_member(sqlite_markets) -> None:
    assets = seed_assets(sqlite_markets.engine, 1_101)

    record = create_asset_category_record(
        sqlite_markets.context,
        display_name="Large",
        assets=[str(asset["uid"]) for asset in assets],
    )

    assert sorted(uuid.UUID(uid) for uid in record["assets"]) == sorted(
        asset["uid"] for asset in assets
    )
    assert membership_count(sqlite_markets.engine, uuid.UUID(record["uid"])) == 1_101


def test_writing_a_category_record_back_keeps_every_member(sqlite_markets) -> None:
    category, members = _large_category(sqlite_markets.engine)
    uid = str(category["uid"])

    record = get_asset_category_record(sqlite_markets.context, uid=uid)
    updated = update_asset_category_record(sqlite_markets.context, uid=uid, assets=record["assets"])

    assert len(updated["assets"]) == 1_101
    assert membership_count(sqlite_markets.engine, category["uid"]) == 1_101


def test_the_category_detail_counts_every_member(sqlite_markets) -> None:
    category, _members = _large_category(sqlite_markets.engine)

    detail = get_asset_category_frontend_detail(sqlite_markets.context, uid=str(category["uid"]))

    values = {field["name"]: field["value"] for field in detail["details"]}
    assert values["number_of_assets"] == 1_101


def test_select_all_deletes_every_matching_category(sqlite_markets, small_read_pages) -> None:
    seed_categories(sqlite_markets.engine, 601, prefix="doomed", display_name="Doomed")
    seed_categories(sqlite_markets.engine, 2, prefix="kept", display_name="Kept")

    result = bulk_delete_asset_category_records(
        sqlite_markets.context, select_all=True, search="DOOMED"
    )

    # One statement deletes every matching category (issue 128).
    assert result["detail"] == "Deleted 601 asset categories."
    assert result["deleted_count"] == len(result["deleted"]) == 601
    assert result["failed"] == []
    assert category_count(sqlite_markets.engine) == 2


@pytest.mark.parametrize("asset_type", [None, "equity"])
def test_asset_rows_reach_every_asset_past_500(sqlite_markets, asset_type) -> None:
    equities = seed_assets(sqlite_markets.engine, 1_101, prefix="eq", asset_type="equity")
    bonds = seed_assets(sqlite_markets.engine, 40, prefix="bond", asset_type="bond")
    expected = equities if asset_type else bonds + equities

    rows = _every_page(
        lambda offset: list_asset_rows(
            sqlite_markets.context, asset_type=asset_type, limit=PAGE, offset=offset
        )
    )
    response = list_asset_rows_response(
        sqlite_markets.context, asset_type=asset_type, limit=PAGE, offset=1_000
    )

    assert [row["unique_identifier"] for row in rows] == [
        asset["unique_identifier"] for asset in expected
    ]
    assert response["count"] == len(expected)
    assert [row["unique_identifier"] for row in response["results"]] == [
        asset["unique_identifier"] for asset in expected[1_000:1_200]
    ]


def test_asset_rows_search_a_category_past_500(sqlite_markets) -> None:
    category, _members = _large_category(sqlite_markets.engine)
    seed_assets(sqlite_markets.engine, 300, prefix="other")

    # "R-0" is in member-0000 to member-0999 and in every other-, case aside; never in a uid.
    rows = _every_page(
        lambda offset: list_asset_rows(
            sqlite_markets.context,
            search="R-0",
            category_uid=str(category["uid"]),
            limit=PAGE,
            offset=offset,
        )
    )

    assert [row["unique_identifier"] for row in rows] == [
        f"member-{index:04d}" for index in range(1_000)
    ]


def test_asset_rows_search_matches_an_openfigi_ticker(sqlite_markets) -> None:
    seed_assets(sqlite_markets.engine, 3, prefix="plain")
    seed_assets(sqlite_markets.engine, 2, prefix="listed", openfigi=True)

    rows = list_asset_rows(sqlite_markets.context, search="t0001")

    assert [row["unique_identifier"] for row in rows] == ["listed-0001"]


def test_asset_rows_by_unique_identifier_keep_the_requested_order(sqlite_markets) -> None:
    seed_assets(sqlite_markets.engine, 3, prefix="eq", asset_type="equity")
    seed_assets(sqlite_markets.engine, 2, prefix="bond", asset_type="bond")
    requested = ["eq-0002", "bond-0001", "missing", "eq-0000"]

    every_type = list_asset_rows(sqlite_markets.context, unique_identifiers=requested)
    equities = list_asset_rows(
        sqlite_markets.context, unique_identifiers=requested, asset_type="equity"
    )

    assert [row["unique_identifier"] for row in every_type] == ["eq-0002", "bond-0001", "eq-0000"]
    assert [row["unique_identifier"] for row in equities] == ["eq-0002", "eq-0000"]


def test_asset_catalog_rows_reach_every_asset_with_its_openfigi_details(sqlite_markets) -> None:
    assets = seed_assets(sqlite_markets.engine, 1_101, openfigi=True)

    rows = _every_page(
        lambda offset: list_asset_catalog_rows(sqlite_markets.context, limit=PAGE, offset=offset)
    )

    assert [(row["unique_identifier"], row["name"], row["ticker"]) for row in rows] == [
        (asset["unique_identifier"], f"Name of {asset['unique_identifier']}", f"T{index:04d}")
        for index, asset in enumerate(assets)
    ]
    assert {row["security_type"] for row in rows} == {"equity"}


def test_asset_catalog_rows_search_a_category(sqlite_markets) -> None:
    members = seed_assets(sqlite_markets.engine, 1_101, prefix="member", openfigi=True)
    (category,) = seed_categories(sqlite_markets.engine, 1)
    seed_memberships(sqlite_markets.engine, category["uid"], [asset["uid"] for asset in members])
    seed_assets(sqlite_markets.engine, 1_101, prefix="other", openfigi=True)
    seed_assets(sqlite_markets.engine, 2, prefix="bond", asset_type="bond")

    by_name = _every_page(
        lambda offset: list_asset_catalog_rows(
            sqlite_markets.context,
            search="NAME OF MEMBER-1",
            category_uid=str(category["uid"]),
            limit=PAGE,
            offset=offset,
        )
    )
    # With no OpenFIGI security type, the asset type is searched in its place.
    by_type = list_asset_catalog_rows(sqlite_markets.context, search="BOND")

    assert [row["unique_identifier"] for row in by_name] == [
        f"member-{index:04d}" for index in range(1_000, 1_101)
    ]
    assert [row["unique_identifier"] for row in by_type] == ["bond-0000", "bond-0001"]


def test_index_catalog_rows_reach_every_index_and_search(sqlite_markets) -> None:
    indexes = seed_indexes(sqlite_markets.engine, 601)

    rows = _every_page(
        lambda offset: list_index_catalog_rows(sqlite_markets.context, limit=PAGE, offset=offset)
    )
    searched = _every_page(
        lambda offset: list_index_catalog_rows(
            sqlite_markets.context, search="INDEX-05", limit=PAGE, offset=offset
        )
    )

    assert [row["unique_identifier"] for row in rows] == [
        index["unique_identifier"] for index in indexes
    ]
    assert [row["unique_identifier"] for row in searched] == [
        f"index-{index:04d}" for index in range(500, 600)
    ]


def test_category_rows_response_counts_members_and_pages_past_500(sqlite_markets) -> None:
    categories = seed_categories(sqlite_markets.engine, 601)
    assets = seed_assets(sqlite_markets.engine, 1_101)
    seed_memberships(sqlite_markets.engine, categories[0]["uid"], [a["uid"] for a in assets])
    seed_memberships(sqlite_markets.engine, categories[1]["uid"], [a["uid"] for a in assets[:3]])

    pages = [
        list_asset_category_rows_response(sqlite_markets.context, limit=PAGE, offset=offset)
        for offset in range(0, 800, PAGE)
    ]
    searched = list_asset_category_rows_response(sqlite_markets.context, search="1101")

    assert [page["pagination"]["total_items"] for page in pages] == [601] * 4
    assert [len(page["rows"]) for page in pages] == [200, 200, 200, 1]
    assert [
        (row["unique_identifier"], row["number_of_assets"])
        for page in pages
        for row in page["rows"]
    ] == [
        (category["unique_identifier"], {0: 1_101, 1: 3}.get(index, 0))
        for index, category in enumerate(categories)
    ]
    # Its member count matches as text; any other match is in a uid.
    matched = [row["unique_identifier"] for row in searched["rows"]]
    assert matched[0] == "category-0000"
    assert all("1101" in uuid.UUID(row["uid"]).hex for row in searched["rows"][1:])
    assert searched["pagination"]["total_items"] == len(matched)


def test_category_rows_reach_every_category_and_search(sqlite_markets) -> None:
    categories = seed_categories(sqlite_markets.engine, 601)

    rows = _every_page(
        lambda offset: list_asset_category_rows(sqlite_markets.context, limit=PAGE, offset=offset)
    )
    searched = _every_page(
        lambda offset: list_asset_category_rows(
            sqlite_markets.context, search="CATEGORY-05", limit=PAGE, offset=offset
        )
    )
    page = list_asset_category_rows_page(
        sqlite_markets.context, search="CATEGORY-05", limit=PAGE, offset=0
    )

    assert [row["unique_identifier"] for row in rows] == [
        category["unique_identifier"] for category in categories
    ]
    assert [row["unique_identifier"] for row in searched] == [
        f"category-{index:04d}" for index in range(500, 600)
    ]
    assert page["count"] == 100
    assert page["results"] == searched
