"""Who manages a portfolio or a signal (ADR 0060, decision 4).

``Portfolio.managed_by`` and ``SignalMetadata.managed_by`` name the principal that
created the row: ``branch:<uid>`` for a workload of a code repository branch (one
application in one Environment), ``user:<uid>`` for a person or any other identity.
Only that principal publishes to the row's series, restates them or deletes the row;
an Organization admin may assign another one.

The Markets API binds the acting manager of each registry write with
``acting_manager_scope``; the library reads it here. Outside such a scope (the
``runtime`` backend in a script, a Job or a test) nothing is checked: that process
reaches the tables directly with its own MetaTables grants, so a check here would
protect nothing, and a row it creates has no manager until one is assigned.
"""

from __future__ import annotations

import contextlib
import re
import uuid
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from dataclasses import dataclass

MANAGED_BY = "managed_by"
"""The registry column that names a row's manager."""

PRINCIPAL_KINDS = ("branch", "user")
_PRINCIPAL = re.compile(r"^(branch|user):(.+)$")


@dataclass(frozen=True)
class Manager:
    """The principal a request acts as, for ``managed_by``, and whether it is an admin."""

    principal: str
    is_organization_admin: bool = False


@dataclass
class _Scope:
    resolve: Callable[[], Manager]
    manager: Manager | None = None

    def get(self) -> Manager:
        if self.manager is None:
            self.manager = self.resolve()
        return self.manager


_scope: ContextVar[_Scope | None] = ContextVar("msm_acting_manager", default=None)


@contextlib.contextmanager
def acting_manager_scope(resolve: Callable[[], Manager]) -> Iterator[None]:
    """Bind the acting manager of the enclosed calls; ``resolve`` runs once, when needed."""

    token = _scope.set(_Scope(resolve))
    try:
        yield
    finally:
        _scope.reset(token)


def acting_manager() -> Manager | None:
    """The bound acting manager, or ``None`` outside a Markets API write."""

    scope = _scope.get()
    return None if scope is None else scope.get()


def principal(kind: str, uid: uuid.UUID | str) -> str:
    """The ``managed_by`` value of a principal of ``kind`` (``branch`` or ``user``)."""

    if kind not in PRINCIPAL_KINDS:
        raise ValueError(f"A manager is a branch or a user, not {kind!r}.")
    return f"{kind}:{uuid.UUID(str(uid))}"


def validate_principal(value: str) -> str:
    """``value`` as a canonical ``branch:<uid>`` or ``user:<uid>``; raises ``ValueError``."""

    match = _PRINCIPAL.match(str(value or "").strip())
    if match is None:
        raise ValueError(f"managed_by must be 'branch:<uid>' or 'user:<uid>'; got {value!r}.")
    try:
        return principal(match.group(1), match.group(2))
    except ValueError as exc:
        raise ValueError(f"managed_by {value!r} does not name a UUID.") from exc


def manager_for_new_row() -> str | None:
    """The ``managed_by`` of a row created now: the acting manager, if one is bound."""

    manager = acting_manager()
    return None if manager is None else manager.principal


def manager_refusal(label: str, managed_by: str | None) -> str | None:
    """Why the acting manager may not publish to or delete ``label``; ``None`` when it may.

    Always ``None`` outside a Markets API write (see the module docstring).
    """

    manager = acting_manager()
    if manager is None:
        return None
    if managed_by in (None, ""):
        return (
            f"{label} has no manager, so nobody may publish to it or delete it. An "
            "Organization admin assigns one with assign_manager (msm registry assign-manager)."
        )
    if managed_by != manager.principal:
        return (
            f"{label} is managed by {managed_by}; the caller is {manager.principal}. Only "
            "its manager publishes to it or deletes it."
        )
    return None


def require_manager(label: str, managed_by: str | None) -> None:
    """Refuse, with ``PermissionError``, an acting manager that does not manage ``label``."""

    refusal = manager_refusal(label, managed_by)
    if refusal is not None:
        raise PermissionError(refusal)


def require_assigning_admin() -> None:
    """Refuse, with ``PermissionError``, an acting manager that is not an Organization admin."""

    manager = acting_manager()
    if manager is not None and not manager.is_organization_admin:
        raise PermissionError("Only an Organization admin assigns a manager.")


def refuse_managed_by(values: dict) -> dict:
    """Refuse ``managed_by`` in a caller's payload: Markets records it, a caller never sends it."""

    if MANAGED_BY in values:
        raise ValueError(
            "managed_by is recorded by Markets from the acting identity of the create call; "
            "an Organization admin changes it with assign_manager."
        )
    return values


__all__ = [
    "MANAGED_BY",
    "Manager",
    "PRINCIPAL_KINDS",
    "acting_manager",
    "acting_manager_scope",
    "manager_for_new_row",
    "manager_refusal",
    "principal",
    "refuse_managed_by",
    "require_assigning_admin",
    "require_manager",
    "validate_principal",
]
