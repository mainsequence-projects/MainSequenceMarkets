"""Assets, categories, OpenFIGI details and indexes written directly, for the list reads.

The tests of `msm.services.asset_master_lists` need more rows than one MetaTables answer
or the old 500-row scans held (#116). Each helper writes its rows in one insert on the
SQLite file of `sqlite_markets`, outside MetaTables, and returns what it wrote.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from msm.models import (
    AssetCategoryMembershipTable,
    AssetCategoryTable,
    AssetTable,
    IndexTable,
    OpenFigiAssetDetailsTable,
)


def _insert(engine, model, rows: list[dict]) -> None:
    if rows:
        with engine.begin() as connection:
            connection.execute(model.__table__.insert(), rows)


def seed_assets(
    engine,
    count: int,
    *,
    prefix: str = "asset",
    asset_type: str | None = "equity",
    openfigi: bool = False,
) -> list[dict]:
    """``count`` assets ``{prefix}-0000``, ..., with OpenFIGI details when ``openfigi``.

    Each detail row names its asset ``Name of {identifier}`` with ticker ``T{index}``.
    """

    assets = [
        {
            "uid": uuid.uuid4(),
            "unique_identifier": f"{prefix}-{index:04d}",
            "asset_type": asset_type,
        }
        for index in range(count)
    ]
    _insert(engine, AssetTable, assets)
    if openfigi:
        _insert(
            engine,
            OpenFigiAssetDetailsTable,
            [
                {
                    "asset_uid": asset["uid"],
                    "name": f"Name of {asset['unique_identifier']}",
                    "ticker": f"T{index:04d}",
                    "exchange_code": "XNYS",
                }
                for index, asset in enumerate(assets)
            ],
        )
    return assets


def seed_categories(
    engine,
    count: int,
    *,
    prefix: str = "category",
    display_name: str = "Category",
) -> list[dict]:
    """``count`` categories ``{prefix}-0000``, ..., displayed ``{display_name} 0000``, ..."""

    categories = [
        {
            "uid": uuid.uuid4(),
            "unique_identifier": f"{prefix}-{index:04d}",
            "display_name": f"{display_name} {index:04d}",
            "description": f"Description of {prefix}-{index:04d}",
        }
        for index in range(count)
    ]
    _insert(engine, AssetCategoryTable, categories)
    return categories


def seed_memberships(engine, category_uid: uuid.UUID, asset_uids: Sequence[uuid.UUID]) -> None:
    """Make each of ``asset_uids`` a member of the category."""

    _insert(
        engine,
        AssetCategoryMembershipTable,
        [
            {"uid": uuid.uuid4(), "category_uid": category_uid, "asset_uid": asset_uid}
            for asset_uid in asset_uids
        ],
    )


def seed_indexes(engine, count: int, *, prefix: str = "index") -> list[dict]:
    """``count`` indexes ``{prefix}-0000``, ..., displayed ``Index 0000``, ..."""

    indexes = [
        {
            "uid": uuid.uuid4(),
            "unique_identifier": f"{prefix}-{index:04d}",
            "index_type": "equity",
            "display_name": f"Index {index:04d}",
            "calculation_method": "custom",
            "value_format": "decimal",
            "description": f"Description of {prefix}-{index:04d}",
        }
        for index in range(count)
    ]
    _insert(engine, IndexTable, indexes)
    return indexes


def membership_count(engine, category_uid: uuid.UUID) -> int:
    """How many members the category has in the file."""

    from sqlalchemy import func, select

    with engine.connect() as connection:
        return connection.execute(
            select(func.count())
            .select_from(AssetCategoryMembershipTable.__table__)
            .where(AssetCategoryMembershipTable.__table__.c.category_uid == category_uid)
        ).scalar_one()


def category_count(engine) -> int:
    """How many categories the file has."""

    from sqlalchemy import func, select

    with engine.connect() as connection:
        return connection.execute(
            select(func.count()).select_from(AssetCategoryTable.__table__)
        ).scalar_one()
