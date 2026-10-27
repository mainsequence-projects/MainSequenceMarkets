"""Deprecated alias of ``msm_pricing.time_index.curves.storage``.

Removed in ms-markets 4.0 (ADR 0048).
"""

from msm._deprecated_imports import alias_module

__getattr__, __dir__ = alias_module(__name__, "msm_pricing.time_index.curves.storage")
