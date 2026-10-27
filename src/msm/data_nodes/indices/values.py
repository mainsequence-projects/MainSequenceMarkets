"""Deprecated alias of ``msm.time_index.indices.values``.

Removed in ms-markets 4.0 (ADR 0048).
"""

from msm._deprecated_imports import alias_module

__getattr__, __dir__ = alias_module(__name__, "msm.time_index.indices.values")
