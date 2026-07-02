"""Scenario namespaces for pricing risk-factor workflows.

This package is intentionally domain-neutral. Concrete scenario families live
in subpackages such as :mod:`msm_pricing.scenarios.curves` so future equities,
volatility, credit, or commodity scenarios can use sibling namespaces instead
of a mixed catch-all module.
"""

from __future__ import annotations

__all__: list[str] = []
