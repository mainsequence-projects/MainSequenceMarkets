"""The one identity a Markets API request acts for (ADR 0047, decision 3).

Every handler and service authorizes against one identity: the requester on a
requester-bound call, the caller otherwise, never both. ``acting_identity()``
is the only place that choice is made. Services that create, update or delete
a registry row are wrapped with ``registry_write``, which resolves the acting
identity before the write and records it after a successful write in the API's
structured audit log (logger ``apps.v1.identity``). ``registry_write`` also binds
the acting manager of the write (ADR 0060): the principal a new ``Portfolio`` or
``SignalMetadata`` row records in ``managed_by``, and the one ``publish``,
``delete_after`` and the delete of such a row are checked against.

The requester is only present because the ``markets-api`` resource declares
``acts_for_requester: true`` in ``.mainsequence/workflows/ms-markets-api.yaml``;
a caller-bound call still returns the caller. Only an Organization admin can
enable that declaration: it takes effect only when the person who pushes the
workflow file is an Organization admin, and otherwise the resource fails before
it deploys.
"""

from __future__ import annotations

import functools
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from mainsequence.client.models_user import RequestIdentityError, RequestUserIdentity, User

from msm.api.managers import Manager, acting_manager_scope, principal

logger = logging.getLogger(__name__)

ActingIdentityKind = Literal["requester", "caller"]
_F = TypeVar("_F", bound=Callable[..., Any])


@dataclass(frozen=True)
class ActingIdentity:
    """The verified identity a request acts for, and which role it plays."""

    uid: str
    kind: ActingIdentityKind
    username: str | None = None
    is_organization_admin: bool = False

    @property
    def is_requester(self) -> bool:
        return self.kind == "requester"


def acting_identity() -> ActingIdentity | None:
    """Return the identity the current request acts for, or ``None`` outside a request.

    On a requester-bound call this is the person the calling application works
    for (``User.get_requester()``); otherwise it is the verified caller
    (``User.get_logged_user()``). The two are never combined. Outside an
    authenticated request, as in local scripts and unit tests that call a
    service directly, there is no identity and ``None`` is returned; use
    ``require_acting_identity()`` where a person is mandatory.
    """

    try:
        requester = User.get_requester()
    except RequestIdentityError:
        return None
    if requester is not None:
        return _acting_identity(requester, kind="requester")
    return _acting_identity(User.get_logged_user(), kind="caller")


def require_acting_identity() -> ActingIdentity:
    """Return the acting identity or raise ``RequestIdentityError`` outside a request."""

    identity = acting_identity()
    if identity is None:
        raise RequestIdentityError(
            "This operation needs an authenticated request; no caller or requester is bound."
        )
    return identity


def record_registry_write(
    action: str,
    *,
    resource: str,
    uid: Any = None,
    identity: ActingIdentity | None,
    details: Mapping[str, Any] | None = None,
) -> None:
    """Record who performed a registry write.

    The record names the acting identity (requester or caller), the resource,
    the action and the row uid when known. It is emitted at INFO on the
    ``apps.v1.identity`` logger with the same fields as ``extra`` so log
    pipelines can index them.
    """

    fields = {
        "resource": resource,
        "action": action,
        "uid": None if uid is None else str(uid),
        "actor_uid": identity.uid if identity else None,
        "actor_kind": identity.kind if identity else None,
        "actor_username": identity.username if identity else None,
        **dict(details or {}),
    }
    logger.info(
        "registry write %s %s uid=%s by %s %s",
        resource,
        action,
        fields["uid"],
        fields["actor_kind"] or "no-identity",
        fields["actor_uid"],
        extra=fields,
    )


def registry_write(resource: str, action: str) -> Callable[[_F], _F]:
    """Wrap a service that creates, updates or deletes registry rows.

    The wrapper resolves the acting identity before the service runs and, when
    the service returns without raising, records the write with the row uid
    taken from the ``uid`` keyword argument or from the result's ``uid``.
    """

    def decorate(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            identity = acting_identity()
            if identity is None:
                result = func(*args, **kwargs)
            else:
                with acting_manager_scope(lambda: acting_manager_of(identity)):
                    result = func(*args, **kwargs)
            record_registry_write(
                action,
                resource=resource,
                uid=_written_uid(result, kwargs),
                identity=identity,
            )
            return result

        wrapper.__registry_write__ = (resource, action)  # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorate


class _DirectoryUser(User):
    """A platform User row with the code repository branch of its workload.

    The platform returns ``code_repository_branch_uid`` on every workload row, next to
    ``job_uid``; the SDK's ``User`` does not declare it and would drop it. MetaTables
    reads the same field to admit a branch's workloads (its ADR 0029).
    """

    code_repository_branch_uid: str | None = None


_caller_principals: dict[str, str] = {}
_caller_principals_lock = threading.Lock()


def caller_principal(uid: str) -> str:
    """The ``managed_by`` principal of caller ``uid``: its branch, or the User itself.

    A workload User declared on a code repository branch is ``branch:<branch uid>``:
    every Job, release and Agent of one application in one Environment (an Environment
    is bound to one branch). Any other User, a person included, is ``user:<uid>``. The
    row is read as the caller, once per process: a User's identity type and branch
    never change. A failed read raises; it is never taken for "no branch".

    A request without a caller assertion, which is every request to an API in local
    mode, cannot read as the caller, and the platform's directory is not read for it
    as the application either: the caller is ``user:<uid>`` (#101). A local API writes
    to a local MetaTables, so that principal never meets a hosted ``branch:`` one. The
    Markets API serves no WebSocket route, the other request without an assertion.
    """

    with _caller_principals_lock:
        cached = _caller_principals.get(uid)
    if cached is not None:
        return cached
    try:
        user = _DirectoryUser.get_by_uid(uid, as_caller=True)
    except RequestIdentityError:
        # as_caller=True refuses before anything is sent: outside a request, on a
        # requester-bound one, and without a caller assertion. Its other two refusals
        # cannot happen here: this runs inside the request, so it has not ended, and a get
        # reads the platform's own address. get_requester() raises in the first case and
        # names the requester in the second, so only a missing assertion is answered
        # here. Not cached: the answer belongs to the request, not to the User.
        if User.get_requester() is not None:
            raise
        return principal("user", uid)
    branch = (
        getattr(user, "code_repository_branch_uid", None)
        if getattr(user, "identity_type", None) == "workload"
        else None
    )
    resolved = principal("branch", branch) if branch else principal("user", uid)
    with _caller_principals_lock:
        _caller_principals[uid] = resolved
    return resolved


def acting_manager_of(identity: ActingIdentity) -> Manager:
    """The manager an acting identity creates rows as and publishes as (ADR 0060).

    A requester is the person ``user:<uid>``; a caller is resolved by
    ``caller_principal``.
    """

    resolved = (
        principal("user", identity.uid)
        if identity.is_requester
        else caller_principal(identity.uid)
    )
    return Manager(principal=resolved, is_organization_admin=identity.is_organization_admin)


def _acting_identity(user: RequestUserIdentity | Any, *, kind: ActingIdentityKind) -> ActingIdentity:
    uid = getattr(user, "uid", None)
    if uid in (None, ""):
        raise RequestIdentityError("Authenticated request identity has no UID.")
    return ActingIdentity(
        uid=str(uid),
        kind=kind,
        username=getattr(user, "username", None),
        is_organization_admin=bool(getattr(user, "is_organization_admin", False)),
    )


def _written_uid(result: Any, kwargs: Mapping[str, Any]) -> Any:
    for key in ("uid", "definition_uid", "account_uid", "portfolio_uid", "calendar_uid"):
        if kwargs.get(key) not in (None, ""):
            return kwargs[key]
    if kwargs.get("uids"):
        return ",".join(str(item) for item in kwargs["uids"])
    if result is None or isinstance(result, (bool, int, str)):
        return None
    if isinstance(result, Mapping):
        return result.get("uid")
    return getattr(result, "uid", None)


__all__ = [
    "ActingIdentity",
    "ActingIdentityKind",
    "acting_identity",
    "acting_manager_of",
    "caller_principal",
    "record_registry_write",
    "registry_write",
    "require_acting_identity",
]
