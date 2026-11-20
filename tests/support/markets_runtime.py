"""A stand-in for ``msm.bootstrap.resolve_runtime`` that resolves its models first.

Every test that replaces ``resolve_runtime`` goes through ``serve_runtime``, so the
models a row operation names are resolved by the resolver the real runtime uses. A
table the deployed runtime cannot find fails the test that reaches it (#103).
"""

from __future__ import annotations

from collections.abc import Callable
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
