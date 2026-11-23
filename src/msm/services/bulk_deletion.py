"""Bulk deletes that delete what may go and report the rest (issue 128).

A bulk delete never refuses the selection because one item cannot be deleted. It deletes
every selected row that may go, together, and answers one envelope: ``detail``,
``deleted_count``, ``deleted`` and ``failed``, where each item of ``failed`` gives the
``uid`` and the reason. The portfolio and account bulk deletes answer the same envelope
with their own items.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger

from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import delete_models

logger = _mainsequence_logger.bind(sub_application="markets", component="bulk_deletion")

_CONFLICT_MARKERS = ("foreign key", "violates", "referenced", "restrict", "constraint")


def is_delete_conflict(exc: Exception) -> bool:
    """Whether ``exc`` is the database refusing a delete through a key."""

    text = str(exc).lower()
    return any(marker in text for marker in _CONFLICT_MARKERS)


def bulk_delete_rows(
    context: MarketsRepositoryContext,
    *,
    model: type[Any],
    uids: Sequence[uuid.UUID | str],
    label: str,
    plural: str,
    table_blockers: Sequence[str] = (),
) -> dict[str, Any]:
    """Delete every row of ``uids`` that exists, in one statement, and report the rest.

    ``label`` names one row in messages ("Portfolio group") and ``plural`` several
    ("portfolio groups"). ``table_blockers`` are reasons the whole table refuses the
    delete, such as MetaTables' impact blockers; each row is then reported with them and
    nothing is sent. When the database refuses the statement, which then deletes nothing,
    each row is deleted on its own, so only the refused ones stay.
    """

    target = list(dict.fromkeys(canonical_uid(uid) for uid in uids if str(uid).strip()))
    if table_blockers:
        reason = " ".join(table_blockers)
        failed = {uid: f"{label} {uid} cannot be deleted; nothing was deleted. {reason}" for uid in target}
        return bulk_delete_response([], failed, target, singular=label.lower(), plural=plural)
    deleted: list[dict[str, Any]] = []
    refused: dict[str, str] = {}
    if target:
        try:
            deleted = _returned_rows(delete_models(context, model=model, uids=target))
        except Exception as exc:
            if not is_delete_conflict(exc):
                raise
            logger.info("Bulk delete refused; deleting each row on its own.", model=model.__name__)
            deleted, refused = _delete_each(context, model=model, uids=target, label=label)
    found = {row["uid"] for row in deleted}
    failed = {
        uid: refused.get(uid, f"{label} {uid} was not found.") for uid in target if uid not in found
    }
    return bulk_delete_response(deleted, failed, target, singular=label.lower(), plural=plural)


def bulk_delete_response(
    deleted: Sequence[dict[str, Any]],
    failed: dict[str, str],
    order: Sequence[str],
    *,
    singular: str,
    plural: str,
) -> dict[str, Any]:
    """The bulk-delete envelope; ``failed`` keeps the order of the selection."""

    count = len(deleted)
    detail = (
        f"No {plural} were deleted."
        if count == 0
        else f"Deleted {count} {singular if count == 1 else plural}."
    )
    if failed:
        detail += f" {len(failed)} could not be deleted."
    return {
        "detail": detail,
        "deleted_count": count,
        "deleted": list(deleted),
        "failed": [{"uid": uid, "detail": failed[uid]} for uid in order if uid in failed],
    }


def canonical_uid(uid: uuid.UUID | str) -> str:
    return str(uuid.UUID(str(uid)))


def _delete_each(
    context: MarketsRepositoryContext,
    *,
    model: type[Any],
    uids: Sequence[str],
    label: str,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    deleted: list[dict[str, Any]] = []
    refused: dict[str, str] = {}
    for uid in uids:
        try:
            deleted.extend(_returned_rows(delete_models(context, model=model, uids=[uid])))
        except Exception as exc:
            if not is_delete_conflict(exc):
                raise
            refused[uid] = f"{label} {uid} cannot be deleted; nothing was deleted. The database refused it: {exc}"
    return deleted, refused


def _returned_rows(result: Any) -> list[dict[str, Any]]:
    rows = result.get("rows") if isinstance(result, dict) else result
    returned = []
    for row in rows or []:
        item = {"uid": canonical_uid(row["uid"])}
        if row.get("unique_identifier") is not None:
            item["unique_identifier"] = str(row["unique_identifier"])
        returned.append(item)
    return returned


__all__ = ["bulk_delete_response", "bulk_delete_rows", "canonical_uid", "is_delete_conflict"]
