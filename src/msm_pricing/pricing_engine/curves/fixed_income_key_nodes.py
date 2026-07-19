"""Shared typed fields for fixed-income curve calibration inputs."""

from __future__ import annotations

from pydantic import Field

from msm_pricing.data_nodes.curves.key_nodes import (
    CurveKeyNodeBase,
    CurveKeyNodeSourceReference,
)


class FixedIncomeCurveKeyNode(CurveKeyNodeBase):
    """Common quote and source fields for fixed-income helper key nodes."""

    instrument_type: str | None = Field(
        default=None,
        description="Optional fixed-income calibration instrument type.",
    )
    quote: float
    quote_type: str
    quote_unit: str
    quote_side: str | None = Field(default="mid")


__all__ = [
    "CurveKeyNodeSourceReference",
    "FixedIncomeCurveKeyNode",
]
