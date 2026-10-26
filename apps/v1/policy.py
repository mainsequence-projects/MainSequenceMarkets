"""Who may trigger a registry write (ADR 0047, decision 3).

Writes run as the Markets workload; this policy decides which callers may
trigger them. ``registry_write`` calls ``authorize_registry_write`` before every
service that creates, updates or deletes a registry row.

The rule, for the acting identity of the request:

- no identity (Markets' own Jobs, scripts and direct service calls): allowed;
- a requester-bound call: allowed, because the person is the actor;
- an Organization admin: allowed;
- a caller listed for the resource in the allow-list: allowed;
- any other person: allowed, as before this policy;
- any other workload identity, that is an application: refused with
  ``RegistryWriteForbidden`` (HTTP 403).

The allow-list is the Main Sequence Constant ``MARKETS_REGISTRY_WRITERS`` in the
Markets deployment's Environment. Its value is a JSON object that maps a
registry resource, as named by ``registry_write`` (``asset``, ``portfolio``,
``index`` ...), or ``"*"`` for every resource, to the User uids of the
applications allowed to write it::

    {"asset": ["<workload user uid>"], "*": ["<workload user uid>"]}

A missing constant means no application may write. A constant that is not such
an object fails closed. The Markets workload needs ``reader`` on the constant;
the SDK caches its value for ten minutes, so an edit takes effect within that
time.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

REGISTRY_WRITERS_CONSTANT = "MARKETS_REGISTRY_WRITERS"
ALL_RESOURCES = "*"
IDENTITY_TYPE_TTL_SECONDS = 600.0

IdentityType = Literal["human", "workload"]


class RegistryWriteForbidden(PermissionError):
    """The acting application is not allowed to write this registry resource."""


class RegistryWritePolicyError(RuntimeError):
    """The policy could not be evaluated, so the write is refused."""


@dataclass(frozen=True)
class RegistryWriterPolicy:
    """The parsed allow-list: resource name to the User uids allowed to write it."""

    writers: Mapping[str, frozenset[str]]

    def allows(self, resource: str, uid: str) -> bool:
        return uid in self.writers.get(resource, frozenset()) or uid in self.writers.get(
            ALL_RESOURCES, frozenset()
        )

    @classmethod
    def from_value(cls, value: Any) -> RegistryWriterPolicy:
        """Parse the constant's value, a JSON object or its decoded mapping."""

        if value in (None, ""):
            return cls(writers={})
        if isinstance(value, (str, bytes)):
            try:
                value = json.loads(value)
            except ValueError as exc:
                raise RegistryWritePolicyError(
                    f"{REGISTRY_WRITERS_CONSTANT} is not valid JSON: {exc}"
                ) from exc
        if not isinstance(value, Mapping):
            raise RegistryWritePolicyError(
                f"{REGISTRY_WRITERS_CONSTANT} must map registry resources to lists of User uids."
            )
        writers: dict[str, frozenset[str]] = {}
        for resource, uids in value.items():
            if isinstance(uids, (str, bytes)) or not isinstance(uids, Iterable):
                raise RegistryWritePolicyError(
                    f"{REGISTRY_WRITERS_CONSTANT}[{resource!r}] must be a list of User uids."
                )
            writers[str(resource)] = frozenset(str(uid).strip() for uid in uids if str(uid).strip())
        return cls(writers=writers)


def load_registry_writer_policy() -> RegistryWriterPolicy:
    """Read the allow-list constant from the Markets deployment's Environment."""

    from mainsequence.client import Constant
    from mainsequence.client.utils import DoesNotExist

    try:
        value = Constant.get_value(REGISTRY_WRITERS_CONSTANT)
    except DoesNotExist:
        return RegistryWriterPolicy(writers={})
    except Exception as exc:
        raise RegistryWritePolicyError(
            f"Could not read {REGISTRY_WRITERS_CONSTANT}: {type(exc).__name__}: {exc}"
        ) from exc
    return RegistryWriterPolicy.from_value(value)


_identity_types: dict[str, tuple[IdentityType, float]] = {}
_identity_types_lock = threading.Lock()


def resolve_identity_type(uid: str) -> IdentityType:
    """Return whether ``uid`` is a person (``human``) or an application (``workload``).

    The caller assertion does not say, so the User is read once and cached for
    ``IDENTITY_TYPE_TTL_SECONDS``.
    """

    now = time.monotonic()
    with _identity_types_lock:
        cached = _identity_types.get(uid)
        if cached is not None and now - cached[1] < IDENTITY_TYPE_TTL_SECONDS:
            return cached[0]

    from mainsequence.client.models_user import User

    try:
        user = User.get_by_uid(uid)
    except Exception as exc:
        raise RegistryWritePolicyError(
            f"Could not read User {uid} to check the registry write policy: "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    identity_type: IdentityType = (
        "workload" if str(getattr(user, "identity_type", "") or "").lower() == "workload" else "human"
    )
    with _identity_types_lock:
        _identity_types[uid] = (identity_type, now)
    return identity_type


def authorize_registry_write(resource: str, action: str, identity: Any) -> None:
    """Raise ``RegistryWriteForbidden`` when the acting identity may not write ``resource``."""

    if identity is None or identity.is_requester or identity.is_organization_admin:
        return
    policy = load_registry_writer_policy()
    if policy.allows(resource, identity.uid):
        return
    if resolve_identity_type(identity.uid) != "workload":
        return
    raise RegistryWriteForbidden(
        f"Application {identity.username or identity.uid} may not {action} {resource} rows. "
        f"An Environment admin adds its User uid under {resource!r} in the "
        f"{REGISTRY_WRITERS_CONSTANT} constant (ADR 0047)."
    )


def clear_identity_type_cache() -> None:
    with _identity_types_lock:
        _identity_types.clear()


__all__ = [
    "ALL_RESOURCES",
    "REGISTRY_WRITERS_CONSTANT",
    "RegistryWriteForbidden",
    "RegistryWritePolicyError",
    "RegistryWriterPolicy",
    "authorize_registry_write",
    "clear_identity_type_cache",
    "load_registry_writer_policy",
    "resolve_identity_type",
]
