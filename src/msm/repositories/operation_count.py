"""How many MetaTables operations a block of work sends (issue 94).

An operation is one execute-operation or execute-transaction call through
``msm.repositories.base``, whatever its statements; it is counted when it is sent, so a
refused one counts. Reads of the MetaTables catalog are not operations and are not counted.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass
class OperationCount:
    """The operations sent inside one `counting_operations` block."""

    operations: int = 0


_current: ContextVar[OperationCount | None] = ContextVar("msm_operation_count", default=None)


@contextmanager
def counting_operations() -> Iterator[OperationCount]:
    """Count the operations sent inside the block, by the threads it hands work to as well.

    A thread counts when it runs in a copy of the block's context, as FastAPI's route
    threads do: they find the same count and add to it.
    """

    count = OperationCount()
    token = _current.set(count)
    try:
        yield count
    finally:
        _current.reset(token)


def count_operation() -> None:
    """Count one operation toward the current block, when there is one."""

    if (count := _current.get()) is not None:
        count.operations += 1


__all__ = ["OperationCount", "count_operation", "counting_operations"]
