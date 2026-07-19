from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from msm.base import (
    MarketsBase,
    MarketsMetaTableMixin,
    markets_table_args,
    new_markets_uid,
)


class IndexDeletionExecutionTable(MarketsMetaTableMixin, MarketsBase):
    """Durable idempotency and step journal for reviewed Index deletion plans."""

    __metatable_identifier__ = "IndexDeletionExecution"
    __metatable_description__ = (
        "Operational journal for reviewed Index deletion plans. Records actor, scope, "
        "idempotency, lifecycle state, and completed steps without storing confirmation "
        "tokens, signing secrets, or Index observation values."
    )
    __table_args__ = markets_table_args(
        __metatable_identifier__,
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed')",
            name="index_deletion_execution_status_valid",
        ),
        Index(None, "plan_id", unique=True),
        Index(None, "actor_user_uid", "idempotency_key", unique=True),
        Index(None, "status"),
    )

    uid: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=new_markets_uid,
        info={
            "label": "UID",
            "description": "Canonical UUID primary key for the execution-journal row.",
        },
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        info={
            "label": "Plan ID",
            "description": "Unique reviewed deletion plan represented by this journal row.",
        },
    )
    actor_user_uid: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Actor User UID",
            "description": "Authenticated platform user bound to the deletion plan.",
        },
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        info={
            "label": "Idempotency Key",
            "description": "Caller-provided retry key unique for this actor and scope.",
        },
    )
    scope_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        info={
            "label": "Scope Hash",
            "description": "SHA-256 digest of the reviewed Index deletion impact.",
        },
    )
    requested_mode: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        info={
            "label": "Requested Mode",
            "description": "Reviewed values_only, identity_only, or identity_and_values mode.",
        },
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        info={
            "label": "Status",
            "description": "Current pending, running, completed, partial, or failed state.",
        },
    )
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        info={
            "label": "Started At",
            "description": "UTC timestamp when execution of this plan first started.",
        },
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        info={
            "label": "Completed At",
            "description": "UTC timestamp when execution reached a terminal state.",
        },
    )
    step_results_json: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        info={
            "label": "Step Results JSON",
            "description": (
                "Bounded per-step status used to resume exact retries; contains no tokens, "
                "secrets, or observation values."
            ),
        },
    )


__all__ = ["IndexDeletionExecutionTable"]
