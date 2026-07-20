from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.data_nodes.indices.storage import configured_index_values_storage
from msm.models import IndexTable
from msm.services.indices import IndexRelationshipProvider, discover_canonical_datasets
from msm.services.indices import catalog as catalog_service


def test_methodology_leg_mapper_preserves_reproducible_methodology_fields() -> None:
    leg_uid = uuid.uuid4()
    definition_uid = uuid.uuid4()
    row = {
        "uid": leg_uid,
        "definition_uid": definition_uid,
        "leg_key": "front_contract",
        "leg_order": 0,
        "leg_role": "hedge",
        "component_kind": "selector",
        "asset_uid": None,
        "component_index_uid": None,
        "selector_code": "futures_rank",
        "selector_parameters_json": {"rank": 1, "roll_days": 5},
        "observable_code": "settlement_price",
        "input_unit": "currency",
        "transform_code": "simple_return",
        "transform_parameters_json": {"periods": 1},
        "coefficient_method": "rolling_dv01_neutral",
        "coefficient": None,
        "coefficient_parameters_json": {"window": 20, "lag": 1},
        "metadata_json": {"label": "Front futures hedge"},
    }

    leg = catalog_service._methodology_leg(row)

    assert leg.model_dump() == row


def test_canonical_dataset_discovery_requires_registered_cadence_and_real_fk(monkeypatch) -> None:
    storage_model = configured_index_values_storage(cadence="1d")
    meta_table_uid = uuid.uuid4()
    fake_meta_table = SimpleNamespace(
        uid=meta_table_uid,
        identifier=storage_model.__metatable_identifier__,
        namespace="mainsequence.markets",
        cadence="1d",
        physical_table_name=storage_model.__table__.name,
        table_index_names=["time_index", "index_identifier"],
        columns=[
            SimpleNamespace(name=name)
            for name in (
                "time_index",
                "index_identifier",
                "value",
                "unit",
                "definition_uid",
                "observation_status",
                "source_as_of",
                "metadata_json",
            )
        ],
        description="Daily canonical Index observations.",
        created_by_user_uid=str(uuid.uuid4()),
        registration=None,
    )
    monkeypatch.setattr(
        catalog_service.TimeIndexMetaTable,
        "filter_by_body",
        lambda **kwargs: [fake_meta_table],
    )

    datasets = discover_canonical_datasets()

    assert len(datasets) == 1
    assert datasets[0].meta_table_uid == str(meta_table_uid)
    assert datasets[0].cadence == "1d"
    assert datasets[0].physical_table_name == storage_model.__table__.name
    assert datasets[0].foreign_keys[0].source_column == "index_identifier"
    assert datasets[0].foreign_keys[0].target_column == "unique_identifier"


def test_extension_provider_rejects_column_name_without_foreign_key() -> None:
    class LooksLikeIndexValues(MarketsMetaTableMixin, MarketsBase):
        __metatable_identifier__ = "TestLooksLikeIndexValues"
        __metatable_description__ = "Test table with a misleading column name."
        __table_args__ = markets_table_args(__metatable_identifier__)

        uid: Mapped[uuid.UUID] = mapped_column(
            Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
        )
        index_identifier: Mapped[str] = mapped_column(String(255), nullable=False)

    with pytest.raises(ValueError, match="actual foreign key"):
        IndexRelationshipProvider(
            key="misleading",
            label="Misleading storage",
            owning_package="extension",
            storage_kind="declared_extension_values",
            storage_model=LooksLikeIndexValues,
            join_kind="unique_identifier",
            join_column="index_identifier",
        )


def test_extension_provider_requires_no_core_datanode_inheritance() -> None:
    class ExtensionOwnedIndexStorage(MarketsMetaTableMixin, MarketsBase):
        __metatable_identifier__ = "TestExtensionOwnedIndexStorage"
        __metatable_description__ = "Extension-owned Index observations for registry testing."
        __table_args__ = markets_table_args(__metatable_identifier__)

        uid: Mapped[uuid.UUID] = mapped_column(
            Uuid(as_uuid=True), primary_key=True, default=new_markets_uid
        )
        extension_index_key: Mapped[str] = mapped_column(
            String(255),
            ForeignKey(f"{IndexTable.__table__.fullname}.unique_identifier", ondelete="RESTRICT"),
            nullable=False,
        )

    provider = IndexRelationshipProvider(
        key="extension_owned",
        label="Extension-owned Index observations",
        owning_package="extension",
        storage_kind="declared_extension_values",
        storage_model=ExtensionOwnedIndexStorage,
        join_kind="unique_identifier",
        join_column="extension_index_key",
    )

    assert provider.storage_model is ExtensionOwnedIndexStorage
    assert not issubclass(ExtensionOwnedIndexStorage, configured_index_values_storage(cadence="1d"))

    with pytest.raises(ValueError, match="does not match the actual foreign key action"):
        IndexRelationshipProvider(
            key="wrong_delete_action",
            label="Wrong delete action",
            owning_package="extension",
            storage_kind="declared_extension_values",
            storage_model=ExtensionOwnedIndexStorage,
            join_kind="unique_identifier",
            join_column="extension_index_key",
            on_delete="CASCADE",
        )
