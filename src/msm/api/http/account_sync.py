"""Account sync contract shared by every venue connector.

A connector captures an account's holdings into ms-markets as one
``AccountHoldingsSet``. An application that holds accounts asks any connector
for that in the same way:

``POST /v1/accounts/{account_uid}/actions/sync``
    Takes no body. The connector answers with an ``AccountSyncOperation``:

    - ``200`` with a terminal operation (``succeeded`` or ``failed``) when it
      finishes the sync inside the request;
    - ``202`` with a ``queued`` operation when it queues the sync. The caller
      then polls ``GET /v1/operations/{operation_uid}``, which returns the same
      operation until it is terminal.

A sync that ran and failed is a ``failed`` operation carrying its ``error``.
A refused request, such as an unknown account or an account that is not the
caller's, is an HTTP error in the shared error contract (``ApiErrorResponse``),
not an operation.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from ._base import HttpContractModel
from .operations import ObservableOperation

ACCOUNT_SYNC_ACTION = "account_sync"
ACCOUNT_SYNC_PATH = "/v1/accounts/{account_uid}/actions/sync"
OPERATION_PATH = "/v1/operations/{operation_uid}"

_UID_PATTERN = r"^[0-9a-f-]{36}$"


class AccountSyncRequest(HttpContractModel):
    """The account one sync operation captures; the endpoint itself takes no body."""

    account_uid: str = Field(
        pattern=_UID_PATTERN,
        description="ms-markets `Account.uid` of the synced account.",
    )


class AccountSyncResult(HttpContractModel):
    """What a succeeded account sync published."""

    account_uid: str = Field(
        pattern=_UID_PATTERN,
        description="ms-markets `Account.uid` of the synced account.",
    )
    holdings_set_uid: str | None = Field(
        pattern=_UID_PATTERN,
        description=(
            "The `AccountHoldingsSet` the sync published, or `null` when it published none."
        ),
    )
    time_index: dt.datetime = Field(description="The holdings snapshot's time, in UTC.")
    holdings_rows: int = Field(ge=0, description="How many holding rows the snapshot has.")
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Anything one venue adds, such as `unresolved_symbols`. Callers never depend on it."
        ),
    )

    @field_validator("time_index")
    @classmethod
    def validate_utc_time_index(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("time_index must be timezone-aware.")
        return value.astimezone(dt.timezone.utc)


class AccountSyncOperation(ObservableOperation[AccountSyncRequest, AccountSyncResult]):
    """``ObservableOperation`` answered by ``POST /v1/accounts/{account_uid}/actions/sync``."""

    action: Literal["account_sync"] = ACCOUNT_SYNC_ACTION

    @model_validator(mode="after")
    def validate_account_sync_result(self) -> AccountSyncOperation:
        if self.status == "succeeded" and self.result is None:
            raise ValueError("A succeeded account sync must contain its AccountSyncResult.")
        if self.result is not None and self.result.account_uid != self.request.account_uid:
            raise ValueError("An account sync result must describe the requested account.")
        return self


__all__ = [
    "ACCOUNT_SYNC_ACTION",
    "ACCOUNT_SYNC_PATH",
    "OPERATION_PATH",
    "AccountSyncOperation",
    "AccountSyncRequest",
    "AccountSyncResult",
]
