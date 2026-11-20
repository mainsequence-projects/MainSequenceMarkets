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
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class ManagedRows:
    """A registry row class whose rows have a manager, and the column that names a row."""

    kind: str
    rows: type
    key_column: str


_managed_rows: dict[str, ManagedRows] = {}


def register_managed_rows(kind: str, rows: type, key_column: str) -> None:
    """Declare that ``rows`` has ``managed_by`` and ``assign_manager``.

    The package that defines the row class calls it when the class is defined, so this
    module names no row class of another package. ``kind`` is the name an operator uses
    for it, ``key_column`` the column an operator names a row by.
    """

    _managed_rows[kind] = ManagedRows(kind, rows, key_column)


def managed_rows() -> dict[str, ManagedRows]:
    """The managed row classes of the packages loaded in this process, by kind."""

    return dict(_managed_rows)


@dataclass(frozen=True)
class ManagerAssignment:
    """One registry row given a manager, or why it was not."""

    kind: str
    key: str
    uid: str | None
    previous: str | None
    managed_by: str
    assigned: bool
    detail: str = ""


def assign_managers(
    managed_by: str,
    *,
    keys: Mapping[str, Sequence[str]] | None = None,
    unmanaged: bool = False,
    dry_run: bool = True,
) -> list[ManagerAssignment]:
    """Make ``managed_by`` the manager of the named rows (ADR 0060, decision 9).

    ``keys`` maps a kind (see ``managed_rows``) to the rows of that kind, each named by
    its key column; ``unmanaged`` adds every row of every loaded kind that has no manager.
    ``dry_run`` lists the rows and changes nothing. Runs only when a person runs it
    (``msm registry assign-manager``). A kind whose package is not loaded is refused.
    """

    assigned_principal = validate_principal(managed_by)
    kinds = managed_rows()
    named = {kind: list(values) for kind, values in (keys or {}).items() if values}
    unknown = sorted(set(named) - set(kinds))
    if unknown:
        raise ValueError(
            f"No loaded package serves {', '.join(unknown)} rows; loaded kinds: "
            f"{', '.join(sorted(kinds)) or 'none'}. Load the package that defines them first."
        )
    found: dict[tuple[str, str], Any] = {}
    for kind, values in named.items():
        managed = kinds[kind]
        for key in values:
            matches = managed.rows.filter(limit=1, **{managed.key_column: key})
            found[(kind, str(key))] = matches[0] if matches else None
    if unmanaged:
        for kind, managed in kinds.items():
            for row in _rows_without_manager(managed.rows):
                found.setdefault((kind, str(getattr(row, managed.key_column))), row)
    assignments: list[ManagerAssignment] = []
    for (kind, key), row in found.items():
        if row is None:
            assignments.append(
                ManagerAssignment(kind, key, None, None, assigned_principal, False, "not found")
            )
            continue
        assigned = False
        if not dry_run:
            kinds[kind].rows.assign_manager(row.uid, assigned_principal)
            assigned = True
        assignments.append(
            ManagerAssignment(
                kind,
                key,
                str(row.uid),
                row.managed_by,
                assigned_principal,
                assigned,
                "dry run" if dry_run else "",
            )
        )
    return assignments


def _rows_without_manager(rows: type) -> list[Any]:
    found: list[Any] = []
    offset = 0
    while True:
        page = rows.filter(limit=500, offset=offset)
        found.extend(row for row in page if not row.managed_by)
        if len(page) < 500:
            return found
        offset += 500


__all__ = [
    "MANAGED_BY",
    "ManagedRows",
    "Manager",
    "ManagerAssignment",
    "PRINCIPAL_KINDS",
    "acting_manager",
    "acting_manager_scope",
    "assign_managers",
    "managed_rows",
    "manager_for_new_row",
    "manager_refusal",
    "principal",
    "refuse_managed_by",
    "register_managed_rows",
    "require_assigning_admin",
    "require_manager",
    "validate_principal",
]
