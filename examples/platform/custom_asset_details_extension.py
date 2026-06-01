from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import ClassVar

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[2]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.platform.bootstrap import (
    EXAMPLE_METATABLE_NAMESPACE,
    EXAMPLE_NAMESPACE_ENV,
)

os.environ.setdefault(EXAMPLE_NAMESPACE_ENV, EXAMPLE_METATABLE_NAMESPACE)

import msm  # noqa: E402
from mainsequence.meta_tables import MetaTableForeignKey  # noqa: E402
from pydantic import AliasChoices, Field  # noqa: E402
from sqlalchemy.orm import Mapped, mapped_column  # noqa: E402
from sqlalchemy.types import String, Uuid  # noqa: E402

from msm.api.base import MarketsMetaTableRow  # noqa: E402
from msm.base import MarketsBase, MarketsMetaTableMixin  # noqa: E402
from msm.models import AssetTable  # noqa: E402


class MyAssetDetailsTable(MarketsMetaTableMixin, MarketsBase):
    """Project-local one-to-one asset detail table."""

    __metatable_identifier__ = "MyAssetDetails"
    __metatable_extra_hash_components__ = {"storage_name": "my_asset_details"}
    __metatable_description__ = (
        "Project-local asset details keyed one-to-one by AssetTable.uid for custom "
        "classification and analytics examples."
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        MetaTableForeignKey(AssetTable, column="uid", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
        info={"description": "Canonical AssetTable uid for this custom detail row."},
    )
    internal_asset_class: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={"description": "Internal asset class assigned by the project."},
    )


class MyAssetDetails(MarketsMetaTableRow):
    """Typed row-operation wrapper for MyAssetDetailsTable."""

    __table__: ClassVar[type[MyAssetDetailsTable]] = MyAssetDetailsTable
    __required_tables__: ClassVar[list[type[MyAssetDetailsTable]]] = [
        MyAssetDetailsTable,
    ]
    __upsert_keys__: ClassVar[tuple[str, ...]] = ("asset_uid",)

    uid: uuid.UUID = Field(validation_alias=AliasChoices("uid", "asset_uid"))
    asset_uid: uuid.UUID
    internal_asset_class: str


def bootstrap_custom_asset_details():
    """Register or attach the extension model through the shared catalog."""

    return msm.start_engine(models=[MyAssetDetailsTable])


def main() -> None:
    runtime = bootstrap_custom_asset_details()
    print(
        "registered {model} as {uid}".format(
            model=MyAssetDetailsTable.__name__,
            uid=runtime.table(MyAssetDetailsTable).meta_table_uid,
        )
    )


if __name__ == "__main__":
    main()
