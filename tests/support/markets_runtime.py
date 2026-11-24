"""The runtime a test gives ms-markets and the MetaTables client.

Every test that replaces ``resolve_runtime`` goes through ``serve_runtime``, so the
models a row operation names are resolved by the resolver the real runtime uses. A
table the deployed runtime cannot find fails the test that reaches it (#103).
``use_runtime_context`` gives the MetaTables client a runtime of the test's own.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from typing import Any


def serve_runtime(monkeypatch, answer: Callable[..., Any]) -> None:
    """Replace ``msm.bootstrap.resolve_runtime`` with ``answer``, after resolving its models.

    ``answer`` receives the call's keyword arguments, ``models`` included, and returns
    the runtime (or raises) as the test needs.
    """

    from msm.models.registration import resolve_markets_meta_table_models

    def resolve_runtime(*, models, **kwargs):
        resolve_markets_meta_table_models(models)
        return answer(models=models, **kwargs)

    monkeypatch.setattr("msm.bootstrap.resolve_runtime", resolve_runtime)


_RUNTIME_BLOCKS: list[ExitStack] = []


def use_runtime_context(runtime: Any) -> None:
    """Give the MetaTables client ``runtime`` for the rest of the test.

    Opens ``metatables.use_runtime_context(runtime)``: every runtime lookup, ms-markets'
    and the client's, and the session DataSource, answer it. The autouse fixture
    ``runtime_context_blocks`` (``tests/conftest.py``) closes it after the test.
    """

    import metatables

    block = ExitStack()
    block.enter_context(metatables.use_runtime_context(runtime))
    _RUNTIME_BLOCKS.append(block)


def close_runtime_contexts() -> None:
    """Close the runtime blocks the test opened, the last first."""

    while _RUNTIME_BLOCKS:
        _RUNTIME_BLOCKS.pop().close()
