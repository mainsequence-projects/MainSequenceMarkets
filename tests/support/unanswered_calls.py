"""MetaTables calls whose answer never arrives (MainSequenceMarkets#151).

The MetaTables client raises `metatables.TransferOutcomeUnknown` for an
``execute-transaction`` or ``execute-operation`` call that answers 5xx or loses its
connection: the call may have run or not. These stubs wrap the `sqlite_markets` harness's
own `MetaTable` methods, so a call either runs against the database or does not, and the
caller gets no answer either way.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace

from metatables import MetaTable, TransferOutcomeUnknown

UNANSWERED = "Server returned HTTP 502; confirm the outcome before resubmitting."


def unanswered_transaction(
    monkeypatch,
    *,
    committed: bool,
    before_raising: Callable[[], None] | None = None,
) -> SimpleNamespace:
    """The next transaction gets no answer; it commits only when ``committed``.

    ``before_raising`` runs after it, before the error is raised. Later transactions
    answer as usual. The result's ``sent`` counts the transactions sent.
    """

    run = MetaTable.execute_transaction
    state = SimpleNamespace(sent=0)

    def execute_transaction(cls, transaction, *, timeout=None):
        state.sent += 1
        if state.sent > 1:
            return run(transaction, timeout=timeout)
        if committed:
            run(transaction, timeout=timeout)
        if before_raising is not None:
            before_raising()
        raise TransferOutcomeUnknown(UNANSWERED)

    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(execute_transaction))
    return state


def unanswered_write(monkeypatch, *, committed: bool) -> None:
    """The next write sent as one statement gets no answer; it commits only when
    ``committed``. Selects and later writes answer as usual."""

    run = MetaTable.execute_operation
    state = SimpleNamespace(sent=0)

    def execute_operation(cls, operation, *, timeout=None):
        if operation.operation == "select":
            return run(operation, timeout=timeout)
        state.sent += 1
        if state.sent > 1:
            return run(operation, timeout=timeout)
        if committed:
            run(operation, timeout=timeout)
        raise TransferOutcomeUnknown(UNANSWERED)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(execute_operation))


def unanswered_reads(monkeypatch) -> None:
    """Every select from now on gets no answer; writes still answer."""

    run = MetaTable.execute_operation

    def execute_operation(cls, operation, *, timeout=None):
        if operation.operation == "select":
            raise TransferOutcomeUnknown(UNANSWERED)
        return run(operation, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(execute_operation))


__all__ = ["UNANSWERED", "unanswered_reads", "unanswered_transaction", "unanswered_write"]
