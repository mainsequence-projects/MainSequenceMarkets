"""Thin apps/v1 helpers for Command Center bulk-action HTTP contracts."""

from __future__ import annotations

from uuid import UUID

from apps.v1.schemas.bulk_actions import (
    BulkActionConfirmation,
    BulkActionDefinition,
    BulkActionExecutionRequest,
    BulkActionExplicitSelection,
    BulkActionPreflightResponse,
)


def build_bulk_delete_action(
    *,
    action_id: str,
    label: str,
    endpoint: str,
    preflight_endpoint: str,
    confirmation_title: str,
    confirmation_warning: str,
) -> BulkActionDefinition:
    return BulkActionDefinition(
        id=action_id,
        label=label,
        endpoint=endpoint,
        preflight_endpoint=preflight_endpoint,
        method="POST",
        tone="danger",
        selection_modes=["explicit"],
        confirmation=BulkActionConfirmation(
            title=confirmation_title,
            word="DELETE",
            button_label=label,
            warning=confirmation_warning,
        ),
        options=[],
    )


def explicit_uuid_selection(request: BulkActionExecutionRequest) -> list[str]:
    if not isinstance(request.selection, BulkActionExplicitSelection):
        raise ValueError("This bulk action supports only explicit UID selection.")
    if request.options:
        unsupported = ", ".join(sorted(request.options))
        raise ValueError(f"This bulk action does not support options: {unsupported}.")

    normalized: list[str] = []
    for resource_id in request.selection.uids:
        try:
            normalized.append(str(UUID(str(resource_id))))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Bulk-action resource id {resource_id!r} is not a UUID.") from exc
    return normalized


def blocked_preflight_detail(preflight: BulkActionPreflightResponse) -> str:
    messages = list(preflight.blockers or [])
    if messages:
        return " ".join(messages)
    return preflight.detail or "The bulk action is not allowed."


__all__ = [
    "blocked_preflight_detail",
    "build_bulk_delete_action",
    "explicit_uuid_selection",
]
