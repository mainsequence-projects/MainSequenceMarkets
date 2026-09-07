from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd
import pytz

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater

from ..base import (
    AssetScopedPortfolioCanonicalDataNode,
    OutputTable,
    _empty_flat_frame,
    _require_columns,
    _reset_frame_index,
)
from ..constants import (
    ASSET_IDENTIFIER,
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
from .temporal import (
    align_asset_observations,
    fetch_asset_observations,
    normalize_asset_observations,
    utc_index,
)


class PortfolioWeights(AssetScopedPortfolioCanonicalDataNode):
    """Execution/rebalance updater for canonical portfolio weights."""

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
        portfolio_description: str | None = None,
        metadata_updater: Any | None = None,
    ) -> PortfolioWeights:
        """Attach the hash-bearing execution contract and runtime portfolio identity."""
        self._rehash_for_portfolio_configuration(portfolio_configuration)
        build = portfolio_configuration.portfolio_build_configuration
        backtesting = build.backtesting_weights_configuration
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_identifier = portfolio_identifier
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self._portfolio_description = portfolio_description
        self._portfolio_metadata_updater = metadata_updater
        self.signal_weights = backtesting.signal_weights_instance
        self.rebalancer = backtesting.rebalance_strategy_instance
        self.execution_valuation_source = build.valuation_source_instance
        self.valuation_column = str(build.valuation_column)
        self.valuation_alignment_policy = build.valuation_alignment_policy
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
        if getattr(self, "_portfolio_configuration", None) is not None:
            raw_frame = self._calculate_executed_weights()
            frame = normalize_portfolio_weights_frame(
                raw_frame,
                portfolio_identifier=self._resolve_portfolio_identifier(),
                output_table=self.output_table,
            )
            self._upsert_portfolio_metadata_if_available(frame)
            return frame

        frame = self.validate_frame(
            self._calculate_weights(),
            output_table=self.output_table,
        )
        self._upsert_portfolio_metadata_if_available(frame)
        return frame

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        if getattr(self, "_portfolio_configuration", None) is None:
            return {}
        return {
            "signal_weights": self.signal_weights,
            "execution_valuations": self.execution_valuation_source,
        }

    def _calculate_executed_weights(self) -> pd.DataFrame:
        latest_execution = self._latest_execution_time_index_value()
        start, end = self._execution_window(latest_execution)
        assets = self._required_asset_identifiers()
        signal_observations = self._signal_observations(start=start, end=end)
        if not assets and not signal_observations.empty:
            assets = (
                signal_observations.index.get_level_values(ASSET_IDENTIFIER)
                .astype(str)
                .unique()
                .tolist()
            )
        signal_timestamps = (
            utc_index(signal_observations.index.get_level_values("time_index"))
            if not signal_observations.empty
            else pd.DatetimeIndex([], tz="UTC", name="time_index")
        )
        execution_index = self.rebalancer.execution_timestamps(
            start,
            end,
            signal_timestamps=signal_timestamps,
        )
        if latest_execution is not None:
            execution_index = execution_index[execution_index > pd.Timestamp(latest_execution)]
        if len(execution_index) == 0:
            return pd.DataFrame()

        if self.rebalancer.timing_mode == "signal_time":
            signal_weights = self._pivot_signal_observations(signal_observations).reindex(
                execution_index
            )
        else:
            signal_weights = self.signal_weights.interpolate_index(execution_index)
        signal_weights = signal_weights.dropna(how="all")
        if signal_weights.empty:
            return pd.DataFrame()
        execution_index = utc_index(signal_weights.index)

        valuation_window, valuation_seed = fetch_asset_observations(
            self.execution_valuation_source,
            start=start,
            end=end,
            asset_identifiers=assets,
        )
        all_valuations = pd.concat([valuation_seed, valuation_window]).sort_index()
        execution_index = self._drop_precoverage_events(
            execution_index,
            observations=all_valuations,
            asset_identifiers=assets,
        )
        if len(execution_index) == 0:
            return pd.DataFrame()
        signal_weights = signal_weights.reindex(execution_index).dropna(how="all")

        value_columns = [self.valuation_column]
        if "volume" in all_valuations.columns:
            value_columns.append("volume")
        aligned_valuations = align_asset_observations(
            all_valuations,
            target_index=execution_index,
            asset_identifiers=assets,
            value_columns=value_columns,
            maximum_staleness=self.valuation_alignment_policy.maximum_staleness,
            fail_on_missing_values=self.valuation_alignment_policy.fail_on_missing_values,
        )
        if aligned_valuations.empty:
            return pd.DataFrame()
        eligible_execution_times = (
            aligned_valuations[self.valuation_column]
            .unstack(ASSET_IDENTIFIER)
            .reindex(columns=assets)
            .notna()
            .all(axis=1)
        )
        execution_index = utc_index(eligible_execution_times[eligible_execution_times].index)
        if len(execution_index) == 0:
            return pd.DataFrame()
        signal_weights = signal_weights.reindex(execution_index)
        aligned_valuations = aligned_valuations[
            aligned_valuations.index.get_level_values("time_index").isin(execution_index)
        ]

        last_weights = self._last_executed_weights(latest_execution)
        calculated = self.rebalancer.apply_rebalance_logic(
            last_rebalance_weights=last_weights,
            signal_weights=signal_weights,
            valuations_df=aligned_valuations,
            valuation_column=self.valuation_column,
            start_date=start,
            end_date=end,
        )
        return self._postprocess_executed_weights(
            calculated,
            latest_execution=latest_execution,
        )

    def _execution_window(self, latest_execution: Any | None) -> tuple[datetime, datetime]:
        start = (
            pd.Timestamp(latest_execution).to_pydatetime()
            if latest_execution is not None
            else self.OFFSET_START
        )
        end = datetime.now(pytz.utc)
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, (pd.Timestamp(start) + pd.Timedelta(maximum_window)).to_pydatetime())
        return start, end

    def _latest_execution_time_index_value(self) -> Any | None:
        statistics = getattr(self, "update_statistics", None)
        if statistics is None:
            return None
        portfolio_identifier = self._resolve_portfolio_identifier()
        progress = statistics.index_progress
        if isinstance(progress, dict):
            value = progress.get(portfolio_identifier)
            if isinstance(value, dict):
                return (
                    value.get("max")
                    or value.get("time_index")
                    or self._max_in_nested_values(value)
                )
            if value is not None:
                return value
        return statistics.max_time_index_value

    def _required_asset_identifiers(self) -> list[str]:
        assets = self.signal_weights.get_asset_list() or []
        identifiers = [str(self._asset_unique_identifier(asset)) for asset in assets]
        override = self.signal_weights.get_asset_uid_to_override_portfolio_price()
        if override is not None:
            identifiers.append(str(override))
        return list(dict.fromkeys(identifiers))

    def _signal_observations(self, *, start: datetime, end: datetime) -> pd.DataFrame:
        frame = self.signal_weights.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={"signal_uid": [self.signal_weights.signal_uid]},
        )
        return normalize_asset_observations(frame)

    @staticmethod
    def _pivot_signal_observations(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame()
        return frame.reset_index().pivot(
            index="time_index",
            columns=ASSET_IDENTIFIER,
            values="signal_weight",
        )

    def _drop_precoverage_events(
        self,
        execution_index: pd.DatetimeIndex,
        *,
        observations: pd.DataFrame,
        asset_identifiers: list[str],
    ) -> pd.DatetimeIndex:
        if observations.empty:
            return pd.DatetimeIndex([], tz="UTC", name="time_index")
        first_by_asset = observations.reset_index().groupby(ASSET_IDENTIFIER)["time_index"].min()
        if any(asset not in first_by_asset for asset in asset_identifiers):
            if self.valuation_alignment_policy.fail_on_missing_values:
                missing = sorted(set(asset_identifiers) - set(first_by_asset.index.astype(str)))
                raise ValueError(
                    "Execution valuation source is missing required assets: " + ", ".join(missing)
                )
            return pd.DatetimeIndex([], tz="UTC", name="time_index")
        first_complete_coverage = max(first_by_asset.loc[asset] for asset in asset_identifiers)
        return execution_index[execution_index >= first_complete_coverage]

    def _last_executed_weights(self, latest_execution: Any | None) -> pd.DataFrame | None:
        if latest_execution is None:
            return None
        frame = self.get_df_between_dates(
            start_date=latest_execution,
            end_date=latest_execution,
            dimension_filters={
                PORTFOLIO_IDENTIFIER: [self._resolve_portfolio_identifier()],
            },
        )
        if frame is None or frame.empty:
            return None
        frame = frame.copy()
        if PORTFOLIO_IDENTIFIER in frame.index.names:
            frame = frame.droplevel(PORTFOLIO_IDENTIFIER)
        return frame.rename(columns={"weight": "weights_current"})

    @staticmethod
    def _postprocess_executed_weights(
        weights: pd.DataFrame,
        *,
        latest_execution: Any | None,
    ) -> pd.DataFrame:
        if weights is None or weights.empty:
            return pd.DataFrame()
        stacked = weights.stack(future_stack=True)
        required = ["weights_before", "weights_current", "price_current", "price_before"]
        missing = [column for column in required if column not in stacked.columns]
        if missing:
            raise ValueError("Executed weights are missing columns: " + ", ".join(missing))
        stacked = stacked.dropna(subset=["weights_current"])
        for column in (
            "weights_before",
            "price_current",
            "price_before",
            "volume_current",
            "volume_before",
        ):
            if column not in stacked.columns:
                stacked[column] = pd.NA
        stacked["weights_before"] = stacked["weights_before"].fillna(0.0)
        if latest_execution is not None:
            stacked = stacked[
                stacked.index.get_level_values("time_index") > pd.Timestamp(latest_execution)
            ]
        stacked.index.names = ["time_index", ASSET_IDENTIFIER]
        return stacked

    def _calculate_weights(self) -> pd.DataFrame:
        weights_frame = getattr(self, "_weights_frame", None)
        if weights_frame is None:
            return self.get_canonical_frame()

        return normalize_portfolio_weights_frame(
            weights_frame,
            portfolio_identifier=(self._resolve_portfolio_identifier()),
            output_table=self.output_table,
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
    def _required_output_table(cls) -> type[PortfolioWeightsStorage]:
        return PortfolioWeightsStorage


def normalize_portfolio_weights_frame(
    weights_frame: pd.DataFrame,
    *,
    portfolio_identifier: str,
    output_table: OutputTable | None = None,
) -> pd.DataFrame:
    """Normalize postprocessed Portfolios weights into canonical PortfolioWeights rows."""
    required_columns = list(PortfolioWeights._column_dtypes_map_for_storage(output_table))
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
        output_table=output_table,
    )
