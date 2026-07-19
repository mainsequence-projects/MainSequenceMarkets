from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import uuid
from typing import Any

from mainsequence.client.metatables import TimeIndexMetaTable
from mainsequence.logconf import logger as _mainsequence_logger

from msm.api.base import operation_result_rows
from msm.api.indices import Index
from msm.models import IndexDeletionExecutionTable, IndexTable
from msm.repositories.base import MarketsOperationContext
from msm.repositories.crud import create_model, delete_model, search_model, update_model

from .catalog import (
    dataset_summary,
    discover_canonical_datasets,
    list_methodologies,
    list_related_meta_tables,
)
from .contracts import (
    IndexActor,
    IndexBulkDeleteExecuteRequest,
    IndexBulkDeletePreview,
    IndexBulkDeletePreviewRequest,
    IndexBulkDeleteResult,
    IndexDatasetAccess,
    IndexDatasetDeleteImpact,
    IndexDatasetDeleteResult,
    IndexDeleteItemImpact,
    IndexDeleteItemResult,
    IndexDeleteWarning,
    IndexRelatedMetaTable,
)
from .relationships import list_index_relationship_providers

TOKEN_VERSION = 1
TOKEN_TTL = dt.timedelta(minutes=5)
TOKEN_SECRET_ENV = "MSM_INDEX_DELETE_CONFIRMATION_SECRET"
logger = _mainsequence_logger.bind(sub_application="markets", component="index_deletion")


class IndexDeletionError(RuntimeError):
    pass


class IndexDeletionConfirmationRequired(IndexDeletionError):
    pass


class IndexDeletionTokenExpired(IndexDeletionError):
    pass


class IndexDeletionScopeChanged(IndexDeletionError):
    def __init__(self, message: str, *, fresh_preview: IndexBulkDeletePreview | None = None):
        super().__init__(message)
        self.fresh_preview = fresh_preview


class IndexDeletionAccessDenied(IndexDeletionError):
    pass


def preview_bulk_delete(
    context: MarketsOperationContext,
    *,
    actor: IndexActor,
    request: IndexBulkDeletePreviewRequest,
    now: dt.datetime | None = None,
) -> IndexBulkDeletePreview:
    """Build a non-mutating, actor-bound impact report and signed scope token."""

    created_at = _utc_now(now)
    indexes: list[IndexDeleteItemImpact] = []
    visible_indexes: list[Index] = []
    relationships: list[IndexRelatedMetaTable] = []
    for index_uid in sorted(request.index_uids, key=str):
        index = _get_index(context, index_uid)
        if index is None:
            indexes.append(
                IndexDeleteItemImpact(
                    uid=index_uid,
                    exists=False,
                    can_delete_identity=False,
                )
            )
            continue
        visible_indexes.append(index)
        methodologies = list_methodologies(context, index_uid=index.uid)
        index_relationships = list_related_meta_tables(context, index=index)
        relationships.extend(index_relationships)
        dependency_count = sum(
            int(item.count or 0)
            for item in index_relationships
            if item.key == "component_index_dependencies"
        )
        indexes.append(
            IndexDeleteItemImpact(
                uid=index.uid,
                exists=True,
                unique_identifier=index.unique_identifier,
                display_name=index.display_name,
                index_type=index.index_type,
                definition_count=len(methodologies),
                leg_count=sum(item.leg_count for item in methodologies),
                component_dependency_count=dependency_count,
                can_delete_identity=dependency_count == 0
                and not any(item.blocks_delete for item in index_relationships),
            )
        )

    canonical = discover_canonical_datasets(actor=actor)
    requested_canonical = (
        {item.meta_table_uid for item in canonical}
        if request.canonical_dataset_uids is None
        else set(request.canonical_dataset_uids)
    )
    known_canonical = {item.meta_table_uid for item in canonical}
    unknown_canonical = requested_canonical - known_canonical
    impacts: list[IndexDatasetDeleteImpact] = []
    for dataset in canonical:
        selected = request.mode != "identity_only" and dataset.meta_table_uid in requested_canonical
        summaries = [
            dataset_summary(context, index=index, dataset=dataset) for index in visible_indexes
        ]
        counts_available = all(item.row_count is not None for item in summaries)
        impacts.append(
            IndexDatasetDeleteImpact(
                meta_table_uid=dataset.meta_table_uid,
                identifier=dataset.identifier,
                cadence=dataset.cadence,
                storage_kind=dataset.storage_kind,
                selected=selected,
                affected_index_uids=tuple(index.uid for index in visible_indexes),
                affected_row_count=(
                    sum(int(item.row_count or 0) for item in summaries)
                    if counts_available
                    else None
                ),
                count_accuracy="exact" if counts_available else "unavailable",
                earliest_time_index=_minimum_time(item.earliest_time_index for item in summaries),
                latest_time_index=_maximum_time(item.latest_time_index for item in summaries),
                access=dataset.access,
                scoped_delete_supported=dataset.scoped_delete_supported,
            )
        )

    extension_provider_by_uid: dict[str, Any] = {}
    for provider in list_index_relationship_providers():
        try:
            meta_table = provider.resolve_meta_table()
        except Exception:
            continue
        meta_table_uid = str(getattr(meta_table, "uid", ""))
        if (
            meta_table_uid
            and provider.delete_capability == "scoped"
            and provider.delete_implementation is not None
        ):
            extension_provider_by_uid[meta_table_uid] = provider
            provider_relationships = [item for item in relationships if item.key == provider.key]
            counts_available = all(item.count is not None for item in provider_relationships)
            impacts.append(
                IndexDatasetDeleteImpact(
                    meta_table_uid=meta_table_uid,
                    identifier=str(getattr(meta_table, "identifier", provider.key)),
                    cadence=(str(getattr(meta_table, "cadence", "") or "") or None),
                    storage_kind=provider.storage_kind,
                    provider_key=provider.key,
                    selected=meta_table_uid in request.declared_extension_dataset_uids,
                    affected_index_uids=tuple(index.uid for index in visible_indexes),
                    affected_row_count=(
                        sum(int(item.count or 0) for item in provider_relationships)
                        if counts_available
                        else None
                    ),
                    count_accuracy="exact" if counts_available else "unavailable",
                    access=IndexDatasetAccess(
                        can_view=True,
                        can_edit=None,
                        reason="Edit access is rechecked by the platform at mutation time.",
                    ),
                    scoped_delete_supported=True,
                )
            )
    unknown_extensions = set(request.declared_extension_dataset_uids) - set(
        extension_provider_by_uid
    )
    resolved_relationships = [item for item in relationships if item.key == "resolved_index_legs"]
    resolved_meta_table_uid = next(
        (
            item.meta_table_uid
            for item in resolved_relationships
            if item.meta_table_uid not in (None, "")
        ),
        None,
    )
    if resolved_meta_table_uid is not None:
        resolved_counts_available = all(item.count is not None for item in resolved_relationships)
        impacts.append(
            IndexDatasetDeleteImpact(
                meta_table_uid=resolved_meta_table_uid,
                identifier=resolved_relationships[0].identifier,
                storage_kind="resolved_index_legs",
                selected=request.mode == "identity_and_values",
                affected_index_uids=tuple(index.uid for index in visible_indexes),
                affected_row_count=(
                    sum(int(item.count or 0) for item in resolved_relationships)
                    if resolved_counts_available
                    else None
                ),
                count_accuracy="exact" if resolved_counts_available else "unavailable",
                access=IndexDatasetAccess(
                    can_view=True,
                    can_edit=None,
                    reason="Edit access is rechecked by the platform at mutation time.",
                ),
                scoped_delete_supported=True,
            )
        )
    selected_relationship_keys = {
        item.provider_key for item in impacts if item.selected and item.provider_key
    }
    if any(item.selected and item.storage_kind == "resolved_index_legs" for item in impacts):
        selected_relationship_keys.add("resolved_index_legs")
    relationship_blocks_identity = any(
        item.blocks_delete and item.key not in selected_relationship_keys for item in relationships
    )
    indexes = [
        item.model_copy(
            update={
                "can_delete_identity": item.exists
                and int(item.component_dependency_count or 0) == 0
                and not relationship_blocks_identity
            }
        )
        for item in indexes
    ]

    warnings = _warnings(
        request=request,
        indexes=indexes,
        datasets=impacts,
        relationships=relationships,
        unknown_canonical=unknown_canonical,
        unknown_extensions=unknown_extensions,
    )
    executable = _is_executable(
        request=request,
        indexes=indexes,
        datasets=impacts,
        relationships=relationships,
        unknown_canonical=unknown_canonical,
        unknown_extensions=unknown_extensions,
    )
    confirmation_phrase = _confirmation_phrase(request.mode, len(request.index_uids))
    scope_basis = {
        "request": request.model_dump(mode="json"),
        "indexes": [item.model_dump(mode="json") for item in indexes],
        "datasets": [item.model_dump(mode="json") for item in impacts],
        "relationships": [item.model_dump(mode="json") for item in relationships],
        "warnings": [item.model_dump(mode="json") for item in warnings],
        "executable": executable,
        "confirmation_phrase": confirmation_phrase,
    }
    scope_hash = _sha256_json(scope_basis)
    plan_id = uuid.uuid4()
    expires_at = created_at + TOKEN_TTL
    token = _sign_token(
        {
            "v": TOKEN_VERSION,
            "plan_id": str(plan_id),
            "actor_user_uid": actor.user_uid,
            "request": request.model_dump(mode="json"),
            "scope_hash": scope_hash,
            "iat": int(created_at.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
    )
    required_codes = tuple(item.code for item in warnings if item.requires_acknowledgement)
    preview = IndexBulkDeletePreview(
        plan_id=plan_id,
        requested_mode=request.mode,
        normalized_request=request,
        created_at=created_at,
        expires_at=expires_at,
        created_by_user_uid=actor.user_uid,
        scope_hash=scope_hash,
        confirmation_token=token,
        executable=executable,
        indexes=tuple(indexes),
        datasets=tuple(impacts),
        relationships=tuple(relationships),
        warnings=tuple(warnings),
        required_acknowledgement_codes=required_codes,
        confirmation_phrase=confirmation_phrase,
    )
    logger.info(
        "Prepared reviewed Index deletion preview",
        plan_id=str(plan_id),
        actor_user_uid=actor.user_uid,
        requested_mode=request.mode,
        index_uids=[str(item) for item in request.index_uids],
        selected_dataset_uids=[item.meta_table_uid for item in preview.datasets if item.selected],
        executable=preview.executable,
        warning_codes=[item.code for item in preview.warnings],
    )
    return preview


def execute_bulk_delete(
    context: MarketsOperationContext,
    *,
    actor: IndexActor,
    request: IndexBulkDeleteExecuteRequest,
    expected_single_index_uid: uuid.UUID | str | None = None,
    now: dt.datetime | None = None,
) -> IndexBulkDeleteResult:
    """Execute or resume exactly one reviewed deletion saga."""

    payload = _verify_token(request.confirmation_token, actor=actor, now=now)
    plan_id = uuid.UUID(payload["plan_id"])
    preview_request = IndexBulkDeletePreviewRequest.model_validate(payload["request"])
    if expected_single_index_uid is not None and preview_request.index_uids != (
        uuid.UUID(str(expected_single_index_uid)),
    ):
        raise IndexDeletionScopeChanged(
            "The reviewed deletion plan does not target exactly this single Index UID."
        )
    existing = _get_journal(context, actor.user_uid, request.idempotency_key)
    if existing is not None:
        if str(existing["scope_hash"]) != str(payload["scope_hash"]):
            raise IndexDeletionScopeChanged(
                "This idempotency key is already bound to another reviewed deletion scope."
            )
        stored_result = (existing.get("step_results_json") or {}).get("result")
        if existing.get("status") == "completed" and stored_result:
            result = IndexBulkDeleteResult.model_validate(stored_result)
            logger.info(
                "Replayed completed Index deletion result",
                plan_id=str(result.plan_id),
                actor_user_uid=actor.user_uid,
                requested_mode=result.requested_mode,
                idempotency_key=request.idempotency_key,
                status=result.status,
            )
            return result
        plan_id = uuid.UUID(str(existing["plan_id"]))

    if existing is None:
        fresh = preview_bulk_delete(context, actor=actor, request=preview_request, now=now)
        if fresh.scope_hash != payload["scope_hash"]:
            raise IndexDeletionScopeChanged(
                "The Index deletion impact changed after preview; review a fresh preview.",
                fresh_preview=fresh,
            )
        if not fresh.executable:
            raise IndexDeletionScopeChanged(
                "The reviewed Index deletion plan is not executable.",
                fresh_preview=fresh,
            )
        _validate_confirmation(request, fresh)
        journal = _create_journal(
            context,
            actor=actor,
            idempotency_key=request.idempotency_key,
            preview=fresh,
            plan_id=plan_id,
        )
        targets = dict(journal.get("step_results_json") or {})
        warnings = fresh.warnings
        indexes = fresh.indexes
    else:
        targets = dict(existing.get("step_results_json") or {})
        expected_phrase = _confirmation_phrase(
            preview_request.mode, len(preview_request.index_uids)
        )
        required_codes = tuple(targets.get("required_acknowledgement_codes") or ())
        _validate_confirmation_values(
            request,
            expected_phrase=expected_phrase,
            required_codes=required_codes,
        )
        warnings = tuple(
            IndexDeleteWarning.model_validate(item) for item in targets.get("warnings", ())
        )
        indexes = tuple(
            IndexDeleteItemImpact.model_validate(item) for item in targets.get("indexes", ())
        )

    completed_steps = set(targets.get("completed_steps") or ())
    stored_dataset_results = dict(targets.get("dataset_step_results") or {})
    stored_index_results = dict(targets.get("index_step_results") or {})
    identifiers = sorted(
        item.unique_identifier for item in indexes if item.unique_identifier is not None
    )
    index_results: list[IndexDeleteItemResult] = [
        IndexDeleteItemResult(
            index_uid=item.uid,
            unique_identifier=item.unique_identifier,
            status="not_started",
        )
        for item in indexes
    ]
    dataset_results: list[IndexDatasetDeleteResult] = []
    deleted_value_count = 0
    deleted_resolved_leg_count = 0
    failure: Exception | None = None

    _update_journal(context, targets, status="running", completed_at=None)
    for target in targets.get("datasets", ()):
        step_key = f"dataset:{target['meta_table_uid']}"
        if step_key in completed_steps:
            stored_result = IndexDatasetDeleteResult.model_validate(
                stored_dataset_results[step_key]
            )
            dataset_results.append(stored_result)
            if target["storage_kind"] == "resolved_index_legs":
                deleted_resolved_leg_count += stored_result.deleted_count or 0
            else:
                deleted_value_count += stored_result.deleted_count or 0
            continue
        try:
            if target.get("provider_key"):
                provider = next(
                    (
                        item
                        for item in list_index_relationship_providers()
                        if item.key == target["provider_key"]
                    ),
                    None,
                )
                if provider is None or provider.delete_implementation is None:
                    raise RuntimeError(
                        f"Index relationship provider {target['provider_key']!r} is no longer available"
                    )
                current_meta_table = provider.resolve_meta_table()
                if str(getattr(current_meta_table, "uid", "")) != str(target["meta_table_uid"]):
                    raise IndexDeletionScopeChanged(
                        f"Index relationship provider {target['provider_key']!r} now resolves to another MetaTable"
                    )
                result = provider.delete_implementation(
                    index_identifiers=identifiers,
                    index_uids=[str(item.uid) for item in indexes],
                    actor=actor,
                    timeout=context.timeout,
                )
            else:
                result = _delete_time_indexed_dataset(
                    target["meta_table_uid"],
                    identifiers=identifiers,
                    timeout=context.timeout,
                )
            deleted_count = _deleted_count(result)
            if target["storage_kind"] == "resolved_index_legs":
                deleted_resolved_leg_count += deleted_count or 0
            else:
                deleted_value_count += deleted_count or 0
            dataset_results.append(
                dataset_result := IndexDatasetDeleteResult(
                    meta_table_uid=target["meta_table_uid"],
                    identifier=target["identifier"],
                    status="deleted" if deleted_count else "already_empty",
                    deleted_count=deleted_count,
                )
            )
            completed_steps.add(step_key)
            targets["completed_steps"] = sorted(completed_steps)
            stored_dataset_results[step_key] = dataset_result.model_dump(mode="json")
            targets["dataset_step_results"] = stored_dataset_results
            _update_journal(context, targets, status="running", completed_at=None)
        except Exception as exc:
            failure = exc
            dataset_results.append(
                IndexDatasetDeleteResult(
                    meta_table_uid=target["meta_table_uid"],
                    identifier=target["identifier"],
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
            break

    if failure is None and preview_request.mode in {"identity_only", "identity_and_values"}:
        current_relationships: list[IndexRelatedMetaTable] = []
        for impact in indexes:
            current = _get_index(context, impact.uid)
            if current is not None:
                current_relationships.extend(list_related_meta_tables(context, index=current))
        if any(item.blocks_delete for item in current_relationships):
            failure = IndexDeletionScopeChanged(
                "A blocking Index relationship appeared before identity deletion."
            )

    if failure is None and preview_request.mode in {"identity_only", "identity_and_values"}:
        for position, impact in enumerate(indexes):
            step_key = f"index:{impact.uid}"
            if step_key in completed_steps:
                index_results[position] = IndexDeleteItemResult.model_validate(
                    stored_index_results[step_key]
                )
                continue
            try:
                current = _get_index(context, impact.uid)
                if current is None:
                    status = "already_absent"
                else:
                    delete_model(context, model=IndexTable, uid=impact.uid)
                    status = "deleted"
                index_results[position] = index_result = IndexDeleteItemResult(
                    index_uid=impact.uid,
                    unique_identifier=impact.unique_identifier,
                    status=status,
                )
                completed_steps.add(step_key)
                targets["completed_steps"] = sorted(completed_steps)
                stored_index_results[step_key] = index_result.model_dump(mode="json")
                targets["index_step_results"] = stored_index_results
                _update_journal(context, targets, status="running", completed_at=None)
            except Exception as exc:
                failure = exc
                index_results[position] = IndexDeleteItemResult(
                    index_uid=impact.uid,
                    unique_identifier=impact.unique_identifier,
                    status="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
                break
    elif preview_request.mode == "values_only":
        index_results = [
            IndexDeleteItemResult(
                index_uid=item.uid,
                unique_identifier=item.unique_identifier,
                status="kept",
            )
            for item in indexes
        ]

    completed_any = bool(completed_steps)
    final_status = "completed" if failure is None else ("partial" if completed_any else "failed")
    result = IndexBulkDeleteResult(
        status=final_status,
        plan_id=plan_id,
        idempotency_key=request.idempotency_key,
        requested_mode=preview_request.mode,
        requested_index_count=len(indexes),
        deleted_index_count=sum(item.status == "deleted" for item in index_results),
        deleted_value_count=deleted_value_count,
        deleted_resolved_leg_count=deleted_resolved_leg_count,
        index_results=tuple(index_results),
        dataset_results=tuple(dataset_results),
        warnings=tuple(warnings),
    )
    targets["result"] = result.model_dump(mode="json")
    if failure is not None:
        targets["last_error"] = f"{type(failure).__name__}: {failure}"
    _update_journal(
        context,
        targets,
        status=final_status,
        completed_at=_utc_now(now),
    )
    logger.info(
        "Finished reviewed Index deletion execution",
        plan_id=str(result.plan_id),
        actor_user_uid=actor.user_uid,
        requested_mode=result.requested_mode,
        idempotency_key=request.idempotency_key,
        status=result.status,
        deleted_index_count=result.deleted_index_count,
        deleted_value_count=result.deleted_value_count,
        deleted_resolved_leg_count=result.deleted_resolved_leg_count,
    )
    return result


def _warnings(
    *,
    request: IndexBulkDeletePreviewRequest,
    indexes: list[IndexDeleteItemImpact],
    datasets: list[IndexDatasetDeleteImpact],
    relationships: list[IndexRelatedMetaTable],
    unknown_canonical: set[str],
    unknown_extensions: set[str],
) -> list[IndexDeleteWarning]:
    index_uids = tuple(item.uid for item in indexes)
    selected_datasets = tuple(item.meta_table_uid for item in datasets if item.selected)
    selected_resolved_leg_datasets = tuple(
        item.meta_table_uid
        for item in datasets
        if item.selected and item.storage_kind == "resolved_index_legs"
    )
    warnings: list[IndexDeleteWarning] = []

    def add(
        code: str,
        severity: str,
        title: str,
        message: str,
        *,
        acknowledgement: bool = True,
        meta_table_uids: tuple[str, ...] = (),
    ) -> None:
        warnings.append(
            IndexDeleteWarning(
                code=code,
                severity=severity,
                title=title,
                message=message,
                affected_index_uids=index_uids,
                affected_meta_table_uids=meta_table_uids,
                requires_acknowledgement=acknowledgement,
            )
        )

    if request.mode in {"identity_only", "identity_and_values"}:
        add(
            "permanent_identity_deletion",
            "destructive",
            "Index identity deletion is permanent",
            "Selected Index identities and cascade-owned definitions and legs cannot be recovered automatically.",
        )
    if request.mode in {"values_only", "identity_and_values"}:
        add(
            "permanent_value_deletion",
            "destructive",
            "Index value deletion is permanent",
            "Selected historical values will be removed from every listed cadence table.",
            meta_table_uids=selected_datasets,
        )
        add(
            "all_timestamps_in_scope",
            "destructive",
            "All timestamps are in scope",
            "The scoped delete uses after_date=None and removes every timestamp for the selected Index streams.",
            meta_table_uids=selected_datasets,
        )
        if selected_resolved_leg_datasets:
            add(
                "resolved_leg_provenance_deletion",
                "destructive",
                "Resolved-leg provenance will be deleted",
                "All selected dynamic component and coefficient audit rows will be removed before Index identity deletion.",
                meta_table_uids=selected_resolved_leg_datasets,
            )
        add(
            "data_node_state_not_reset",
            "warning",
            "DataNode state is not reset",
            "Update statistics, checkpoints, schedules, jobs, hashes, and producer configuration remain unchanged.",
        )
        add(
            "data_may_be_republished",
            "warning",
            "Values may be republished",
            "An active or scheduled producer can recreate deleted values.",
        )
        add(
            "producer_quiescence_unknown",
            "warning",
            "Producer quiescence is unknown",
            "This API cannot prove that every producer for the selected datasets is stopped.",
        )
    add(
        "cross_table_non_atomic",
        "warning",
        "Deletion is not cross-table atomic",
        "A later step can fail after an earlier MetaTable has already been changed.",
    )
    if not request.declared_extension_dataset_uids:
        add(
            "extension_values_excluded",
            "warning",
            "Extension-owned values are excluded",
            "Extension-owned Index tables are untouched unless an authoritative delete provider is explicitly selected.",
        )
    if any(not item.authoritative for item in relationships):
        add(
            "inferred_tables_not_deleted",
            "warning",
            "Inferred tables are not deleted",
            "Inferred related tables are informational and are never automatic delete targets.",
        )
    if any(
        item.count_accuracy == "unavailable"
        for item in _datasets_requiring_counts(request, datasets)
    ):
        add(
            "counts_unavailable",
            "blocking",
            "Affected counts are unavailable",
            "At least one required dataset could not produce an authoritative scoped count.",
        )
    if request.mode in {"identity_only", "identity_and_values"} and any(
        item.authoritative
        and _on_delete_action(item.on_delete) in {"RESTRICT", "NO ACTION"}
        and item.count is None
        for item in relationships
    ):
        add(
            "relationship_counts_unavailable",
            "blocking",
            "Relationship counts are unavailable",
            "At least one authoritative restrictive relationship could not be counted before identity deletion.",
        )
    unselected_nonempty_datasets = tuple(
        item.meta_table_uid
        for item in datasets
        if request.mode in {"identity_only", "identity_and_values"}
        and not item.selected
        and int(item.affected_row_count or 0) > 0
    )
    if unselected_nonempty_datasets:
        add(
            "unselected_values_block_identity",
            "blocking",
            "Existing Index data is outside the delete scope",
            "Index identity deletion is blocked while a listed canonical, resolved-leg, or declared extension dataset still contains rows outside the reviewed delete scope.",
            meta_table_uids=unselected_nonempty_datasets,
        )
    if any(item.access.can_edit is False for item in datasets if item.selected):
        add(
            "insufficient_edit_access",
            "blocking",
            "Edit access is insufficient",
            "The caller lacks confirmed edit access to at least one required resource.",
        )
    elif any(item.access.can_edit is None for item in datasets if item.selected):
        add(
            "edit_access_rechecked_on_execution",
            "warning",
            "Edit access will be rechecked",
            "The catalog cannot prove edit access for every selected table; each governed mutation will enforce current platform access.",
        )
    if any(int(item.component_dependency_count or 0) > 0 for item in indexes):
        add(
            "definition_dependency_blocks_delete",
            "blocking",
            "A methodology depends on this Index",
            "Another calculation definition uses a selected Index as a component.",
        )
    if any(
        _on_delete_action(item.on_delete) == "SET NULL" and int(item.count or 0)
        for item in relationships
    ):
        add(
            "set_null_side_effect",
            "warning",
            "Dependent links will be cleared",
            "Known dependent rows remain but lose their Index link.",
        )
    if any(
        _on_delete_action(item.on_delete) == "CASCADE" and int(item.count or 0)
        for item in relationships
    ):
        add(
            "cascade_side_effect",
            "destructive",
            "Dependent rows will cascade",
            "Known cascade-owned rows will be removed with the Index identity.",
        )
    if any(item.delete_capability == "manual" and int(item.count or 0) for item in relationships):
        add(
            "manual_cleanup_required",
            "blocking",
            "Manual cleanup is required",
            "A declared relationship must be removed or repointed outside this operation.",
        )
    if unknown_canonical or unknown_extensions:
        add(
            "unknown_dataset_selection",
            "blocking",
            "A selected dataset is not authoritative",
            "One or more requested dataset UIDs are not visible authoritative Index relationship providers.",
            acknowledgement=False,
            meta_table_uids=tuple(sorted(unknown_canonical | unknown_extensions)),
        )
    return warnings


def _is_executable(
    *,
    request: IndexBulkDeletePreviewRequest,
    indexes: list[IndexDeleteItemImpact],
    datasets: list[IndexDatasetDeleteImpact],
    relationships: list[IndexRelatedMetaTable],
    unknown_canonical: set[str],
    unknown_extensions: set[str],
) -> bool:
    if unknown_canonical or unknown_extensions or any(not item.exists for item in indexes):
        return False
    if any(
        item.count_accuracy == "unavailable"
        for item in _datasets_requiring_counts(request, datasets)
    ):
        return False
    if any(item.access.can_edit is False for item in datasets if item.selected):
        return False
    if request.mode in {"identity_only", "identity_and_values"}:
        if any(not item.can_delete_identity for item in indexes):
            return False
        selected_relationship_keys = {
            item.provider_key for item in datasets if item.selected and item.provider_key
        }
        if any(item.selected and item.storage_kind == "resolved_index_legs" for item in datasets):
            selected_relationship_keys.add("resolved_index_legs")
        if any(
            item.blocks_delete and item.key not in selected_relationship_keys
            for item in relationships
        ):
            return False
        if any(
            item.authoritative
            and _on_delete_action(item.on_delete) in {"RESTRICT", "NO ACTION"}
            and item.count is None
            for item in relationships
        ):
            return False
    rows_by_dataset = {item.meta_table_uid: int(item.affected_row_count or 0) for item in datasets}
    if request.mode == "identity_only" and any(rows_by_dataset.values()):
        return False
    if request.mode == "identity_and_values":
        if any(
            count > 0 and not next(item for item in datasets if item.meta_table_uid == uid).selected
            for uid, count in rows_by_dataset.items()
        ):
            return False
    return True


def _datasets_requiring_counts(
    request: IndexBulkDeletePreviewRequest,
    datasets: list[IndexDatasetDeleteImpact],
) -> tuple[IndexDatasetDeleteImpact, ...]:
    return tuple(
        item
        for item in datasets
        if item.selected
        or (
            item.storage_kind == "canonical_index_values"
            and request.mode in {"identity_only", "identity_and_values"}
        )
    )


def _on_delete_action(value: str) -> str:
    return str(value).upper().replace("_", " ")


def _validate_confirmation(
    request: IndexBulkDeleteExecuteRequest,
    preview: IndexBulkDeletePreview,
) -> None:
    _validate_confirmation_values(
        request,
        expected_phrase=preview.confirmation_phrase,
        required_codes=preview.required_acknowledgement_codes,
    )


def _validate_confirmation_values(
    request: IndexBulkDeleteExecuteRequest,
    *,
    expected_phrase: str,
    required_codes: tuple[str, ...],
) -> None:
    if not request.confirmation_token:
        raise IndexDeletionConfirmationRequired("A preview confirmation token is required.")
    if request.confirmation_phrase != expected_phrase:
        raise IndexDeletionConfirmationRequired("The confirmation phrase does not match exactly.")
    missing = set(required_codes) - set(request.acknowledged_warning_codes)
    if missing:
        raise IndexDeletionConfirmationRequired(
            f"Required warning acknowledgements are missing: {', '.join(sorted(missing))}"
        )


def _get_index(context: MarketsOperationContext, index_uid: uuid.UUID | str) -> Index | None:
    rows = operation_result_rows(
        search_model(
            context,
            model=IndexTable,
            filters={"uid": uuid.UUID(str(index_uid))},
            limit=1,
        )
    )
    return Index.model_validate(rows[0]) if rows else None


def _delete_time_indexed_dataset(
    meta_table_uid: str,
    *,
    identifiers: list[str],
    timeout: int | float | tuple[float, float] | None,
) -> dict[str, Any]:
    matches = TimeIndexMetaTable.filter_by_body(uid__in=[meta_table_uid], limit=1, offset=0)
    if not matches:
        raise LookupError(f"TimeIndexMetaTable {meta_table_uid!r} is not visible")
    resolved_timeout = timeout if isinstance(timeout, int) else None
    return matches[0].delete_after_date(
        None,
        dimension_filters={"index_identifier": identifiers},
        timeout=resolved_timeout,
    )


def _create_journal(
    context: MarketsOperationContext,
    *,
    actor: IndexActor,
    idempotency_key: str,
    preview: IndexBulkDeletePreview,
    plan_id: uuid.UUID,
) -> dict[str, Any]:
    state = {
        "journal_uid": None,
        "indexes": [item.model_dump(mode="json") for item in preview.indexes],
        "datasets": [item.model_dump(mode="json") for item in preview.datasets if item.selected],
        "warnings": [item.model_dump(mode="json") for item in preview.warnings],
        "required_acknowledgement_codes": list(preview.required_acknowledgement_codes),
        "completed_steps": [],
        "dataset_step_results": {},
        "index_step_results": {},
        "resolved_leg_deleted_count": 0,
    }
    result = create_model(
        context,
        model=IndexDeletionExecutionTable,
        values={
            "plan_id": plan_id,
            "actor_user_uid": actor.user_uid,
            "idempotency_key": idempotency_key,
            "scope_hash": preview.scope_hash,
            "requested_mode": preview.requested_mode,
            "status": "pending",
            "started_at": preview.created_at,
            "completed_at": None,
            "step_results_json": state,
        },
    )
    rows = operation_result_rows(result)
    if not rows:
        raise RuntimeError("Index deletion journal insert did not return a row")
    row = rows[0]
    state["journal_uid"] = str(row["uid"])
    update_model(
        context,
        model=IndexDeletionExecutionTable,
        uid=row["uid"],
        values={"step_results_json": state},
    )
    row["step_results_json"] = state
    return row


def _get_journal(
    context: MarketsOperationContext,
    actor_user_uid: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    rows = operation_result_rows(
        search_model(
            context,
            model=IndexDeletionExecutionTable,
            filters={
                "actor_user_uid": actor_user_uid,
                "idempotency_key": idempotency_key,
            },
            limit=1,
        )
    )
    return rows[0] if rows else None


def _update_journal(
    context: MarketsOperationContext,
    state: dict[str, Any],
    *,
    status: str,
    completed_at: dt.datetime | None,
) -> None:
    journal_uid = state.get("journal_uid")
    if not journal_uid:
        raise RuntimeError("Index deletion journal state has no journal_uid")
    update_model(
        context,
        model=IndexDeletionExecutionTable,
        uid=journal_uid,
        values={
            "status": status,
            "completed_at": completed_at,
            "step_results_json": state,
        },
    )


def _deleted_count(result: dict[str, Any] | None) -> int | None:
    if not isinstance(result, dict):
        return None
    for key in ("deleted_count", "count", "rows_deleted"):
        value = result.get(key)
        if value is not None:
            return int(value)
    data = result.get("data")
    if isinstance(data, dict):
        return _deleted_count(data)
    return None


def _confirmation_phrase(mode: str, count: int) -> str:
    noun = "INDEX" if count == 1 else "INDEXES"
    if mode == "values_only":
        return f"DELETE ALL SELECTED INDEX VALUES FOR {count} {noun}"
    if mode == "identity_and_values":
        return f"DELETE {count} {noun} AND ALL SELECTED INDEX VALUES"
    return f"DELETE {count} {noun}"


def _sign_token(payload: dict[str, Any]) -> str:
    secret = _token_secret()
    encoded_payload = _b64encode(_canonical_json(payload).encode())
    signature = hmac.new(secret, encoded_payload.encode(), hashlib.sha256).digest()
    return f"{encoded_payload}.{_b64encode(signature)}"


def _verify_token(
    token: str,
    *,
    actor: IndexActor,
    now: dt.datetime | None,
) -> dict[str, Any]:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = hmac.new(_token_secret(), encoded_payload.encode(), hashlib.sha256).digest()
        supplied = _b64decode(encoded_signature)
        if not hmac.compare_digest(expected, supplied):
            raise ValueError("signature mismatch")
        payload = json.loads(_b64decode(encoded_payload).decode())
    except Exception as exc:
        raise IndexDeletionConfirmationRequired(
            "Invalid Index deletion confirmation token."
        ) from exc
    if payload.get("v") != TOKEN_VERSION:
        raise IndexDeletionConfirmationRequired("Unsupported Index deletion token version.")
    if payload.get("actor_user_uid") != actor.user_uid:
        raise IndexDeletionAccessDenied("The confirmation token belongs to another actor.")
    if int(payload.get("exp", 0)) < int(_utc_now(now).timestamp()):
        raise IndexDeletionTokenExpired("The Index deletion confirmation token expired.")
    return payload


def _token_secret() -> bytes:
    secret = os.getenv(TOKEN_SECRET_ENV, "")
    if len(secret) < 32:
        raise RuntimeError(
            f"{TOKEN_SECRET_ENV} must be injected from a platform Secret and contain at least 32 characters"
        )
    return secret.encode()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode()).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _utc_now(value: dt.datetime | None) -> dt.datetime:
    current = value or dt.datetime.now(dt.UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return current.astimezone(dt.UTC)


def _minimum_time(values):
    resolved = [value for value in values if value is not None]
    return min(resolved) if resolved else None


def _maximum_time(values):
    resolved = [value for value in values if value is not None]
    return max(resolved) if resolved else None


__all__ = [
    "IndexDeletionAccessDenied",
    "IndexDeletionConfirmationRequired",
    "IndexDeletionError",
    "IndexDeletionScopeChanged",
    "IndexDeletionTokenExpired",
    "execute_bulk_delete",
    "preview_bulk_delete",
]
