"""Compatibility alias for the ``msm_migrations:migration`` provider."""

from __future__ import annotations

from msm_migrations import MarketsAlembicVersion, migration


__all__ = [
    "MarketsAlembicVersion",
    "migration",
]
