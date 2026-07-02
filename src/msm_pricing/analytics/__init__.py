"""Pure-data analytics helpers for pricing workflows.

The analytics namespace is intentionally separate from `pricing_engine`.
Analytics helpers operate on caller-supplied arrays, pandas objects, or
already-computed metrics; they do not resolve Main Sequence backend rows,
publish DataNodes, or mutate pricing instruments.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

__all__ = ["spreads"]


def __getattr__(name: str) -> ModuleType:
    """Load analytics subpackages lazily without widening the top-level API."""
    if name != "spreads":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(".spreads", __name__)
    globals()[name] = module
    return module
