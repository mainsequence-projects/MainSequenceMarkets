"""Owner-scoped observable-operation contracts and local lifecycle storage."""

from __future__ import annotations

import datetime as dt
from threading import RLock
from typing import Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from ._base import HttpContractModel

OperationRequestT = TypeVar("OperationRequestT")
OperationResultT = TypeVar("OperationResultT")
OperationStatus = Literal["queued", "running", "succeeded", "failed"]
OperationStepStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


class OperationStep(HttpContractModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    label: str = Field(pattern=r".*\S.*")
    status: OperationStepStatus = "pending"
    message: str | None = None
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None


class OperationError(HttpContractModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(pattern=r".*\S.*")
    retryable: bool = False


class ObservableOperation(HttpContractModel, Generic[OperationRequestT, OperationResultT]):
    operation_uid: str = Field(pattern=r"^[0-9a-f-]{36}$")
    action: str = Field(pattern=r".*\S.*")
    status: OperationStatus
    current_step: str | None
    steps: list[OperationStep] = Field(min_length=1)
    request: OperationRequestT
    result: OperationResultT | None = None
    error: OperationError | None = None
    created_at: dt.datetime
    started_at: dt.datetime | None = None
    updated_at: dt.datetime
    completed_at: dt.datetime | None = None
    poll_after_ms: int = Field(default=500, ge=0)

    @field_validator("steps")
    @classmethod
    def validate_unique_step_keys(cls, value: list[OperationStep]) -> list[OperationStep]:
        keys = [step.key for step in value]
        if len(keys) != len(set(keys)):
            raise ValueError("Observable operation step keys must be unique.")
        return value

    @model_validator(mode="after")
    def validate_terminal_payload(self) -> ObservableOperation[OperationRequestT, OperationResultT]:
        if self.status == "succeeded" and self.error is not None:
            raise ValueError("A succeeded operation cannot contain an error.")
        if self.status == "failed" and self.error is None:
            raise ValueError("A failed operation must contain an error.")
        if self.status in {"succeeded", "failed"} and self.completed_at is None:
            raise ValueError("A terminal operation must have completed_at.")
        if self.status in {"queued", "running"} and self.completed_at is not None:
            raise ValueError("A non-terminal operation cannot have completed_at.")
        return self


class OperationNotFoundError(LookupError):
    """Raised when an operation is absent or belongs to a different owner."""


class OperationStateError(RuntimeError):
    """Raised when a lifecycle transition is invalid for the current state."""


class InMemoryOperationStore(Generic[OperationRequestT, OperationResultT]):
    """Thread-safe single-process operation store for local and one-worker APIs.

    This store deliberately makes no durability claim. Multi-worker or restart-safe
    deployments should persist the same ``ObservableOperation`` contract in a shared
    provider-owned repository.
    """

    def __init__(self, *, poll_after_ms: int = 500) -> None:
        if poll_after_ms < 0:
            raise ValueError("poll_after_ms must be greater than or equal to 0.")
        self._poll_after_ms = poll_after_ms
        self._lock = RLock()
        self._operations: dict[
            str,
            tuple[str | None, ObservableOperation[OperationRequestT, OperationResultT]],
        ] = {}

    def create(
        self,
        *,
        action: str,
        request: OperationRequestT,
        owner_uid: str | None,
        steps: list[tuple[str, str]],
    ) -> ObservableOperation[OperationRequestT, OperationResultT]:
        if not steps:
            raise ValueError("An observable operation requires at least one step.")
        now = _utc_now()
        operation = ObservableOperation[OperationRequestT, OperationResultT](
            operation_uid=str(uuid4()),
            action=action,
            status="queued",
            current_step=None,
            steps=[OperationStep(key=key, label=label) for key, label in steps],
            request=request,
            created_at=now,
            updated_at=now,
            poll_after_ms=self._poll_after_ms,
        )
        with self._lock:
            self._operations[operation.operation_uid] = (owner_uid, operation)
        return operation.model_copy(deep=True)

    def get(
        self,
        operation_uid: str,
        *,
        owner_uid: str | None,
    ) -> ObservableOperation[OperationRequestT, OperationResultT]:
        with self._lock:
            record = self._operations.get(operation_uid)
            if record is None or record[0] != owner_uid:
                raise OperationNotFoundError(f"Operation {operation_uid} does not exist.")
            return record[1].model_copy(deep=True)

    def start(
        self,
        operation_uid: str,
        *,
        step_key: str,
    ) -> ObservableOperation[OperationRequestT, OperationResultT]:
        with self._lock:
            owner_uid, operation = self._record(operation_uid)
            if operation.status != "queued":
                raise OperationStateError("Only a queued operation can be started.")
            now = _utc_now()
            steps = _start_step(operation.steps, step_key=step_key, now=now)
            updated = operation.model_copy(
                update={
                    "status": "running",
                    "current_step": step_key,
                    "steps": steps,
                    "started_at": now,
                    "updated_at": now,
                }
            )
            self._operations[operation_uid] = (owner_uid, updated)
            return updated.model_copy(deep=True)

    def advance(
        self,
        operation_uid: str,
        *,
        step_key: str,
        message: str | None = None,
    ) -> ObservableOperation[OperationRequestT, OperationResultT]:
        with self._lock:
            owner_uid, operation = self._record(operation_uid)
            if operation.status != "running" or operation.current_step is None:
                raise OperationStateError("Only a running operation can advance.")
            now = _utc_now()
            steps = _complete_step(
                operation.steps,
                step_key=operation.current_step,
                status="succeeded",
                now=now,
                message=message,
            )
            steps = _start_step(steps, step_key=step_key, now=now)
            updated = operation.model_copy(
                update={"current_step": step_key, "steps": steps, "updated_at": now}
            )
            self._operations[operation_uid] = (owner_uid, updated)
            return updated.model_copy(deep=True)

    def succeed(
        self,
        operation_uid: str,
        *,
        result: OperationResultT,
        message: str | None = None,
    ) -> ObservableOperation[OperationRequestT, OperationResultT]:
        with self._lock:
            owner_uid, operation = self._record(operation_uid)
            if operation.status != "running" or operation.current_step is None:
                raise OperationStateError("Only a running operation can succeed.")
            now = _utc_now()
            steps = _complete_step(
                operation.steps,
                step_key=operation.current_step,
                status="succeeded",
                now=now,
                message=message,
            )
            steps = [
                step.model_copy(update={"status": "skipped"}) if step.status == "pending" else step
                for step in steps
            ]
            updated = operation.model_copy(
                update={
                    "status": "succeeded",
                    "current_step": None,
                    "steps": steps,
                    "result": result,
                    "error": None,
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._operations[operation_uid] = (owner_uid, updated)
            return updated.model_copy(deep=True)

    def fail(
        self,
        operation_uid: str,
        *,
        error: OperationError,
        message: str | None = None,
    ) -> ObservableOperation[OperationRequestT, OperationResultT]:
        with self._lock:
            owner_uid, operation = self._record(operation_uid)
            if operation.status != "running" or operation.current_step is None:
                raise OperationStateError("Only a running operation can fail.")
            now = _utc_now()
            steps = _complete_step(
                operation.steps,
                step_key=operation.current_step,
                status="failed",
                now=now,
                message=message or error.message,
            )
            updated = operation.model_copy(
                update={
                    "status": "failed",
                    "steps": steps,
                    "error": error,
                    "updated_at": now,
                    "completed_at": now,
                }
            )
            self._operations[operation_uid] = (owner_uid, updated)
            return updated.model_copy(deep=True)

    def _record(
        self,
        operation_uid: str,
    ) -> tuple[str | None, ObservableOperation[OperationRequestT, OperationResultT]]:
        try:
            return self._operations[operation_uid]
        except KeyError as exc:
            raise OperationNotFoundError(f"Operation {operation_uid} does not exist.") from exc


def _start_step(
    steps: list[OperationStep],
    *,
    step_key: str,
    now: dt.datetime,
) -> list[OperationStep]:
    found = False
    updated: list[OperationStep] = []
    for step in steps:
        if step.key == step_key:
            found = True
            if step.status != "pending":
                raise OperationStateError(f"Operation step {step_key!r} is not pending.")
            updated.append(step.model_copy(update={"status": "running", "started_at": now}))
        else:
            updated.append(step.model_copy(deep=True))
    if not found:
        raise OperationStateError(f"Operation step {step_key!r} does not exist.")
    return updated


def _complete_step(
    steps: list[OperationStep],
    *,
    step_key: str,
    status: Literal["succeeded", "failed"],
    now: dt.datetime,
    message: str | None,
) -> list[OperationStep]:
    updated: list[OperationStep] = []
    for step in steps:
        if step.key == step_key:
            if step.status != "running":
                raise OperationStateError(f"Operation step {step_key!r} is not running.")
            updated.append(
                step.model_copy(update={"status": status, "message": message, "completed_at": now})
            )
        else:
            updated.append(step.model_copy(deep=True))
    return updated


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


__all__ = [
    "InMemoryOperationStore",
    "ObservableOperation",
    "OperationError",
    "OperationNotFoundError",
    "OperationStateError",
    "OperationStatus",
    "OperationStep",
    "OperationStepStatus",
]
