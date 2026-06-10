from __future__ import annotations

from typing import Any

import pandas as pd

from ..base import (
    AssetScopedPortfolioCanonicalDataNode,
    StorageTable,
    _empty_flat_frame,
    _require_columns,
    _reset_frame_index,
)
from ..constants import (
    PORTFOLIO_IDENTIFIER,
    PORTFOLIO_WEIGHT_SOURCE_COLUMN_ALIASES,
)
from ..metadata import emit_portfolio_metadata, extract_portfolio_description
from ..portfolio_identity import (
    canonical_portfolio_configuration,
    compute_portfolio_configuration_hash,
    get_or_create_portfolio,
)
from .storage import PortfolioWeightsStorage


class PortfolioWeights(AssetScopedPortfolioCanonicalDataNode):
    """Canonical DataNode for executed Portfolios portfolio weights."""

    def set_weights_frame(
        self,
        weights_frame: pd.DataFrame,
        *,
        portfolio_identifier: str | None = None,
        portfolio_configuration: Any | None = None,
        portfolio: Any | None = None,
        portfolio_resolver: Any | None = None,
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfolioWeights:
        """Attach runtime calculation inputs without changing table identity."""
        self._weights_frame = weights_frame
        self._portfolio_identifier = portfolio_identifier
        self._portfolio_configuration = portfolio_configuration
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        return self

    def update(self) -> pd.DataFrame:
        frame = self.validate_frame(
            self._calculate_weights(),
            storage_table=self.storage_table,
        )
        self._upsert_portfolio_metadata_if_available(frame)
        return frame

    def _calculate_weights(self) -> pd.DataFrame:
        weights_frame = getattr(self, "_weights_frame", None)
        if weights_frame is None:
            return self.get_canonical_frame()

        return normalize_portfolio_weights_frame(
            weights_frame,
            portfolio_identifier=(self._resolve_portfolio_identifier()),
            storage_table=self.storage_table,
        )

    def _resolve_portfolio_identifier(self) -> str:
        explicit_identifier = getattr(
            self,
            "_portfolio_identifier",
            None,
        )
        if explicit_identifier:
            return str(explicit_identifier)

        portfolio = getattr(self, "_portfolio", None)
        portfolio_identifier = getattr(
            portfolio,
            "unique_identifier",
            None,
        )
        if portfolio_identifier:
            return str(portfolio_identifier)

        portfolio_configuration = getattr(self, "_portfolio_configuration", None)
        if portfolio_configuration is not None:
            resolved_portfolio = get_or_create_portfolio(
                portfolio_configuration,
                portfolio_resolver=getattr(self, "_portfolio_resolver", None),
            )
            resolved_identifier = getattr(resolved_portfolio, "unique_identifier", None)
            if resolved_identifier:
                return str(resolved_identifier)

        raise ValueError(
            "PortfolioWeights requires a portfolio_identifier, a Portfolio row, "
            "or a portfolio_configuration that can resolve one before canonical "
            "rows can be written."
        )

    def _upsert_portfolio_metadata_if_available(self, frame: pd.DataFrame) -> None:
        portfolio_configuration = getattr(self, "_portfolio_configuration", None)
        portfolio_description = getattr(self, "_portfolio_description", None)
        if portfolio_configuration is None and portfolio_description is None:
            return

        flat = frame.reset_index()
        if flat.empty or PORTFOLIO_IDENTIFIER not in flat.columns:
            return
        unique_identifier = flat[PORTFOLIO_IDENTIFIER].iloc[0]
        if unique_identifier in (None, ""):
            return

        if (
            portfolio_description is None
            and extract_portfolio_description(portfolio_configuration) is None
        ):
            return

        emit_portfolio_metadata(
            unique_identifier=str(unique_identifier),
            description=portfolio_description
            or extract_portfolio_description(portfolio_configuration),
            updater=getattr(self, "_portfolio_metadata_updater", None),
        )

    @staticmethod
    def canonical_portfolio_configuration(
        portfolio_configuration: Any,
    ) -> dict[str, Any]:
        return canonical_portfolio_configuration(portfolio_configuration)

    @staticmethod
    def compute_portfolio_configuration_hash(
        portfolio_configuration: Any,
    ) -> str:
        return compute_portfolio_configuration_hash(portfolio_configuration)

    @staticmethod
    def normalize_weights_frame(
        weights_frame: pd.DataFrame,
        *,
        portfolio_identifier: str,
    ) -> pd.DataFrame:
        return normalize_portfolio_weights_frame(
            weights_frame,
            portfolio_identifier=(portfolio_identifier),
        )

    @classmethod
    def _required_storage_table(cls) -> type[PortfolioWeightsStorage]:
        return PortfolioWeightsStorage


def normalize_portfolio_weights_frame(
    weights_frame: pd.DataFrame,
    *,
    portfolio_identifier: str,
    storage_table: StorageTable | None = None,
) -> pd.DataFrame:
    """Normalize postprocessed Portfolios weights into canonical PortfolioWeights rows."""
    required_columns = list(PortfolioWeights._column_dtypes_map_for_storage(storage_table))
    flat = _reset_frame_index(weights_frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)

    flat = flat.rename(columns=PORTFOLIO_WEIGHT_SOURCE_COLUMN_ALIASES)
    flat[PORTFOLIO_IDENTIFIER] = str(portfolio_identifier)

    _require_columns(
        flat,
        required_columns=required_columns,
        frame_name="PortfolioWeights",
    )
    return PortfolioWeights.validate_frame(
        flat[required_columns],
        storage_table=storage_table,
    )
