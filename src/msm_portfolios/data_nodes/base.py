"""Deprecated alias of ``msm_portfolios.time_index.base``.

Removed in ms-markets 4.0 (ADR 0048).
"""

from msm._deprecated_imports import alias_module

__getattr__, __dir__ = alias_module(__name__, "msm_portfolios.time_index.base")
