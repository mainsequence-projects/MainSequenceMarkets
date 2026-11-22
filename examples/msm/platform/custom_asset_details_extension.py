from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import ClassVar

if __package__ in {None, ""}:
    _PROJECT_ROOT = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(_PROJECT_ROOT / "src"), str(_PROJECT_ROOT)]

from examples.msm.platform.bootstrap import use_local_runtime  # noqa: E402

if __name__ == "__main__":
    use_local_runtime()  # before any client model is imported

import msm  # noqa: E402
from metatables import sqlalchemy_naming_convention  # noqa: E402
from pydantic import AliasChoices, Field  # noqa: E402
from sqlalchemy import ForeignKey, MetaData  # noqa: E402
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column  # noqa: E402
from sqlalchemy.types import String, Uuid  # noqa: E402

from msm.api.base import MarketsMetaTableRow  # noqa: E402
from msm.base import MarketsMetaTableMixin  # noqa: E402
from msm.models import AssetTable  # noqa: E402


class Base(DeclarativeBase):
    """The project's own base: its migration provider targets this metadata."""

    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class MyProjectMarketsMetaTableMixin(MarketsMetaTableMixin):
    """Project-local default namespace and physical table-name prefix."""

    __abstract__ = True
    __metatable_namespace__ = "com.my_project.markets"
    __markets_storage_app__ = "my_project_markets"


class MyAssetDetailsTable(MyProjectMarketsMetaTableMixin, Base):
    """Project-local one-to-one asset detail table."""

    __markets_base_identifier__ = "MyAssetDetails"
    __metatable_extra_hash_components__ = {"storage_name": "my_asset_details"}
    __metatable_description__ = (
        "Project-local asset details keyed one-to-one by AssetTable.uid for custom "
        "classification and analytics examples."
    )

    asset_uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(AssetTable.__table__.c.uid, ondelete="CASCADE"),
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
    """Attach the migrated extension model through the shared runtime path."""

    use_local_runtime()
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
