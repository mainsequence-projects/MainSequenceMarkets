"""Generic stateful portfolio rebalance execution."""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

import pandas as pd
import pytz
from pydantic import Field

from metatables import TimeIndexTableRef, TimeIndexTableUpdater
from msm.time_index.utils.time import normalize_datetime64_ns_utc
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.rebalance_strategy import (
    RebalanceInputContract,
    PriceConversion,
    RebalanceStrategyBase,
    observed_prices,
    valuation_prices,
)

from msm_portfolios.retirement import (
    drop_retired_rows,
    end_before_retirement,
    retirement_boundary,
    window_is_empty,
)
from ..base import (
    AssetScopedPortfolioCanonicalUpdater,
    OutputTable,
    PortfolioCanonicalUpdaterConfiguration,
    _empty_flat_frame,
    _require_columns,
    _reset_frame_index,
)
from ..constants import PORTFOLIO_IDENTIFIER
from ..portfolio_identity import get_or_create_portfolio
from .run_rows import ValuationRows, held_rows, rows_between, window_bound
from .storage import PortfolioRebalanceStateStorage
from .temporal import (
    fetch_asset_observations,
    normalize_asset_observations,
    strictly_before,
)


class PortfolioRebalanceConfiguration(PortfolioCanonicalUpdaterConfiguration):
    """The rebalance's own settings: the portfolio it keeps the state of.

    ``portfolio_identifier`` is the portfolio its run resolved. It is saved with the
    update, so a node Job run rebuilds the rebalance for that portfolio without the
    producer's resolver (ADR 0067, decision 4). It is no part of the update hash: the
    portfolio's configuration is.
    """

    portfolio_identifier: str | None = Field(
        default=None,
        json_schema_extra={"hash_excluded": True},
    )


class PortfolioRebalance(AssetScopedPortfolioCanonicalUpdater):
    """Persist strategy-owned target activation and partial execution state."""

    OFFSET_START = datetime(2018, 1, 1, tzinfo=pytz.utc)

    @classmethod
    def default_config(cls) -> PortfolioRebalanceConfiguration:
        return PortfolioRebalanceConfiguration()

    @classmethod
    def _validate_config(cls, config: Any) -> PortfolioRebalanceConfiguration:
        if not isinstance(config, PortfolioRebalanceConfiguration):
            raise TypeError(f"{cls.__name__} requires a PortfolioRebalanceConfiguration.")
        return config

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
        if portfolio_identifier is not None:
            # Saved with the update, outside its hash, for a node Job run to rebuild.
            self.config = self.config.model_copy(
                update={"portfolio_identifier": str(portfolio_identifier)}
            )
        self._rehash_for_portfolio_configuration(portfolio_configuration)
        backtesting = (
            portfolio_configuration.portfolio_build_configuration.backtesting_weights_configuration
        )
        self._portfolio_configuration = portfolio_configuration
        self._portfolio_identifier = self.config.portfolio_identifier
        self._portfolio = portfolio
        self._portfolio_resolver = portfolio_resolver
        self.signal_weights = backtesting.signal_weights_instance
        self.rebalance_strategy: RebalanceStrategyBase = backtesting.rebalance_strategy_instance
        build = portfolio_configuration.portfolio_build_configuration
        self.valuation_source = build.valuation_source_instance
        self.valuation_column = str(build.valuation_column)
        self.valuation_asset_identifier = str(build.valuation_asset_identifier)
        self.fx_source = build.fx_source_instance
        # The ledger's initial NAV is the book's unit, in the portfolio's currency
        # (ADR 0059, ADR 0065).
        self.book_unit_value = float(build.accounting_configuration.initial_nav)
        self.ledger_initial_state = build.accounting_configuration.initial_state_time_index
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
        """The signal, the prices it trades at and the strategy's declared inputs.

        A computed signal (``SignalWeights``) is its own node: the rebalance depends on it
        as ``signal_weights``, so it runs first, and reads its rows from its table. A
        signal whose weights arrive only by publication (``ApplicationWeights``) is no
        node and has no edge; the rebalance reads it from Markets. In one joined run a
        dependency several portfolios share runs once (issue #133).
        """
        if getattr(self, "_portfolio_configuration", None) is None:
            return {}
        declared = self.rebalance_strategy.declared_dependencies()
        for reserved in ("signal_weights", "valuation_source", "fx_source"):
            if reserved in declared:
                raise ValueError(f"{reserved!r} is reserved by PortfolioRebalance.")
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
        dependencies: dict[str, TimeIndexTableUpdater | TimeIndexTableRef] = {}
        if isinstance(self.signal_weights, TimeIndexTableUpdater):
            dependencies["signal_weights"] = self.signal_weights
        if self.rebalance_strategy.own_execution_prices() is None:
            # Each asset trades at its next observed price in the valuation source.
            dependencies["valuation_source"] = self.valuation_source
            if self.fx_source is not None:
                dependencies["fx_source"] = self.fx_source
        return {**dependencies, **dict(sorted(declared.items()))}

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
        boundary = self._retirement_boundary()
        end = end_before_retirement(end, boundary)
        if window_is_empty(start, end):
            return self._no_transitions()
        if latest is None:
            # A first run starts at the signal's first observation (#138). A computed
            # signal ran before this node in the same graph, so its table holds it.
            first = self.signal_weights.first_observation_time()
            if first is not None:
                start, end = self._execution_window(None, signal_start=first)
                end = end_before_retirement(end, boundary)
                if window_is_empty(start, end):
                    return self._no_transitions()
        assets = self._required_asset_identifiers()
        signals = self._signal_observations(start=start, end=end, assets=assets)
        if not assets and not signals.empty:
            assets = (
                signals.index.get_level_values(ASSET_IDENTIFIER_DIMENSION)
                .astype(str)
                .unique()
                .tolist()
            )
        previous_state = self._previous_state(latest)
        held = (
            []
            if previous_state is None
            else previous_state.reset_index()[ASSET_IDENTIFIER_DIMENSION].astype(str).tolist()
        )
        # The newest recorded rebalance's open orders trade at their first eligible
        # price from its earliest moment on, which can be before this window.
        since = self.rebalance_strategy.recorded_earliest_moment(previous_state, signals)
        price_start = start
        if since is not None and since < pd.Timestamp(start):
            price_start = since
        observed_inputs = read_strategy_inputs(
            self.rebalance_strategy,
            start=start,
            end=end,
            assets=assets,
            held=held,
            prices_since=price_start,
        )
        fill_prices = None
        reference_prices = None
        price_conversion = None
        if self.rebalance_strategy.own_execution_prices() is None:
            fill_prices, reference_prices, price_conversion = self._portfolio_prices(
                start=price_start,
                end=end,
                assets=list(dict.fromkeys([*assets, *held])),
            )
        transitions = self.rebalance_strategy.build_transitions(
            start=start,
            end=end,
            signal_observations=signals,
            observed_inputs=observed_inputs,
            previous_state=previous_state,
            fill_prices=fill_prices,
            reference_prices=reference_prices,
            price_conversion=price_conversion,
            book_unit_value=self.book_unit_value,
        )
        return drop_retired_rows(
            normalize_rebalance_state_frame(
                transitions,
                portfolio_identifier=self._resolve_portfolio_identifier(),
                output_table=self.output_table,
            ),
            boundary,
        )

    def _retirement_boundary(self) -> pd.Timestamp | None:
        """The portfolio's ``retired_at`` (ADR 0049), from the row the run resolved.

        A rebalance rebuilt without one, as in a node Job run, reads its portfolio's row.
        """

        portfolio = getattr(self, "_portfolio", None)
        configuration = getattr(self, "_portfolio_configuration", None)
        if portfolio is None and getattr(self, "_portfolio_identifier", None):
            from msm.api.portfolios import Portfolio

            portfolio = Portfolio.get_by_unique_identifier(self._portfolio_identifier)
        elif portfolio is None and configuration is not None:
            portfolio = get_or_create_portfolio(
                configuration,
                portfolio_resolver=getattr(self, "_portfolio_resolver", None),
            )
        return retirement_boundary(portfolio)

    def _no_transitions(self) -> pd.DataFrame:
        return normalize_rebalance_state_frame(
            pd.DataFrame(),
            portfolio_identifier=self._resolve_portfolio_identifier(),
            output_table=self.output_table,
        )

    def _execution_window(
        self, latest: Any | None, *, signal_start: Any | None = None
    ) -> tuple[Any, Any]:
        """After this portfolio's latest row, or on its first run from ``OFFSET_START``.

        ``signal_start``, the signal's first observation, moves a first run's start to it
        when it is later.
        """
        start: Any = self.OFFSET_START
        if latest is not None:
            start = pd.Timestamp(latest) + pd.Timedelta(1, unit="ns")
        elif signal_start is not None:
            start = max(pd.Timestamp(start), pd.Timestamp(signal_start))
        end: Any = pd.Timestamp.now(tz="UTC")
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, pd.Timestamp(start) + pd.Timedelta(maximum_window))
        return start, end

    def _latest_transition_time_index_value(self) -> Any | None:
        """This portfolio's latest rebalance-state time; ``None`` before its first row.

        A producer keeps one rebalance-state table for all its portfolios, so the
        table's latest time is another portfolio's progress, never this one's start
        (#118). With no row of its own, the run starts at ``OFFSET_START``.
        """

        progress = getattr(getattr(self, "update_statistics", None), "index_progress", None)
        if not isinstance(progress, dict):
            return None
        value = progress.get(self._resolve_portfolio_identifier())
        return self._max_in_nested_values(value) if isinstance(value, dict) else value

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

    def _portfolio_prices(
        self,
        *,
        start: Any,
        end: Any,
        assets: list[str],
    ) -> tuple[pd.DataFrame, pd.DataFrame, PriceConversion | None]:
        """Read the valuation source: the prices assets fill at, and those that value them.

        Fill prices are its observed rows in ``[start, end]``. Reference prices are all
        its rows there plus each asset's last row before ``start``, so a rebalance can
        value its holdings and size its decision at the window's first instant. With an
        FX source, prices in another currency are converted at the last observed rate
        (ADR 0059); the rates are read from ``start``, with each currency's last rate
        before it.

        In a portfolio run (``run_rows``) the source is read once for the rebalance and
        its ledger (#139): from the ledger's initial state when that is earlier, and to the
        source's last row unless ``MAX_TD_FROM_LATEST_VALUE`` bounds the window. The rows
        before ``start`` give each asset's last row; an asset with none there is read.
        """
        held = held_rows()
        read_start = start
        read_end = end
        initial = getattr(self, "ledger_initial_state", None)
        if held is not None:
            if initial is not None and window_bound(initial) < window_bound(start):
                read_start = initial
            if not os.getenv("MAX_TD_FROM_LATEST_VALUE"):
                read_end = None
        kwargs: dict[str, Any] = {
            "start_date": read_start,
            "end_date": read_end,
            "great_or_equal": True,
            "less_or_equal": True,
        }
        if assets:
            kwargs["dimension_filters"] = {ASSET_IDENTIFIER_DIMENSION: assets}
        read = self.valuation_source.get_df_between_dates(**kwargs)
        read = pd.DataFrame() if read is None else read
        frame = rows_between(read, start=start, end=end)
        seeds = self._last_prices_before(read, start=start, read_start=read_start, assets=assets)
        if held is not None:
            held.valuations[self._resolve_portfolio_identifier()] = ValuationRows(
                source=self.valuation_source,
                start=window_bound(read_start),
                end=None if read_end is None else window_bound(read_end),
                assets=frozenset(assets) if assets else None,
                frame=read,
            )
        flat_frames = [
            _flat_frame(item) for item in (seeds, frame) if item is not None and not item.empty
        ]
        combined = pd.concat(flat_frames, ignore_index=True) if flat_frames else pd.DataFrame()
        currencies = quote_currencies(
            combined,
            valuation_asset_identifier=self.valuation_asset_identifier,
            fx_declared=self.fx_source is not None,
        )
        conversion = None
        if self.fx_source is not None:
            conversion = PriceConversion(
                valuation_asset_identifier=self.valuation_asset_identifier,
                currencies=currencies,
                fx_rates=read_fx_rates(
                    self.fx_source,
                    currencies=currencies,
                    valuation_asset_identifier=self.valuation_asset_identifier,
                    start=start,
                    end=end,
                ),
            )
        return (
            observed_prices(frame, price_column=self.valuation_column),
            valuation_prices(combined, price_column=self.valuation_column),
            conversion,
        )

    def _last_prices_before(
        self, read: pd.DataFrame, *, start: Any, read_start: Any, assets: list[str]
    ) -> pd.DataFrame:
        """Each asset's last valuation row strictly before ``start``.

        Taken from ``read`` (the source from ``read_start`` on); an asset with no row there
        before ``start`` has its last row before ``read_start`` read.
        """
        if not assets:
            return pd.DataFrame()
        earlier = pd.DataFrame()
        if not read.empty:
            flat = _flat_frame(read)
            flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
            flat = flat[flat["time_index"] < pd.Timestamp(start)]
            earlier = (
                flat.sort_values("time_index", kind="stable")
                .groupby(ASSET_IDENTIFIER_DIMENSION, sort=False)
                .tail(1)
                .reset_index(drop=True)
            )
        found = set() if earlier.empty else set(earlier[ASSET_IDENTIFIER_DIMENSION].astype(str))
        missing = [asset for asset in assets if asset not in found]
        before = _last_rows_before(
            self.valuation_source,
            coordinates=tuple({ASSET_IDENTIFIER_DIMENSION: asset} for asset in missing),
            before=read_start,
        )
        frames = [item for item in (earlier, before) if not item.empty]
        if not frames:
            return pd.DataFrame()
        return (
            pd.concat(frames, ignore_index=True)
            .sort_values("time_index", kind="stable")
            .reset_index(drop=True)
        )

    def _previous_state(self, latest: Any | None) -> pd.DataFrame | None:
        """Return the latest rebalance-state row of every asset of the portfolio.

        Assets fill independently, so their latest rows have different times and
        intents; an asset missing from the rows at ``latest`` still holds its
        weight. The update statistics hold the latest time of every
        ``(intent, asset)``, and the rows at those times are read exactly.
        """
        if latest is None:
            return None
        portfolio_identifier = self._resolve_portfolio_identifier()
        coordinates = self._latest_coordinates_by_asset(portfolio_identifier)
        if not coordinates:
            frame = self.get_df_between_dates(
                start_date=latest,
                end_date=latest,
                dimension_filters={PORTFOLIO_IDENTIFIER: [portfolio_identifier]},
            )
            return None if frame is None or frame.empty else frame
        frame = self.get_last_observation(
            dimension_filters={
                PORTFOLIO_IDENTIFIER: [portfolio_identifier],
                "rebalance_intent_id": sorted({intent for intent, _asset, _time in coordinates}),
                ASSET_IDENTIFIER_DIMENSION: sorted(
                    {asset for _intent, asset, _time in coordinates}
                ),
            },
            dimension_range_map=[
                {
                    "coordinate": {
                        PORTFOLIO_IDENTIFIER: portfolio_identifier,
                        "rebalance_intent_id": intent,
                        ASSET_IDENTIFIER_DIMENSION: asset,
                    },
                    "end_date": pd.Timestamp(time_index).to_pydatetime(),
                    "end_date_operand": "<=",
                }
                for intent, asset, time_index in coordinates
            ],
        )
        return None if frame is None or frame.empty else frame

    def _latest_coordinates_by_asset(
        self,
        portfolio_identifier: str,
    ) -> list[tuple[str, str, pd.Timestamp]]:
        """Return ``(intent, asset, time)`` of each asset's latest row from update statistics.

        Rows that tie at an asset's latest time are all returned; a superseded row
        and its replacement share a time.
        """
        statistics = getattr(self, "update_statistics", None)
        progress = getattr(statistics, "index_progress", None)
        if not isinstance(progress, dict):
            return []
        by_intent = progress.get(portfolio_identifier)
        if not isinstance(by_intent, dict):
            return []
        latest: dict[str, list[tuple[str, pd.Timestamp]]] = {}
        for intent, by_asset in by_intent.items():
            if not isinstance(by_asset, dict):
                return []
            for asset, value in by_asset.items():
                if value is None:
                    continue
                time_index = pd.Timestamp(value)
                time_index = (
                    time_index.tz_localize("UTC")
                    if time_index.tzinfo is None
                    else time_index.tz_convert("UTC")
                )
                current = latest.get(str(asset))
                if current is None or time_index > current[0][1]:
                    latest[str(asset)] = [(str(intent), time_index)]
                elif time_index == current[0][1]:
                    current.append((str(intent), time_index))
        return [
            (intent, asset, time_index)
            for asset, entries in sorted(latest.items())
            for intent, time_index in entries
        ]

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


def read_strategy_inputs(
    strategy: RebalanceStrategyBase,
    *,
    start: Any,
    end: Any,
    assets: list[str],
    held: list[str] | tuple[str, ...] = (),
    prices_since: Any | None = None,
) -> dict[str, pd.DataFrame]:
    """Read every input ``strategy`` declares, each over its ``dependency_window``.

    Each window is read at the coordinates the strategy follows
    (``dependency_seed_coordinates``), such as its calendar in the calendar events, and
    ``assets`` and ``held`` filter the asset-scoped inputs. The input a strategy trades
    at (``own_execution_prices``) values its book and sizes each rebalance with each
    asset's last row before its earliest moment (#90): it is read from
    ``prices_since``, the newest recorded rebalance's earliest moment, when that is
    earlier than the window, with each asset's last row before then.
    """
    dependencies = strategy.declared_dependencies()
    contracts = strategy.required_input_contract()
    if set(dependencies) != set(contracts):
        raise ValueError("Rebalance strategy dependency names and input-contract names must match.")
    universe = list(dict.fromkeys([*assets, *held]))
    own_prices = strategy.own_execution_prices()
    result: dict[str, pd.DataFrame] = {}
    for name in sorted(dependencies):
        source_start, source_end = strategy.dependency_window(name, start, end)
        seeds = strategy.dependency_seed_coordinates(name)
        contract = contracts[name]
        # The window is read at the coordinates the strategy follows (#138).
        dimensions = dict.fromkeys(dimension for coordinate in seeds for dimension in coordinate)
        dimension_filters = {
            dimension: sorted({str(coordinate[dimension]) for coordinate in seeds})
            for dimension in dimensions
        }
        if contract.asset_scoped and universe:
            dimension_filters[ASSET_IDENTIFIER_DIMENSION] = universe
        if own_prices is not None and name == own_prices[0]:
            if prices_since is not None and pd.Timestamp(prices_since) < pd.Timestamp(
                source_start
            ):
                source_start = prices_since
            seeds = (*seeds, *({ASSET_IDENTIFIER_DIMENSION: asset} for asset in universe))
        result[name] = read_rebalance_input(
            dependencies[name],
            dependency_name=name,
            contract=contract,
            start=source_start,
            end=source_end,
            seed_coordinates=seeds,
            dimension_filters=dimension_filters or None,
        )
    return result


def read_rebalance_input(
    dependency: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    dependency_name: str,
    contract: RebalanceInputContract,
    start: Any,
    end: Any,
    seed_coordinates: tuple[dict[str, str], ...] = (),
    dimension_filters: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """Read one declared strategy input over ``[start, end]``.

    For each of ``seed_coordinates`` the latest row strictly before ``start`` is
    read too, so the strategy sees the state in force when the window opens.
    """
    kwargs: dict[str, Any] = {
        "start_date": start,
        "end_date": end,
        "great_or_equal": True,
        "less_or_equal": True,
    }
    if dimension_filters:
        kwargs["dimension_filters"] = dimension_filters
    frames = [
        dependency.get_df_between_dates(**kwargs),
        _last_rows_before(dependency, coordinates=seed_coordinates, before=start),
    ]
    flat_frames = [
        _flat_frame(frame) for frame in frames if frame is not None and not frame.empty
    ]
    combined = pd.concat(flat_frames, ignore_index=True) if flat_frames else pd.DataFrame()
    return normalize_rebalance_input(
        combined,
        dependency_name=dependency_name,
        contract=contract,
    )


def _last_rows_before(
    dependency: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    coordinates: tuple[dict[str, str], ...],
    before: Any,
) -> pd.DataFrame:
    """Return, for each coordinate, its latest row strictly before ``before``."""
    if not coordinates:
        return pd.DataFrame()
    dimensions = sorted({name for coordinate in coordinates for name in coordinate})
    if any(set(coordinate) != set(dimensions) for coordinate in coordinates):
        raise ValueError("Seed coordinates must all name the same dimensions.")
    dimension_filters = {
        name: sorted({str(coordinate[name]) for coordinate in coordinates})
        for name in dimensions
    }
    boundary = pd.Timestamp(before)
    boundary = boundary.tz_localize("UTC") if boundary.tzinfo is None else boundary
    request_end, operand = strictly_before(boundary)
    get_last_observation = getattr(dependency, "get_last_observation", None)
    if callable(get_last_observation):
        frame = get_last_observation(
            dimension_filters=dimension_filters,
            dimension_range_map=[
                {
                    "coordinate": dict(coordinate),
                    "end_date": request_end,
                    "end_date_operand": operand,
                }
                for coordinate in coordinates
            ],
        )
    else:
        frame = dependency.get_df_between_dates(
            end_date=request_end,
            less_or_equal=operand == "<=",
            dimension_filters=dimension_filters,
        )
    if frame is None or frame.empty:
        return pd.DataFrame()
    flat = _flat_frame(frame)
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
    flat = flat[flat["time_index"] < boundary]
    wanted = {tuple(str(coordinate[name]) for name in dimensions) for coordinate in coordinates}
    keys = zip(*(flat[name].astype(str) for name in dimensions), strict=True)
    flat = flat[pd.Series([key in wanted for key in keys], index=flat.index, dtype=bool)]
    return (
        flat.sort_values("time_index", kind="stable")
        .groupby(dimensions, sort=False)
        .tail(1)
        .reset_index(drop=True)
    )


def quote_currencies(
    frame: pd.DataFrame | None,
    *,
    valuation_asset_identifier: str,
    fx_declared: bool,
) -> dict[str, str]:
    """Return each asset's quote currency from the valuation source (ADR 0059).

    With an FX source the source must name each price's currency in
    ``price_asset_identifier``. Without one, every asset is priced in the portfolio's
    currency: a currency column naming another is refused, never converted silently.
    """
    flat = pd.DataFrame() if frame is None or frame.empty else _flat_frame(frame)
    if "price_asset_identifier" not in flat.columns:
        if fx_declared and not flat.empty:
            raise ValueError(
                "The portfolio declares fx_source_instance, so its valuation source must "
                "have a price_asset_identifier column naming each price's currency "
                "(ADR 0059)."
            )
        return {}
    pairs = flat[[ASSET_IDENTIFIER_DIMENSION, "price_asset_identifier"]].astype(str)
    pairs = pairs.drop_duplicates()
    repeated = sorted(
        pairs.loc[pairs[ASSET_IDENTIFIER_DIMENSION].duplicated(), ASSET_IDENTIFIER_DIMENSION]
    )
    if repeated:
        raise ValueError(
            "The valuation source quotes these assets in more than one currency: "
            + ", ".join(repeated)
        )
    currencies = dict(
        zip(pairs[ASSET_IDENTIFIER_DIMENSION], pairs["price_asset_identifier"], strict=True)
    )
    foreign = sorted(
        asset for asset, currency in currencies.items() if currency != valuation_asset_identifier
    )
    if foreign and not fx_declared:
        raise ValueError(
            f"The valuation source quotes {', '.join(foreign)} in another currency than the "
            f"portfolio's {valuation_asset_identifier}; a portfolio holding them needs "
            "fx_source_instance (ADR 0059)."
        )
    return currencies


def read_fx_rates(
    fx_source: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    currencies: dict[str, str],
    valuation_asset_identifier: str,
    start: Any,
    end: Any,
) -> pd.DataFrame:
    """Read the rates into the portfolio's currency over ``[start, end]``.

    Each needed currency's last rate before ``start`` is read too, so a price at the
    window's first instant has a rate.
    """
    foreign = sorted(
        {currency for currency in currencies.values() if currency != valuation_asset_identifier}
    )
    if not foreign:
        return pd.DataFrame()
    filters = {
        "base_asset_identifier": foreign,
        "quote_asset_identifier": [valuation_asset_identifier],
    }
    window = fx_source.get_df_between_dates(
        start_date=start,
        end_date=end,
        great_or_equal=True,
        less_or_equal=True,
        dimension_filters=filters,
    )
    seeds = _last_rows_before(
        fx_source,
        coordinates=tuple(
            {"base_asset_identifier": currency, "quote_asset_identifier": valuation_asset_identifier}
            for currency in foreign
        ),
        before=start,
    )
    frames = [_flat_frame(item) for item in (seeds, window) if item is not None and not item.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _flat_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the frame with its named index levels as columns."""
    if list(frame.index.names) == [None]:
        return frame.reset_index(drop=True)
    return frame.reset_index()


def normalize_rebalance_input(
    frame: pd.DataFrame | None,
    *,
    dependency_name: str,
    contract: RebalanceInputContract,
) -> pd.DataFrame:
    """Validate and deterministically consolidate one declared observed input."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    flat = _flat_frame(frame.copy())
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
    "PortfolioRebalanceConfiguration",
    "normalize_rebalance_input",
    "normalize_rebalance_state_frame",
    "read_rebalance_input",
    "read_strategy_inputs",
]
