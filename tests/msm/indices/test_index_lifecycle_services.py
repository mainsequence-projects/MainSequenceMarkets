from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from msm.api.indices import Index
from msm.base import MarketsBase, MarketsMetaTableMixin, markets_table_args, new_markets_uid
from msm.data_nodes.indices.storage import configured_index_values_storage
from msm.models import IndexTable
from msm.services.indices import (
    IndexActor,
    IndexBulkDeleteExecuteRequest,
    IndexBulkDeletePreviewRequest,
    IndexDatasetAccess,
    IndexDatasetDescriptor,
    IndexDatasetSummary,
    IndexDeletionAccessDenied,
    IndexDeletionConfirmationRequired,
    IndexDeletionScopeChanged,
    IndexRelatedMetaTable,
    IndexRelationshipProvider,
    discover_canonical_datasets,
    preview_bulk_delete,
)
from msm.services.indices import catalog as catalog_service
from msm.services.indices import deletion as deletion_service


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


def test_preview_is_read_only_signed_actor_bound_and_warns_about_datanodes(
    monkeypatch,
) -> None:
    index_uid = uuid.uuid4()
    actor = IndexActor(user_uid=str(uuid.uuid4()))
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
    )
    monkeypatch.setenv(
        deletion_service.TOKEN_SECRET_ENV,
        "test-only-index-delete-secret-that-is-long-enough",
    )
    monkeypatch.setattr(deletion_service, "_get_index", lambda context, uid: index)
    monkeypatch.setattr(deletion_service, "list_methodologies", lambda context, index_uid: ())
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (),
    )
    monkeypatch.setattr(deletion_service, "discover_canonical_datasets", lambda actor: ())

    preview = preview_bulk_delete(
        SimpleNamespace(),
        actor=actor,
        request=IndexBulkDeletePreviewRequest(
            index_uids=(index_uid,),
            mode="values_only",
        ),
        now=dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC),
    )

    assert preview.executable is True
    assert preview.created_by_user_uid == actor.user_uid
    assert preview.confirmation_phrase == "DELETE ALL SELECTED INDEX VALUES FOR 1 INDEX"
    assert {
        "permanent_value_deletion",
        "all_timestamps_in_scope",
        "data_node_state_not_reset",
        "data_may_be_republished",
        "producer_quiescence_unknown",
        "cross_table_non_atomic",
    }.issubset(preview.required_acknowledgement_codes)
    assert preview.confirmation_token.count(".") == 1

    with pytest.raises(IndexDeletionAccessDenied):
        deletion_service._verify_token(
            preview.confirmation_token,
            actor=IndexActor(user_uid=str(uuid.uuid4())),
            now=dt.datetime(2026, 7, 19, 12, 1, tzinfo=dt.UTC),
        )


def test_scoped_storage_delete_always_supplies_index_dimension(monkeypatch) -> None:
    calls = []

    class FakeTimeIndexMetaTable:
        def delete_after_date(self, after_date, *, dimension_filters, timeout):
            calls.append((after_date, dimension_filters, timeout))
            return {"deleted_count": 7}

    monkeypatch.setattr(
        deletion_service.TimeIndexMetaTable,
        "filter_by_body",
        lambda **kwargs: [FakeTimeIndexMetaTable()],
    )

    result = deletion_service._delete_time_indexed_dataset(
        str(uuid.uuid4()),
        identifiers=["USD_SWAP_10Y", "EUR_SWAP_10Y"],
        timeout=30,
    )

    assert result == {"deleted_count": 7}
    assert calls == [
        (
            None,
            {"index_identifier": ["USD_SWAP_10Y", "EUR_SWAP_10Y"]},
            30,
        )
    ]


def test_identity_preview_blocks_when_canonical_value_count_is_unavailable(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    actor = IndexActor(user_uid=str(uuid.uuid4()))
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
    )
    dataset = IndexDatasetDescriptor(
        meta_table_uid=str(uuid.uuid4()),
        identifier="IndexValuesTS.1d",
        cadence="1d",
        physical_table_name="ms_markets__index_values__t_1d",
        time_index_name="time_index",
        index_names=("time_index", "index_identifier"),
        columns=("time_index", "index_identifier", "value", "unit"),
        foreign_keys=(),
        storage_kind="canonical_index_values",
        discovery_source="core_model",
        access=IndexDatasetAccess(can_view=True, can_edit=True),
        scoped_delete_supported=True,
    )
    monkeypatch.setenv(
        deletion_service.TOKEN_SECRET_ENV,
        "test-only-index-delete-secret-that-is-long-enough",
    )
    monkeypatch.setattr(deletion_service, "_get_index", lambda context, uid: index)
    monkeypatch.setattr(deletion_service, "list_methodologies", lambda context, index_uid: ())
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (),
    )
    monkeypatch.setattr(
        deletion_service,
        "discover_canonical_datasets",
        lambda actor: (dataset,),
    )
    monkeypatch.setattr(
        deletion_service,
        "dataset_summary",
        lambda context, index, dataset: IndexDatasetSummary(
            dataset=dataset,
            index_uid=index.uid,
            index_identifier=index.unique_identifier,
            count_accuracy="unavailable",
            error="catalog unavailable",
        ),
    )

    preview = preview_bulk_delete(
        SimpleNamespace(),
        actor=actor,
        request=IndexBulkDeletePreviewRequest(
            index_uids=(index_uid,),
            mode="identity_only",
        ),
    )

    assert preview.executable is False
    assert "counts_unavailable" in {item.code for item in preview.warnings}


def test_identity_and_values_preview_includes_resolved_leg_storage(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    resolved_meta_table_uid = str(uuid.uuid4())
    actor = IndexActor(user_uid=str(uuid.uuid4()))
    index = Index(
        uid=index_uid,
        unique_identifier="ROLLING_SWAP_INDEX",
        index_type="derived",
        display_name="Rolling Swap Index",
    )
    resolved_relationship = IndexRelatedMetaTable(
        key="resolved_index_legs",
        label="Resolved methodology legs",
        owning_package="msm",
        storage_kind="resolved_index_legs",
        meta_table_uid=resolved_meta_table_uid,
        identifier="IndexResolvedLegsStorage",
        relationship_type="direct",
        join_kind="unique_identifier",
        join_column="index_identifier",
        on_delete="RESTRICT",
        authoritative=True,
        discovery_source="core_model",
        exploration_capability="count",
        delete_capability="scoped",
        count=2,
        blocks_delete=True,
    )
    monkeypatch.setenv(
        deletion_service.TOKEN_SECRET_ENV,
        "test-only-index-delete-secret-that-is-long-enough",
    )
    monkeypatch.setattr(deletion_service, "_get_index", lambda context, uid: index)
    monkeypatch.setattr(deletion_service, "list_methodologies", lambda context, index_uid: ())
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (resolved_relationship,),
    )
    monkeypatch.setattr(deletion_service, "discover_canonical_datasets", lambda actor: ())

    preview = preview_bulk_delete(
        SimpleNamespace(),
        actor=actor,
        request=IndexBulkDeletePreviewRequest(
            index_uids=(index_uid,),
            mode="identity_and_values",
        ),
    )

    resolved_impact = next(
        item for item in preview.datasets if item.storage_kind == "resolved_index_legs"
    )
    assert resolved_impact.meta_table_uid == resolved_meta_table_uid
    assert resolved_impact.selected is True
    assert resolved_impact.affected_row_count == 2
    assert preview.indexes[0].can_delete_identity is True
    assert preview.executable is True
    assert "resolved_leg_provenance_deletion" in preview.required_acknowledgement_codes


def test_public_index_delete_requires_review_confirmation() -> None:
    with pytest.raises(IndexDeletionConfirmationRequired, match="preview"):
        Index.delete(uuid.uuid4())


def test_bulk_preview_request_normalizes_duplicate_index_uids() -> None:
    index_uid = uuid.uuid4()

    request = IndexBulkDeletePreviewRequest(
        index_uids=(index_uid, index_uid),
        mode="values_only",
    )

    assert request.index_uids == (index_uid,)


def test_execution_uses_reviewed_plan_id_and_completed_retry_is_idempotent(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    actor = IndexActor(user_uid=str(uuid.uuid4()))
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
    )
    monkeypatch.setenv(
        deletion_service.TOKEN_SECRET_ENV,
        "test-only-index-delete-secret-that-is-long-enough",
    )
    monkeypatch.setattr(deletion_service, "_get_index", lambda context, uid: index)
    monkeypatch.setattr(deletion_service, "list_methodologies", lambda context, index_uid: ())
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (),
    )
    monkeypatch.setattr(deletion_service, "discover_canonical_datasets", lambda actor: ())
    preview = preview_bulk_delete(
        SimpleNamespace(),
        actor=actor,
        request=IndexBulkDeletePreviewRequest(
            index_uids=(index_uid,),
            mode="identity_only",
        ),
        now=dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC),
    )
    journal = None
    delete_calls = []

    def fake_get_journal(context, actor_user_uid, idempotency_key):
        return journal

    def fake_create_journal(context, *, actor, idempotency_key, preview, plan_id):
        nonlocal journal
        state = {
            "journal_uid": str(uuid.uuid4()),
            "indexes": [item.model_dump(mode="json") for item in preview.indexes],
            "datasets": [],
            "warnings": [item.model_dump(mode="json") for item in preview.warnings],
            "required_acknowledgement_codes": list(preview.required_acknowledgement_codes),
            "completed_steps": [],
            "dataset_step_results": {},
            "index_step_results": {},
            "resolved_leg_deleted_count": 0,
        }
        journal = {
            "plan_id": plan_id,
            "scope_hash": preview.scope_hash,
            "status": "pending",
            "step_results_json": state,
        }
        return journal

    def fake_update_journal(context, state, *, status, completed_at):
        nonlocal journal
        journal = {
            **(journal or {}),
            "status": status,
            "step_results_json": dict(state),
        }

    monkeypatch.setattr(deletion_service, "_get_journal", fake_get_journal)
    monkeypatch.setattr(deletion_service, "_create_journal", fake_create_journal)
    monkeypatch.setattr(deletion_service, "_update_journal", fake_update_journal)
    monkeypatch.setattr(
        deletion_service,
        "delete_model",
        lambda context, model, uid: delete_calls.append(uid) or {},
    )
    execute_request = IndexBulkDeleteExecuteRequest(
        confirmation_token=preview.confirmation_token,
        confirmation_phrase=preview.confirmation_phrase,
        acknowledged_warning_codes=preview.required_acknowledgement_codes,
        idempotency_key="test-idempotency-key",
    )

    result = deletion_service.execute_bulk_delete(
        SimpleNamespace(timeout=None),
        actor=actor,
        request=execute_request,
        now=dt.datetime(2026, 7, 19, 12, 1, tzinfo=dt.UTC),
    )
    repeated = deletion_service.execute_bulk_delete(
        SimpleNamespace(timeout=None),
        actor=actor,
        request=execute_request,
        now=dt.datetime(2026, 7, 19, 12, 2, tzinfo=dt.UTC),
    )

    assert result.status == "completed"
    assert result.plan_id == preview.plan_id
    assert repeated == result
    assert delete_calls == [index_uid]


def test_execution_rejects_changed_review_scope(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    actor = IndexActor(user_uid=str(uuid.uuid4()))
    index = Index(
        uid=index_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
    )
    monkeypatch.setenv(
        deletion_service.TOKEN_SECRET_ENV,
        "test-only-index-delete-secret-that-is-long-enough",
    )
    monkeypatch.setattr(deletion_service, "_get_index", lambda context, uid: index)
    monkeypatch.setattr(deletion_service, "list_methodologies", lambda context, index_uid: ())
    monkeypatch.setattr(deletion_service, "discover_canonical_datasets", lambda actor: ())
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (),
    )
    preview = preview_bulk_delete(
        SimpleNamespace(),
        actor=actor,
        request=IndexBulkDeletePreviewRequest(
            index_uids=(index_uid,),
            mode="identity_only",
        ),
        now=dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC),
    )
    blocker = IndexRelatedMetaTable(
        key="new_dependency",
        label="New dependency",
        owning_package="extension",
        storage_kind="related_reference_table",
        identifier="NewDependency",
        relationship_type="direct",
        join_kind="uid",
        join_column="index_uid",
        on_delete="RESTRICT",
        authoritative=True,
        discovery_source="declared_provider",
        exploration_capability="count",
        delete_capability="none",
        count=1,
        blocks_delete=True,
    )
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (blocker,),
    )
    monkeypatch.setattr(
        deletion_service,
        "_get_journal",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(IndexDeletionScopeChanged) as exc_info:
        deletion_service.execute_bulk_delete(
            SimpleNamespace(timeout=None),
            actor=actor,
            request=IndexBulkDeleteExecuteRequest(
                confirmation_token=preview.confirmation_token,
                confirmation_phrase=preview.confirmation_phrase,
                acknowledged_warning_codes=preview.required_acknowledgement_codes,
                idempotency_key="changed-scope",
            ),
            now=dt.datetime(2026, 7, 19, 12, 1, tzinfo=dt.UTC),
        )

    assert exc_info.value.fresh_preview is not None
    assert exc_info.value.fresh_preview.executable is False


def test_single_index_execution_rejects_another_plan_before_journaling(monkeypatch) -> None:
    reviewed_uid = uuid.uuid4()
    route_uid = uuid.uuid4()
    actor = IndexActor(user_uid=str(uuid.uuid4()))
    index = Index(
        uid=reviewed_uid,
        unique_identifier="USD_SWAP_10Y",
        index_type="interest_rate",
        display_name="USD 10Y Swap Rate",
    )
    monkeypatch.setenv(
        deletion_service.TOKEN_SECRET_ENV,
        "test-only-index-delete-secret-that-is-long-enough",
    )
    monkeypatch.setattr(deletion_service, "_get_index", lambda context, uid: index)
    monkeypatch.setattr(deletion_service, "list_methodologies", lambda context, index_uid: ())
    monkeypatch.setattr(
        deletion_service,
        "list_related_meta_tables",
        lambda context, index: (),
    )
    monkeypatch.setattr(deletion_service, "discover_canonical_datasets", lambda actor: ())
    preview = preview_bulk_delete(
        SimpleNamespace(),
        actor=actor,
        request=IndexBulkDeletePreviewRequest(
            index_uids=(reviewed_uid,),
            mode="identity_only",
        ),
        now=dt.datetime(2026, 7, 19, 12, tzinfo=dt.UTC),
    )
    monkeypatch.setattr(
        deletion_service,
        "_get_journal",
        lambda *args, **kwargs: pytest.fail("journal lookup must not occur"),
    )

    with pytest.raises(IndexDeletionScopeChanged, match="exactly this single Index"):
        deletion_service.execute_bulk_delete(
            SimpleNamespace(timeout=None),
            actor=actor,
            request=IndexBulkDeleteExecuteRequest(
                confirmation_token=preview.confirmation_token,
                confirmation_phrase=preview.confirmation_phrase,
                acknowledged_warning_codes=preview.required_acknowledgement_codes,
                idempotency_key="wrong-single-index-route",
            ),
            expected_single_index_uid=route_uid,
            now=dt.datetime(2026, 7, 19, 12, 1, tzinfo=dt.UTC),
        )
