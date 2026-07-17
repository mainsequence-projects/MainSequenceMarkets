"""Runtime dependency resolution for helper-based curve reconstruction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import QuantLib as ql


class MissingRateHelperDependencyError(LookupError):
    """Raised when a helper key node references an unresolved runtime dependency."""


class RateHelperRuntimeResolver(Protocol):
    """Resolve runtime QuantLib dependencies referenced by helper key nodes."""

    def resolve_yield_curve(
        self,
        identifier: str,
        node: Mapping[str, Any],
    ) -> ql.YieldTermStructureHandle:
        """Resolve a named curve dependency to a QuantLib curve handle."""

    def resolve_index(
        self,
        identifier: str,
        node: Mapping[str, Any],
    ) -> ql.IborIndex | ql.OvernightIndex:
        """Resolve a named index dependency to a QuantLib interest-rate index."""

    def resolve_overnight_index(
        self,
        identifier: str | None,
        node: Mapping[str, Any],
    ) -> ql.OvernightIndex:
        """Resolve an OIS helper overnight-index dependency."""


@dataclass(frozen=True, slots=True)
class StaticRateHelperRuntimeResolver:
    """Mapping-backed resolver for tests, examples, and adapter-owned contexts."""

    yield_curves: Mapping[str, ql.YieldTermStructureHandle] = field(default_factory=dict)
    indexes: Mapping[str, ql.IborIndex | ql.OvernightIndex] = field(default_factory=dict)
    overnight_indexes: Mapping[str, ql.OvernightIndex] = field(default_factory=dict)

    def resolve_yield_curve(
        self,
        identifier: str,
        node: Mapping[str, Any],
    ) -> ql.YieldTermStructureHandle:
        """Resolve a curve handle by exact identifier."""

        key = _required_identifier(identifier, field_name="curve identifier")
        try:
            return self.yield_curves[key]
        except KeyError as exc:
            raise MissingRateHelperDependencyError(
                f"Rate-helper key node requires unresolved curve dependency {key!r}."
            ) from exc

    def resolve_index(
        self,
        identifier: str,
        node: Mapping[str, Any],
    ) -> ql.IborIndex | ql.OvernightIndex:
        """Resolve an interest-rate index by exact identifier."""

        key = _required_identifier(identifier, field_name="index identifier")
        try:
            return self.indexes[key]
        except KeyError as exc:
            raise MissingRateHelperDependencyError(
                f"Rate-helper key node requires unresolved index dependency {key!r}."
            ) from exc

    def resolve_overnight_index(
        self,
        identifier: str | None,
        node: Mapping[str, Any],
    ) -> ql.OvernightIndex:
        """Resolve an overnight index by exact identifier."""

        key = _required_identifier(identifier, field_name="overnight index identifier")
        if key in self.overnight_indexes:
            return self.overnight_indexes[key]
        resolved = self.resolve_index(key, node)
        if not isinstance(resolved, ql.OvernightIndex):
            raise TypeError(
                f"Resolved index dependency {key!r} is not a QuantLib OvernightIndex."
            )
        return resolved


def _required_identifier(value: object, *, field_name: str) -> str:
    identifier = str(value or "").strip()
    if not identifier:
        raise MissingRateHelperDependencyError(f"Missing {field_name}.")
    return identifier


__all__ = [
    "MissingRateHelperDependencyError",
    "RateHelperRuntimeResolver",
    "StaticRateHelperRuntimeResolver",
]
