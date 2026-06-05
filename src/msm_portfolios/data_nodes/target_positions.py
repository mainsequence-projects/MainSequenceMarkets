from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import pandas as pd

from .base import PortfolioCanonicalDataNode, PortfolioCanonicalDataNodeConfiguration
from .storage import TargetPositionsStorage

from msm_portfolios.services.target_positions import (
    build_target_positions_frame as build_target_positions_service_frame,
    validate_target_positions_frame,
)


class TargetPositionsDataNodeConfiguration(PortfolioCanonicalDataNodeConfiguration):
    """Update-scoped configuration for account target-position exposure rows."""


class TargetPositions(PortfolioCanonicalDataNode):
    """DataNode users can subclass to import account target-position exposures."""

    @classmethod
    def default_config(cls) -> TargetPositionsDataNodeConfiguration:
        return cls._validate_config(TargetPositionsDataNodeConfiguration())

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> TargetPositionsDataNodeConfiguration:
        if not isinstance(config, TargetPositionsDataNodeConfiguration):
            raise TypeError(f"{cls.__name__} requires a TargetPositionsDataNodeConfiguration.")
        return config

    @classmethod
    def _required_storage_table(cls) -> type[TargetPositionsStorage]:
        return TargetPositionsStorage

    def update(self) -> pd.DataFrame:
        return validate_target_positions_frame(self.get_target_positions_frame())

    def set_frame(self, frame: pd.DataFrame) -> TargetPositions:
        self._target_positions_frame = frame
        return self

    def get_target_positions_frame(self) -> pd.DataFrame:
        frame = getattr(self, "_target_positions_frame", None)
        if frame is None:
            raise ValueError(
                f"{self.__class__.__name__} requires a real target-position frame. "
                "Call set_frame() or set_target_positions_frame() before update()."
            )
        return frame

    def build_target_positions_frame(
        self,
        *,
        target_positions_date: dt.datetime | str,
        position_set_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
    ) -> pd.DataFrame:
        return build_target_positions_service_frame(
            target_positions_date=target_positions_date,
            position_set_uid=position_set_uid,
            positions=positions,
        )

    def set_target_positions_frame(
        self,
        *,
        target_positions_date: dt.datetime | str,
        position_set_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
    ) -> TargetPositions:
        return self.set_frame(
            self.build_target_positions_frame(
                target_positions_date=target_positions_date,
                position_set_uid=position_set_uid,
                positions=positions,
            )
        )


__all__ = [
    "TargetPositions",
    "TargetPositionsDataNodeConfiguration",
]
