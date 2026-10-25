"""Shared helpers for batch lookups by uid (ADR 0047, migration path step 1).

A batch lookup answers "these uids, as rows" for consumers that page on their
own sidecar table and hydrate core columns in one call. It is bounded, exact
and unordered; it is not a browsable collection.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from msm.api.base import operation_result_rows
from msm.repositories.crud import search_model

MAX_LOOKUP_UIDS = 500


def normalize_lookup_uids(values: Iterable[str] | None) -> list[uuid.UUID]:
    """Parse ``uid__in`` values: repeated parameters and comma-separated lists.

    Raises ``ValueError`` on an empty list, a malformed uid or more than
    ``MAX_LOOKUP_UIDS`` entries.
    """

    parsed: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in values or ():
        for part in str(raw).split(","):
            text = part.strip()
            if not text:
                continue
            try:
                value = uuid.UUID(text)
            except ValueError as exc:
                raise ValueError(f"uid__in entry {text!r} is not a UUID.") from exc
            if value in seen:
                continue
            seen.add(value)
            parsed.append(value)
    if not parsed:
        raise ValueError("uid__in requires at least one uid.")
    if len(parsed) > MAX_LOOKUP_UIDS:
        raise ValueError(f"uid__in accepts at most {MAX_LOOKUP_UIDS} uids.")
    return parsed


def rows_by_uids(context: Any, *, model: type[Any], uids: Sequence[uuid.UUID]) -> list[dict[str, Any]]:
    """Return the rows of ``model`` whose uid is in ``uids``, in uid order of the request."""

    if not uids:
        return []
    rows = operation_result_rows(
        search_model(
            context,
            model=model,
            in_filters={"uid": list(uids)},
            limit=len(uids),
        )
    )
    by_uid = {str(row["uid"]): row for row in rows}
    return [by_uid[str(uid)] for uid in uids if str(uid) in by_uid]


__all__ = ["MAX_LOOKUP_UIDS", "normalize_lookup_uids", "rows_by_uids"]
