"""Generic stateful portfolio rebalance execution."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.data_nodes.utils.time import normalize_datetime64_ns_utc
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy import (
    RebalanceInputContract,
    RebalanceStrategyBase,
)

from ..base import (
    AssetScopedPortfolioCanonicalDataNode,
    OutputTable,
    _empty_flat_frame,
    _require_columns,
    _reset_frame_index,
)
from ..constants import PORTFOLIO_IDENTIFIER
from ..portfolio_identity import get_or_create_portfolio
from .storage import PortfolioRebalanceStateStorage
from .temporal import fetch_asset_observations, normalize_asset_observations


class PortfolioRebalance(AssetScopedPortfolioCanonicalDataNode):
    """Persist strategy-owned target activation and partial execution state."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    def __init__(
        self,
        config=None,
        *args,
        portfolio_configuration: Any | None = None,
        namespace: str | None = None,
        **kwargs,
    ):
        self._portfolio_configuration = portfolio_configuration
        self._state_frame: pd.DataFrame | None = None
        super().__init__(config, *args, namespace=namespace, **kwargs)
        if portfolio_configuration is not None:
            self.set_portfolio_configuration(portfolio_configuration)

    def set_portfolio_configuration(
        self,
        portfolio_configuration: Any,
        *,
        portfolio_identifier: str | None = None,
        portfolio: Any | None = None,
        portfolio_resolver: Any | None = None,
    ) -> PortfolioRebalance:
        self._rehash_for_portfolio_configuration(portfolio_configuration)
        backtesting = (
            portfolio_configuration.portfolio_build_configuration.backtesting_weights_configuration
        )
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_identifier = portfolio_identifier
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self.signal_weights = backtesting.signal_weights_instance
        self.rebalance_strategy: RebalanceStrategyBase = backtesting.rebalance_strategy_instance
        return self

    def set_rebalance_state_frame(
        self,
        state_frame: pd.DataFrame,
        *,
        portfolio_identifier: str,
    ) -> PortfolioRebalance:
        """Attach direct canonical state rows for storage-only workflows."""
        self._state_frame = state_frame
        self._portfolio_identifier = portfolio_identifier
        return self

    def _rehash_for_portfolio_configuration(self, portfolio_configuration: Any) -> None:
        build_configuration = {
            "config": self.config,
            "portfolio_configuration": portfolio_configuration,
        }
        if self.hash_namespace:
            build_configuration["hash_namespace"] = self.hash_namespace
        self.build_configuration = build_configuration
        self._initialize_configuration(init_kwargs=build_configuration)

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        if getattr(self, "_portfolio_configuration", None) is None:
            return {}
        declared = self.rebalance_strategy.declared_dependencies()
        if "signal_weights" in declared:
            raise ValueError("'signal_weights' is reserved by PortfolioRebalance.")
        invalid = {
            name: dependency
            for name, dependency in declared.items()
            if not isinstance(dependency, (TimeIndexTableUpdater, TimeIndexTableRef))
        }
        if invalid:
            raise TypeError(
                "Rebalance dependencies must be TimeIndexTableUpdater or "
                "TimeIndexTableRef instances: " + ", ".join(sorted(invalid))
            )
        return {"signal_weights": self.signal_weights, **dict(sorted(declared.items()))}

    def update(self) -> pd.DataFrame:
        if getattr(self, "_portfolio_configuration", None) is None:
            if self._state_frame is None:
                return self.get_canonical_frame()
            return normalize_rebalance_state_frame(
                self._state_frame,
                portfolio_identifier=self._resolve_portfolio_identifier(),
                output_table=self.output_table,
            )

        latest = self._latest_transition_time_index_value()
        start, end = self._execution_window(latest)
        assets = self._required_asset_identifiers()
        signals = self._signal_observations(start=start, end=end, assets=assets)
        if not assets and not signals.empty:
            assets = (
                signals.index.get_level_values(ASSET_IDENTIFIER_DIMENSION)
                .astype(str)
                .unique()
                .tolist()
            )
        observed_inputs = self._observed_inputs(start=start, end=end, assets=assets)
        previous_state = self._previous_state(latest)
        transitions = self.rebalance_strategy.build_transitions(
            start=start,
            end=end,
            signal_observations=signals,
            observed_inputs=observed_inputs,
            previous_state=previous_state,
        )
        return normalize_rebalance_state_frame(
            transitions,
            portfolio_identifier=self._resolve_portfolio_identifier(),
            output_table=self.output_table,
        )

    def _execution_window(self, latest: Any | None) -> tuple[Any, Any]:
        start: Any = self.OFFSET_START
        if latest is not None:
            start = pd.Timestamp(latest) + pd.Timedelta(1, unit="ns")
        end: Any = pd.Timestamp.now(tz="UTC")
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, pd.Timestamp(start) + pd.Timedelta(maximum_window))
        return start, end

    def _latest_transition_time_index_value(self) -> Any | None:
        statistics = getattr(self, "update_statistics", None)
        if statistics is None:
            return None
        progress = statistics.index_progress
        portfolio_identifier = self._resolve_portfolio_identifier()
        if isinstance(progress, dict):
            value = progress.get(portfolio_identifier)
            if isinstance(value, dict):
                return self._max_in_nested_values(value)
            if value is not None:
                return value
        return statistics.max_time_index_value

    def _required_asset_identifiers(self) -> list[str]:
        assets = self.signal_weights.get_asset_list() or []
        return list(dict.fromkeys(str(self._asset_unique_identifier(asset)) for asset in assets))

    def _signal_observations(
        self,
        *,
        start: Any,
        end: Any,
        assets: list[str],
    ) -> pd.DataFrame:
        filters = {"signal_uid": [self.signal_weights.signal_uid]}
        if assets:
            window, seed = fetch_asset_observations(
                self.signal_weights,
                start=start,
                end=end,
                asset_identifiers=assets,
                extra_dimension_filters=filters,
            )
            frame = pd.concat([seed, window]).sort_index()
        else:
            frame = normalize_asset_observations(
                self.signal_weights.get_df_between_dates(
                    start_date=start,
                    end_date=end,
                    great_or_equal=True,
                    less_or_equal=True,
                    dimension_filters=filters,
                )
            )
        if frame.empty:
            return frame
        flat = frame.reset_index().sort_values("time_index", kind="stable")
        return (
            flat.drop_duplicates(
                subset=["time_index", ASSET_IDENTIFIER_DIMENSION],
                keep="last",
            )
            .set_index(["time_index", ASSET_IDENTIFIER_DIMENSION])
            .sort_index()
        )

    def _observed_inputs(
        self,
        *,
        start: Any,
        end: Any,
        assets: list[str],
    ) -> dict[str, pd.DataFrame]:
        dependencies = self.rebalance_strategy.declared_dependencies()
        contracts = self.rebalance_strategy.required_input_contract()
        if set(dependencies) != set(contracts):
            raise ValueError(
                "Rebalance strategy dependency names and input-contract names must match."
            )
        result: dict[str, pd.DataFrame] = {}
        for name in sorted(dependencies):
            source_start, source_end = self.rebalance_strategy.dependency_window(name, start, end)
            contract = contracts[name]
            kwargs: dict[str, Any] = {
                "start_date": source_start,
                "end_date": source_end,
                "great_or_equal": True,
                "less_or_equal": True,
            }
            if contract.asset_scoped and assets:
                kwargs["dimension_filters"] = {ASSET_IDENTIFIER_DIMENSION: assets}
            frame = dependencies[name].get_df_between_dates(**kwargs)
            result[name] = normalize_rebalance_input(
                frame,
                dependency_name=name,
                contract=contract,
            )
        return result

    def _previous_state(self, latest: Any | None) -> pd.DataFrame | None:
        if latest is None:
            return None
        frame = self.get_df_between_dates(
            start_date=latest,
            end_date=latest,
            dimension_filters={PORTFOLIO_IDENTIFIER: [self._resolve_portfolio_identifier()]},
        )
        return None if frame is None or frame.empty else frame

    def _resolve_portfolio_identifier(self) -> str:
        explicit = getattr(self, "_portfolio_identifier", None)
        if explicit:
            return str(explicit)
        portfolio = getattr(self, "_portfolio", None)
        if getattr(portfolio, "unique_identifier", None):
            return str(portfolio.unique_identifier)
        configuration = getattr(self, "_portfolio_configuration", None)
        if configuration is not None:
            resolved = get_or_create_portfolio(
                configuration,
                portfolio_resolver=getattr(self, "_portfolio_resolver", None),
            )
            if getattr(resolved, "unique_identifier", None):
                return str(resolved.unique_identifier)
        raise ValueError(
            "PortfolioRebalance requires a portfolio identifier or resolvable "
            "portfolio configuration."
        )

    @classmethod
    def _required_output_table(cls) -> type[PortfolioRebalanceStateStorage]:
        return PortfolioRebalanceStateStorage


def normalize_rebalance_input(
    frame: pd.DataFrame | None,
    *,
    dependency_name: str,
    contract: RebalanceInputContract,
) -> pd.DataFrame:
    """Validate and deterministically consolidate one declared observed input."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    flat = frame.copy().reset_index()
    required = [*contract.index_names, *contract.required_columns]
    missing = [column for column in required if column not in flat.columns]
    if missing:
        raise ValueError(
            f"Rebalance dependency {dependency_name!r} is missing columns: " + ", ".join(missing)
        )
    flat["time_index"] = normalize_datetime64_ns_utc(flat["time_index"])
    for dimension in contract.index_names[1:]:
        flat[dimension] = flat[dimension].map(str)
    return (
        flat.sort_values(list(contract.index_names), kind="stable")
        .drop_duplicates(subset=list(contract.index_names), keep="last")
        .set_index(list(contract.index_names))
        .sort_index()
    )


def normalize_rebalance_state_frame(
    frame: pd.DataFrame,
    *,
    portfolio_identifier: str,
    output_table: OutputTable | None = None,
) -> pd.DataFrame:
    """Normalize strategy transitions into canonical rebalance-state rows."""
    required_columns = list(PortfolioRebalance._column_dtypes_map_for_storage(output_table))
    flat = _reset_frame_index(frame)
    if flat.empty:
        flat = _empty_flat_frame(column_names=required_columns)
    flat[PORTFOLIO_IDENTIFIER] = str(portfolio_identifier)
    _require_columns(
        flat,
        required_columns=required_columns,
        frame_name="PortfolioRebalance",
    )
    return PortfolioRebalance.validate_frame(
        flat[required_columns],
        output_table=output_table,
    )


__all__ = [
    "PortfolioRebalance",
    "normalize_rebalance_input",
    "normalize_rebalance_state_frame",
]
