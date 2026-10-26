"""The one identity a Markets API request acts for (ADR 0047, decision 3).

Every handler and service authorizes against one identity: the requester on a
requester-bound call, the caller otherwise, never both. ``acting_identity()``
is the only place that choice is made. Services that create, update or delete
a registry row are wrapped with ``registry_write``, which resolves the acting
identity, checks it against the registry write policy (``apps.v1.policy``)
before the write and records it after a successful write. No Markets
registry table has an author or owner column yet, so the record is the API's
structured audit log (logger ``apps.v1.identity``); when such a column exists
the same hook supplies the value.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, TypeVar

from mainsequence.client.models_user import RequestIdentityError, RequestUserIdentity, User

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

    The wrapper resolves the acting identity before the service runs, refuses
    the write with ``RegistryWriteForbidden`` when the registry write policy
    does not allow that identity, and, when the service returns without
    raising, records the write with the row uid taken from the ``uid`` keyword
    argument or from the result's ``uid``.
    """

    def decorate(func: _F) -> _F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            from apps.v1.policy import authorize_registry_write

            identity = acting_identity()
            authorize_registry_write(resource, action, identity)
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
    "record_registry_write",
    "registry_write",
    "require_acting_identity",
]
