"""Bulk deletes that delete what may go and report the rest (issue 128).

A bulk delete never refuses the selection because one item cannot be deleted. It deletes
every selected row that may go, together, and answers one envelope: ``detail``,
``deleted_count``, ``deleted`` and ``failed``, where each item of ``failed`` gives the
``uid`` and the reason. The portfolio and account bulk deletes answer the same envelope
with their own items.

A delete MetaTables does not answer (``metatables.TransferOutcomeUnknown``) may have
committed or not. `confirm_unknown_delete` reads the rows once to tell (issue 151).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from mainsequence.client.exceptions import ApiError
from mainsequence.logconf import logger as _mainsequence_logger
from metatables import ApiResolutionError, TransferOutcomeUnknown
from metatables.contracts.transfer import TransferError

from msm.repositories.base import MarketsRepositoryContext
from msm.repositories.crud import delete_models, existing_model_uids

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

    When MetaTables does not answer the statement, `confirm_unknown_delete` reads the rows
    (issue 151). Nothing read them before the delete, so a row that is gone was deleted by
    it or never existed: it is reported in ``failed`` as gone, never as deleted.
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
        except TransferOutcomeUnknown as exc:
            gone, refused = confirm_unknown_delete(
                context,
                model=model,
                labels={uid: f"{label} {uid}" for uid in target},
                noun=label,
                error=exc,
            )
            refused.update(
                {
                    uid: (
                        f"{label} {uid} is gone: MetaTables did not answer its delete, so this "
                        "call deleted it, or it did not exist."
                    )
                    for uid in gone
                }
            )
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


def confirm_unknown_delete(
    context: MarketsRepositoryContext,
    *,
    model: type[Any],
    labels: Mapping[str, str],
    noun: str,
    error: TransferOutcomeUnknown,
    not_found: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, str]]:
    """After one all-or-nothing delete got no answer: the uids it deleted, and why not the rest.

    ``labels`` names each uid of ``model`` the delete was sent for, in its order
    ("Portfolio 'A'"), and ``noun`` one row ("Portfolio"). One read of ``model`` tells:
    when none of the rows is left, the delete committed and every uid is returned.
    Otherwise it did not commit, or not yet: the outcome of a row left is unknown, since
    the transaction can outlive the request, and a row gone was deleted by another call
    and is not found (``not_found`` gives that reason per uid; by default "<noun> <uid>
    was not found."). When the read fails too, the outcome of every row is unknown. Each
    unknown outcome's reason says the call may be retried.
    """

    uids = list(labels)
    logger.warning("A delete got no answer; reading its rows again.", model=model.__name__, error=str(error))
    try:
        remaining = existing_model_uids(context, model=model, uids=uids)
    except (ApiError, ApiResolutionError, TransferError) as read_error:
        logger.warning("Reading the rows of a delete without an answer failed.", error=str(read_error))
        return [], {
            uid: (
                f"{label}: the outcome of its delete is unknown. MetaTables did not answer it, "
                f"and reading the {noun.lower()} again failed too ({type(read_error).__name__}). "
                "The call may be retried."
            )
            for uid, label in labels.items()
        }
    if not remaining:
        return uids, {}
    missing = not_found or {}
    return [], {
        uid: (
            f"{label}: the outcome of its delete is unknown. MetaTables did not answer it, "
            f"and the {noun.lower()} still existed when read again; the delete may still "
            "finish. The call may be retried."
            if uid in remaining
            else missing.get(uid, f"{noun} {uid} was not found.")
        )
        for uid, label in labels.items()
    }


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


__all__ = [
    "bulk_delete_response",
    "bulk_delete_rows",
    "canonical_uid",
    "confirm_unknown_delete",
    "is_delete_conflict",
]
