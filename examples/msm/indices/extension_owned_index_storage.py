"""Define extension-owned Index observations without using the core Index DataNode base."""

from __future__ import annotations

import datetime
from typing import ClassVar

import pandas as pd
from sqlalchemy import DateTime, Float, ForeignKey, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

from mainsequence.meta_tables import schema_table_name, sqlalchemy_naming_convention

from msm.base import MarketsTimeIndexMetaTableMixin
from msm.data_nodes.indices import IndexValuesDataNode, configured_index_values_storage
from msm.data_nodes.utils.stamped import StampedDataNode
from msm.models.indices import IndexTable


class ExtensionBase(DeclarativeBase):
    """Isolated SQLAlchemy registry owned by the example extension."""

    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


# Copy only the referenced core table into the extension registry so SQLAlchemy
# can resolve the foreign key while the extension continues to own its schema.
IndexTable.__table__.to_metadata(ExtensionBase.metadata)


class ExtensionIndexObservationsStorage(MarketsTimeIndexMetaTableMixin, ExtensionBase):
    """Example rich observation contract owned outside the core library."""

    __markets_storage_app__ = "extension_example"
    __tablename__ = schema_table_name(
        "extension_example",
        "index_observations",
        suffix="1m",
    )
    __metatable_namespace__ = "extension-example"
    __metatable_identifier__ = "IndexObservationsTS.1m"
    __metatable_description__ = (
        "Extension-owned Index observations with bid, ask, mid, source, and quality fields."
    )
    __time_index_name__: ClassVar[str] = "time_index"
    __cadence__: ClassVar[str] = "1m"
    __index_names__: ClassVar[list[str]] = ["time_index", "index_identifier"]
    __metatable_extra_hash_components__ = {
        "storage_name": "extension_index_observations",
        "cadence": "1m",
    }

    time_index: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    index_identifier: Mapped[str] = mapped_column(
        String(255),
        ForeignKey(f"{IndexTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
        nullable=False,
    )
    bid: Mapped[float] = mapped_column(Float, nullable=False)
    ask: Mapped[float] = mapped_column(Float, nullable=False)
    mid: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    quality_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class ExtensionIndexObservationsDataNode(StampedDataNode):
    """Example-owned producer; deliberately not an IndexTimestampedDataNode subclass."""

    frame_label: ClassVar[str] = "Extension Index Observations"

    @classmethod
    def _required_storage_table(cls) -> type[ExtensionIndexObservationsStorage]:
        return ExtensionIndexObservationsStorage


CANONICAL_ONE_MINUTE_VALUES_STORAGE = configured_index_values_storage(cadence="1m")


def run() -> dict[str, object]:
    """Normalize extension-owned rows and optionally map `mid` to canonical values."""

    source = pd.DataFrame(
        [
            {
                "time_index": "2026-07-17T14:00:00Z",
                "index_identifier": "USD_SWAP_10Y",
                "bid": 0.04190,
                "ask": 0.04194,
                "mid": 0.04192,
                "unit": "decimal",
                "source": "example-feed",
                "quality_status": "preliminary",
                "metadata_json": {"frequency": "1 minute"},
            }
        ]
    )
    extension_values = ExtensionIndexObservationsDataNode.validate_frame(source)

    canonical_source = extension_values.reset_index().rename(
        columns={"mid": "value", "quality_status": "observation_status"}
    )
    canonical_values = IndexValuesDataNode.validate_frame(
        canonical_source[
            [
                "time_index",
                "index_identifier",
                "value",
                "observation_status",
                "metadata_json",
            ]
        ],
        storage_table=CANONICAL_ONE_MINUTE_VALUES_STORAGE,
    )
    return {
        "index_identity": {
            "unique_identifier": "USD_SWAP_10Y",
            "index_type": "interest_rate",
            "display_name": "USD 10-Year Swap Yield",
        },
        "extension_values": extension_values,
        "canonical_values": canonical_values,
    }


if __name__ == "__main__":
    output = run()
    print(output["extension_values"])
    print(output["canonical_values"])
