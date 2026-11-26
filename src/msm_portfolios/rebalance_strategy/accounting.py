"""Explicit, vectorized execution simulation for position-aware backtests."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Iterable, Literal, Mapping

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from msm_portfolios.accounting.contracts import AccountingStateView, EventBatch


SettlementStyle = Literal["cash", "variation_margin"]
TargetMeasure = Literal["market_value_weight", "notional_weight"]


@dataclass(frozen=True)
class AccountingExecutionContext:
    """One immutable strategy decision at an economic timestamp."""

    time_index: pd.Timestamp
    event_source: str
    rebalance_intent_id: str
    signal_time_index: pd.Timestamp
    signal_target_weights: Mapping[str, float]
    desired_weights: Mapping[str, float]
    weight_before: Mapping[str, float]
    asset_executions: Mapping[str, Any]
    state: AccountingStateView
    available_balances: pd.DataFrame
    pre_execution_nav: float
    valuation_asset_identifier: str
    valuation_references: str
    valuation_observations: pd.DataFrame
    fx_observations: pd.DataFrame
    event_observations: Mapping[str, pd.DataFrame]
    strategy_revision: str
    completion_tolerance: float
    # The lowest cash the execution policy allows, in the portfolio's currency.
    # ``None`` books every fill in full; otherwise buys the ledger's own cash cannot
    # cover are cut (ADR 0058).
    cash_floor: float | None = None

    def __post_init__(self) -> None:
        timestamp = _utc_timestamp(self.time_index)
        signal_time = _utc_timestamp(self.signal_time_index)
        if not np.isfinite(self.pre_execution_nav) or self.pre_execution_nav <= 0:
            raise ValueError("Position-aware target-weight execution requires positive finite NAV.")
        if not self.valuation_asset_identifier:
            raise ValueError("valuation_asset_identifier is required for execution sizing.")
        object.__setattr__(self, "time_index", timestamp)
        object.__setattr__(self, "signal_time_index", signal_time)
        object.__setattr__(
            self,
            "signal_target_weights",
            MappingProxyType(dict(self.signal_target_weights)),
        )
        object.__setattr__(self, "desired_weights", MappingProxyType(dict(self.desired_weights)))
        object.__setattr__(self, "weight_before", MappingProxyType(dict(self.weight_before)))
        object.__setattr__(self, "asset_executions", MappingProxyType(dict(self.asset_executions)))
        object.__setattr__(self, "available_balances", self.available_balances.copy())
        object.__setattr__(
            self,
            "event_observations",
            MappingProxyType(
                {name: frame.copy() for name, frame in self.event_observations.items()}
            ),
        )


class InstrumentExecutionSpec(BaseModel):
    """Explicit sizing and settlement contract for one simulated instrument."""

    model_config = ConfigDict(extra="forbid")

    asset_identifier: str = Field(min_length=1)
    position_identifier: str | None = None
    quantity_unit: str = Field(min_length=1)
    target_measure: TargetMeasure
    contract_multiplier: float = Field(gt=0.0, allow_inf_nan=False)
    quantity_step: float | None = Field(
        default=None,
        gt=0.0,
        allow_inf_nan=False,
        description=(
            "The lot step quantities are rounded toward zero to; None trades fractional "
            "quantities (ADR 0065, decision 11)."
        ),
    )
    price_asset_identifier: str = Field(min_length=1)
    settlement_style: SettlementStyle
    terms_version: str = Field(min_length=1)

    @property
    def resolved_position_identifier(self) -> str:
        return self.position_identifier or self.asset_identifier


class ExecutionCostModel(BaseModel, ABC):
    """Pure vectorized model for fill-time simulated costs."""

    model_config = ConfigDict(extra="forbid")

    model_identifier: ClassVar[str]
    model_version: ClassVar[str] = "1"

    @abstractmethod
    def cost_quantity_deltas(self, execution_facts: pd.DataFrame) -> np.ndarray:
        """Return signed cost-currency cash deltas for every simulated execution."""


class ProportionalExecutionCostModel(ExecutionCostModel):
    """Charge a proportion of absolute quote-currency executed notional."""

    model_identifier: ClassVar[str] = "msm.proportional_execution_cost"
    model_version: ClassVar[str] = "1"

    rate: float = Field(ge=0.0, allow_inf_nan=False)
    minimum_cost: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)

    def cost_quantity_deltas(self, execution_facts: pd.DataFrame) -> np.ndarray:
        notionals = np.abs(
            execution_facts["quantity_delta"].to_numpy(dtype="float64")
            * execution_facts["execution_price"].to_numpy(dtype="float64")
            * execution_facts["contract_multiplier"].to_numpy(dtype="float64")
        )
        costs = notionals * self.rate
        if self.minimum_cost:
            costs = np.where(notionals > 0.0, np.maximum(costs, self.minimum_cost), 0.0)
        return -costs


class PositionExecutionModel(BaseModel, ABC):
    """Pure model that converts one strategy target into simulated ledger events."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_identifier: ClassVar[str]
    model_version: ClassVar[str] = "1"

    def current_weights(
        self,
        *,
        state: AccountingStateView,
        valuation_result: Any,
        time_index: pd.Timestamp,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> dict[str, float]:
        """Return current exposure in the target measure understood by the model."""

        del state, time_index, valuation_asset_identifier, valuation_observations
        del fx_observations
        return _market_value_weights(valuation_result)

    def decision_quantities(
        self,
        *,
        valuation_result: Any,
        time_index: pd.Timestamp,
        target_weights: Mapping[str, float],
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> dict[str, float] | None:
        """Return the share counts fixed at a rebalance's decision, or ``None``.

        ``None`` (the default) leaves sizing to ``simulate``, at each fill.
        """
        del valuation_result, time_index, target_weights, valuation_asset_identifier
        del valuation_observations, fx_observations
        return None

    @abstractmethod
    def simulate(
        self,
        context: AccountingExecutionContext,
        *,
        cost_models: tuple[ExecutionCostModel, ...],
    ) -> EventBatch:
        """Return complete simulated execution events for one strategy decision."""


class TargetWeightExecutionModel(PositionExecutionModel):
    """Vectorized target-weight sizing with explicit instrument settlement terms."""

    model_identifier: ClassVar[str] = "msm.target_weight_execution"
    model_version: ClassVar[str] = "1"

    instrument_specs: tuple[InstrumentExecutionSpec, ...]
    price_column: str = Field(default="price", min_length=1)

    @model_validator(mode="after")
    def validate_instrument_specs(self) -> TargetWeightExecutionModel:
        assets = [spec.asset_identifier for spec in self.instrument_specs]
        if len(assets) != len(set(assets)):
            raise ValueError("Instrument execution specs require unique asset identifiers.")
        positions = [spec.resolved_position_identifier for spec in self.instrument_specs]
        if len(positions) != len(set(positions)):
            raise ValueError("Instrument execution specs require unique position identifiers.")
        return self

    def simulate(
        self,
        context: AccountingExecutionContext,
        *,
        cost_models: tuple[ExecutionCostModel, ...],
    ) -> EventBatch:
        execution_assets = _economically_required_execution_assets(context)
        groups = [
            _with_costs(
                self._execution_facts(context, execution_assets=grouped_assets),
                cost_models,
            )
            for grouped_assets in self._execution_groups(execution_assets)
        ]
        if context.cash_floor is not None and groups:
            groups = _cut_uncovered_buys(context, groups, cost_models)
        batches: list[EventBatch] = [_execution_event_batch(facts) for facts in groups]
        progress_only_assets = set(context.desired_weights) - execution_assets
        if progress_only_assets:
            batches.append(
                _progress_only_event_batch(
                    context,
                    assets=progress_only_assets,
                    model_identifier=self.model_identifier,
                    model_version=self.model_version,
                )
            )
        return _combine_event_batches(batches)

    def _execution_groups(self, execution_assets: set[str]) -> tuple[set[str], ...]:
        by_asset = {spec.asset_identifier: spec for spec in self.instrument_specs}
        missing_specs = sorted(execution_assets - set(by_asset))
        if missing_specs:
            raise ValueError(
                "Missing explicit instrument execution specs for: "
                + ", ".join(missing_specs)
            )
        grouped: dict[tuple[Any, ...], set[str]] = {}
        for asset in sorted(execution_assets):
            spec = by_asset[asset]
            signature = (
                self.model_identifier,
                self.model_version,
                spec.target_measure,
                spec.quantity_unit,
                spec.price_asset_identifier,
                spec.contract_multiplier,
                spec.quantity_step,
                spec.terms_version,
                spec.settlement_style,
            )
            grouped.setdefault(signature, set()).add(asset)
        return tuple(grouped[signature] for signature in sorted(grouped, key=str))

    def decision_quantities(
        self,
        *,
        valuation_result: Any,
        time_index: pd.Timestamp,
        target_weights: Mapping[str, float],
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> dict[str, float]:
        """Return the share counts a rebalance decided at ``time_index`` fixes.

        ``target weight x NAV / price``, rounded down to the lot step. Every price and
        FX rate is the last observed at or before ``time_index``, the same set for all
        assets; the caller passes the instant just before the rebalance's earliest
        moment, and the NAV then, or at the ledger's opening for a rebalance decided
        before it (#150). A zero target is zero shares and needs no price.
        """
        nav = float(valuation_result.nav)
        if not np.isfinite(nav) or nav <= 0.0:
            raise ValueError(
                "Position-aware target-weight execution requires positive finite NAV."
            )
        quantities = {
            str(asset): 0.0
            for asset, weight in target_weights.items()
            if np.isclose(float(weight), 0.0, rtol=0.0, atol=1e-15)
        }
        sized = sorted(str(asset) for asset in target_weights if str(asset) not in quantities)
        if not sized:
            return quantities
        by_asset = {spec.asset_identifier: spec for spec in self.instrument_specs}
        missing_specs = sorted(set(sized) - set(by_asset))
        if missing_specs:
            raise ValueError(
                "Missing explicit instrument execution specs for: " + ", ".join(missing_specs)
            )
        try:
            marks = _select_execution_marks(
                valuation_observations,
                time_index=time_index,
                asset_identifiers=sized,
                price_column=self.price_column,
            )
        except ValueError as error:
            raise ValueError(
                f"A rebalance decided at {time_index.isoformat()} sizes its shares from the "
                f"last prices observed before its earliest moment. {error}"
            ) from error
        rows = _instrument_specs_frame(by_asset[asset] for asset in sized).merge(
            marks,
            on="asset_identifier",
            how="left",
            validate="one_to_one",
        )
        mismatched_quote = rows[
            rows["price_asset_identifier_x"].astype(str)
            != rows["price_asset_identifier_y"].astype(str)
        ]
        if not mismatched_quote.empty:
            raise ValueError(
                "Execution mark quote Asset disagrees with instrument terms for: "
                + ", ".join(mismatched_quote["asset_identifier"].astype(str))
            )
        fx_rates, _ = _execution_fx_rates(
            rows["price_asset_identifier_x"],
            valuation_asset_identifier=valuation_asset_identifier,
            time_index=time_index,
            fx_observations=fx_observations,
        )
        unit_value = (
            rows[self.price_column].to_numpy(dtype="float64")
            * rows["contract_multiplier"].to_numpy(dtype="float64")
            * fx_rates
        )
        weights = np.array(
            [float(target_weights[asset]) for asset in rows["asset_identifier"].astype(str)],
            dtype="float64",
        )
        decided = _round_to_steps(
            weights * nav / unit_value,
            rows["quantity_step"].to_numpy(dtype="float64"),
        )
        quantities.update(
            zip(rows["asset_identifier"].astype(str), decided.tolist(), strict=True)
        )
        return quantities

    def current_weights(
        self,
        *,
        state: AccountingStateView,
        valuation_result: Any,
        time_index: pd.Timestamp,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> dict[str, float]:
        nav = float(valuation_result.nav)
        if not np.isfinite(nav) or nav <= 0.0:
            raise ValueError(
                "Position-aware target-weight execution requires positive finite NAV."
            )
        by_asset = {spec.asset_identifier: spec for spec in self.instrument_specs}
        result = _market_value_weights(valuation_result)
        market_value_assets = {
            spec.asset_identifier
            for spec in self.instrument_specs
            if spec.target_measure == "market_value_weight"
        }
        result = {
            asset: weight for asset, weight in result.items() if asset in market_value_assets
        }
        if state.positions.empty:
            return result
        held = state.positions.copy()
        held = held[~np.isclose(held["quantity"].to_numpy(dtype="float64"), 0.0)]
        held_assets = set(held["asset_identifier"].astype(str))
        missing_specs = sorted(held_assets - set(by_asset))
        if missing_specs:
            raise ValueError(
                "Missing explicit instrument execution specs for held positions: "
                + ", ".join(missing_specs)
            )
        notional_specs = [
            by_asset[asset]
            for asset in sorted(held_assets)
            if by_asset[asset].target_measure == "notional_weight"
        ]
        if not notional_specs:
            return result
        specs = _instrument_specs_frame(notional_specs)
        marks = _select_execution_marks(
            valuation_observations,
            time_index=time_index,
            asset_identifiers=specs["asset_identifier"].tolist(),
            price_column=self.price_column,
        )
        marked = specs.merge(marks, on="asset_identifier", how="left", validate="one_to_one")
        mismatched_quote = marked[
            marked["price_asset_identifier_x"].astype(str)
            != marked["price_asset_identifier_y"].astype(str)
        ]
        if not mismatched_quote.empty:
            raise ValueError(
                "Execution mark quote Asset disagrees with instrument terms for: "
                + ", ".join(mismatched_quote["asset_identifier"].astype(str))
            )
        marked = marked.rename(
            columns={"price_asset_identifier_x": "price_asset_identifier"}
        ).drop(columns=["price_asset_identifier_y"])
        quantities = _current_quantities(state.positions, specs=marked)
        fx_rates, _ = _execution_fx_rates(
            marked["price_asset_identifier"],
            valuation_asset_identifier=valuation_asset_identifier,
            time_index=time_index,
            fx_observations=fx_observations,
        )
        exposures = (
            quantities
            * marked[self.price_column].to_numpy(dtype="float64")
            * marked["contract_multiplier"].to_numpy(dtype="float64")
            * fx_rates
            / nav
        )
        result.update(
            dict(zip(marked["asset_identifier"].astype(str), exposures, strict=True))
        )
        return result

    def _execution_facts(
        self,
        context: AccountingExecutionContext,
        *,
        execution_assets: set[str],
    ) -> pd.DataFrame:
        configured_assets = {spec.asset_identifier for spec in self.instrument_specs}
        missing_specs = sorted(execution_assets - configured_assets)
        if missing_specs:
            raise ValueError(
                "Missing explicit instrument execution specs for: " + ", ".join(missing_specs)
            )

        rows = _instrument_specs_frame(
            spec for spec in self.instrument_specs if spec.asset_identifier in execution_assets
        )
        # Each execution books the price PortfolioRebalance recorded for its fill: an
        # observed price at the fill's time. The ledger does not look up its own mark.
        prices: list[float] = []
        strategy_input_revisions: list[str] = []
        strategy_observed_at: list[pd.Timestamp] = []
        for asset in rows["asset_identifier"].astype(str):
            execution = context.asset_executions[asset]
            execution_price = getattr(execution, "execution_price", None)
            if execution_price is None:
                raise ValueError(
                    f"The fill of {asset} at {context.time_index.isoformat()} has no recorded "
                    "execution price."
                )
            price_time = getattr(execution, "price_time_index", None)
            if price_time is None or _utc_timestamp(price_time) != context.time_index:
                # A later price inside an earlier event would value the trade with
                # information the ledger did not have yet.
                observed = "an unknown time" if price_time is None else price_time.isoformat()
                raise ValueError(
                    f"The fill of {asset} at {context.time_index.isoformat()} carries a price "
                    f"observed at {observed}; a fill is booked at its price's own time."
                )
            price = float(execution_price)
            if not np.isfinite(price) or price <= 0.0:
                raise ValueError("Recorded execution prices must be finite and positive.")
            prices.append(price)
            revision, observed_at = _strategy_observation_reference(
                context.event_observations,
                asset_identifier=asset,
                time_index=context.time_index,
            )
            strategy_input_revisions.append(revision)
            strategy_observed_at.append(observed_at)
        rows[self.price_column] = prices
        rows["price_source_revision"] = strategy_input_revisions
        rows["mark_observed_at"] = strategy_observed_at
        rows["strategy_input_revision"] = strategy_input_revisions
        rows["strategy_observed_at"] = strategy_observed_at

        fx_rates, fx_revisions = _execution_fx_rates(
            rows["price_asset_identifier"],
            valuation_asset_identifier=context.valuation_asset_identifier,
            time_index=context.time_index,
            fx_observations=context.fx_observations,
        )
        rows["fx_rate"] = fx_rates
        rows["fx_source_revision"] = fx_revisions
        rows["target_weight"] = rows["asset_identifier"].map(context.desired_weights).astype(
            "float64"
        )
        rows["signal_target_weight"] = rows["asset_identifier"].map(
            context.signal_target_weights
        ).fillna(0.0)
        rows["weight_before"] = rows["asset_identifier"].map(context.weight_before).fillna(0.0)
        for column in ("target_weight", "signal_target_weight", "weight_before"):
            if not np.isfinite(rows[column].to_numpy(dtype="float64")).all():
                raise ValueError(f"Execution {column} values must be finite.")

        current_quantity = _current_quantities(context.state.positions, specs=rows)
        rows["quantity_before"] = current_quantity
        unit_value = (
            rows[self.price_column].to_numpy(dtype="float64")
            * rows["contract_multiplier"].to_numpy(dtype="float64")
            * rows["fx_rate"].to_numpy(dtype="float64")
        )
        if not np.isfinite(unit_value).all() or (unit_value <= 0.0).any():
            raise ValueError("Execution unit values must be finite and strictly positive.")
        # A rebalance that fixed its share counts at the decision fills them; any
        # other execution is sized here, from the NAV at the fill.
        decided = np.array(
            [
                np.nan
                if getattr(context.asset_executions[asset], "target_quantity", None) is None
                else float(context.asset_executions[asset].target_quantity)
                for asset in rows["asset_identifier"].astype(str)
            ],
            dtype="float64",
        )
        sized_at_fill = _round_to_steps(
            rows["target_weight"].to_numpy(dtype="float64")
            * float(context.pre_execution_nav)
            / unit_value,
            rows["quantity_step"].to_numpy(dtype="float64"),
        )
        order_target = np.where(np.isnan(decided), sized_at_fill, decided)
        # A fill that trades part of its open order trades that part of the ledger's
        # own order, rounded toward zero to the lot step.
        fraction = np.array(
            [
                float(getattr(context.asset_executions[asset], "fill_fraction", 1.0))
                for asset in rows["asset_identifier"].astype(str)
            ],
            dtype="float64",
        )
        if not np.isfinite(fraction).all():
            raise ValueError("Recorded fill fractions must be finite.")
        partial = ~np.isclose(fraction, 1.0, rtol=0.0, atol=1e-12)
        target_quantity = np.where(
            partial,
            current_quantity
            + _round_to_steps(
                (order_target - current_quantity) * fraction,
                rows["quantity_step"].to_numpy(dtype="float64"),
            ),
            order_target,
        )
        rows["target_quantity"] = target_quantity
        # The weight a fill reaches comes from its share count and its price.
        rows["target_weight"] = np.where(
            np.isnan(decided) & ~partial,
            rows["target_weight"].to_numpy(dtype="float64"),
            target_quantity * unit_value / float(context.pre_execution_nav),
        )
        rows["quantity_delta"] = target_quantity - current_quantity
        rows["execution_price"] = rows[self.price_column].to_numpy(dtype="float64")
        rows["settlement_asset_identifier"] = rows["price_asset_identifier"]
        cash_settlement = -(
            rows["quantity_delta"].to_numpy(dtype="float64")
            * rows["execution_price"].to_numpy(dtype="float64")
            * rows["contract_multiplier"].to_numpy(dtype="float64")
        )
        rows["settlement_quantity_delta"] = np.where(
            rows["settlement_style"].astype(str).to_numpy() == "cash",
            cash_settlement,
            0.0,
        )
        rows["cost_asset_identifier"] = rows["price_asset_identifier"]
        rows["time_index"] = context.time_index
        rows["observed_at"] = [
            max(mark_time, strategy_time)
            for mark_time, strategy_time in zip(
                rows["mark_observed_at"],
                rows["strategy_observed_at"],
                strict=True,
            )
        ]
        rows["event_source"] = context.event_source
        rows["rebalance_intent_id"] = context.rebalance_intent_id
        rows["target_signal_time_index"] = context.signal_time_index
        rows["pre_execution_nav"] = context.pre_execution_nav

        execution_status: list[str] = []
        strategy_states: list[dict[str, Any]] = []
        for asset in rows["asset_identifier"].astype(str):
            execution = context.asset_executions[asset]
            execution_status.append(_execution_status(context, asset))
            strategy_states.append(dict(getattr(execution, "strategy_state", {}) or {}))
        rows["execution_status"] = execution_status
        rows["strategy_state"] = strategy_states

        model_revision = _digest(
            {
                "model_identifier": self.model_identifier,
                "model_version": self.model_version,
                "config": self.model_dump(mode="json"),
            }
        )
        identifiers: list[str] = []
        revisions: list[str] = []
        for row in rows.to_dict(orient="records"):
            identity = {
                "rebalance_intent_id": context.rebalance_intent_id,
                "time_index": context.time_index.isoformat(),
                "asset_identifier": row["asset_identifier"],
                "position_identifier": row["position_identifier"],
                "execution_model": self.model_identifier,
            }
            identifiers.append(_digest(identity))
            revisions.append(
                _digest(
                    {
                        **identity,
                        "strategy_revision": context.strategy_revision,
                        "input_state_identifier": context.state.state_identifier,
                        "price_source_revision": row["price_source_revision"],
                        "strategy_input_revision": row["strategy_input_revision"],
                        "fx_source_revision": row["fx_source_revision"],
                        "terms_version": row["terms_version"],
                        "target_weight": row["target_weight"],
                        "quantity_delta": row["quantity_delta"],
                        "execution_price": row["execution_price"],
                        "model_revision": model_revision,
                    }
                )
            )
        rows["execution_identifier"] = identifiers
        rows["source_revision"] = revisions
        return rows


INSUFFICIENT_LEDGER_CASH = "insufficient_cash"


def _with_costs(facts: pd.DataFrame, cost_models: tuple[ExecutionCostModel, ...]) -> pd.DataFrame:
    cost_delta = np.zeros(len(facts), dtype="float64")
    for model in cost_models:
        values = np.asarray(model.cost_quantity_deltas(facts), dtype="float64")
        if values.shape != (len(facts),):
            raise ValueError(f"{model.model_identifier} must return one cost delta per execution.")
        if not np.isfinite(values).all() or (values > 0.0).any():
            raise ValueError("Execution cost models must return finite non-positive deltas.")
        cost_delta += values
    facts["cost_quantity_delta"] = cost_delta
    return facts


def _cut_uncovered_buys(
    context: AccountingExecutionContext,
    groups: list[pd.DataFrame],
    cost_models: tuple[ExecutionCostModel, ...],
) -> list[pd.DataFrame]:
    """Cut the buys the ledger's own cash cannot cover, pro rata, and record the cut.

    ``PortfolioRebalance`` already fitted its fills to its cash. The ledger's cash can
    still be short of it: lot rounding, execution costs and lifecycle cash flows are
    the ledger's alone. Cash is counted across all currencies in the portfolio's
    currency at the last observed FX rate (ADR 0059). Sells and costs at this instant
    count; the buys then share what is left down to ``context.cash_floor``, each cut by
    the same fraction and rounded toward zero to its lot step (ADR 0058).
    """
    for facts in groups:
        facts["ledger_cut_quantity"] = 0.0
        facts["ledger_cut_reason"] = None
    floor = float(context.cash_floor or 0.0)
    balances = context.available_balances
    balance = 0.0
    if not balances.empty:
        rates, _ = _execution_fx_rates(
            balances["asset_identifier"].astype(str),
            valuation_asset_identifier=context.valuation_asset_identifier,
            time_index=context.time_index,
            fx_observations=context.fx_observations,
        )
        balance = float((balances["quantity"].to_numpy(dtype="float64") * rates).sum())
    flow = 0.0
    spend = 0.0
    buy_costs = 0.0
    for facts in groups:
        fx_rate = facts["fx_rate"].to_numpy(dtype="float64")
        settled = facts["settlement_quantity_delta"].to_numpy(dtype="float64") * fx_rate
        costs = facts["cost_quantity_delta"].to_numpy(dtype="float64") * fx_rate
        buys = _cash_settled_buys(facts)
        flow += float(settled.sum() + costs.sum())
        spend -= float(settled[buys].sum())
        buy_costs -= float(costs[buys].sum())
    if balance + flow >= floor - 1e-9 or spend <= 0.0:
        return groups
    # The buys' spend and costs are what the cut can save; the rest is fixed.
    available = balance + flow + spend + buy_costs - floor
    fraction = min(max(available / (spend + buy_costs), 0.0), 1.0)
    nav = float(context.pre_execution_nav)
    changed: set[int] = set()
    for position, facts in enumerate(groups):
        buys = _cash_settled_buys(facts)
        if not buys.any():
            continue
        delta = facts["quantity_delta"].to_numpy(dtype="float64")
        kept = _round_to_steps(delta * fraction, facts["quantity_step"].to_numpy(dtype="float64"))
        new_delta = np.where(buys, kept, delta)
        cut = delta - new_delta
        if not (np.abs(cut) > 0.0).any():
            continue
        unit_value = (
            facts["execution_price"].to_numpy(dtype="float64")
            * facts["contract_multiplier"].to_numpy(dtype="float64")
            * facts["fx_rate"].to_numpy(dtype="float64")
        )
        facts["quantity_delta"] = new_delta
        facts["target_quantity"] = facts["quantity_before"].to_numpy(dtype="float64") + new_delta
        facts["target_weight"] = np.where(
            buys,
            facts["target_quantity"].to_numpy(dtype="float64") * unit_value / nav,
            facts["target_weight"].to_numpy(dtype="float64"),
        )
        facts["settlement_quantity_delta"] = np.where(
            facts["settlement_style"].astype(str).to_numpy() == "cash",
            -(
                new_delta
                * facts["execution_price"].to_numpy(dtype="float64")
                * facts["contract_multiplier"].to_numpy(dtype="float64")
            ),
            0.0,
        )
        facts["ledger_cut_quantity"] = cut
        facts["ledger_cut_reason"] = [
            INSUFFICIENT_LEDGER_CASH if abs(value) > 0.0 else None for value in cut
        ]
        facts["source_revision"] = [
            revision
            if abs(value) == 0.0
            else _digest({"source_revision": revision, "ledger_cut_quantity": float(value)})
            for revision, value in zip(facts["source_revision"], cut, strict=True)
        ]
        changed.add(position)
    return [
        _with_costs(facts, cost_models) if position in changed else facts
        for position, facts in enumerate(groups)
    ]


def _cash_settled_buys(facts: pd.DataFrame) -> np.ndarray:
    return (
        (facts["settlement_style"].astype(str) == "cash") & (facts["quantity_delta"] > 0.0)
    ).to_numpy()


def _execution_event_batch(facts: pd.DataFrame) -> EventBatch:
    """Convert internal simulated facts into explicit economic and progress records."""

    rows: list[dict[str, Any]] = []
    for fact in facts.sort_values("asset_identifier", kind="stable").to_dict(orient="records"):
        common = {
            "event_local_identifier": str(fact["execution_identifier"]),
            "time_index": _utc_timestamp(fact["time_index"]),
            "observed_at": _utc_timestamp(fact["observed_at"]),
            "source_identifier": str(fact["execution_identifier"]),
            "source_revision": str(fact["source_revision"]),
            "event_type": "execution",
            "phase": "execution",
            "terms_version": str(fact["terms_version"]),
            "recognized_pnl": 0.0,
        }
        quantity_delta = float(fact["quantity_delta"])
        if not np.isclose(quantity_delta, 0.0, rtol=0.0, atol=1e-15):
            rows.append(
                {
                    **common,
                    "record_kind": "position_delta",
                    "position_identifier": str(fact["position_identifier"]),
                    "asset_identifier": str(fact["asset_identifier"]),
                    "balance_role": "instrument",
                    "quantity_delta": quantity_delta,
                    "quantity_unit": str(fact["quantity_unit"]),
                    "price": float(fact["execution_price"]),
                    "price_asset_identifier": str(fact["price_asset_identifier"]),
                }
            )
        settlement_delta = float(fact["settlement_quantity_delta"])
        if not np.isclose(settlement_delta, 0.0, rtol=0.0, atol=1e-15):
            rows.append(
                {
                    **common,
                    "record_kind": "cash_delta",
                    "asset_identifier": str(fact["settlement_asset_identifier"]),
                    "balance_role": "settled_cash",
                    "quantity_delta": settlement_delta,
                    "quantity_unit": str(fact["settlement_asset_identifier"]),
                    "price": float(fact["execution_price"]),
                    "price_asset_identifier": str(fact["price_asset_identifier"]),
                }
            )
        cost_delta = float(fact["cost_quantity_delta"])
        if not np.isclose(cost_delta, 0.0, rtol=0.0, atol=1e-15):
            rows.append(
                {
                    **common,
                    "record_kind": "cost",
                    "asset_identifier": str(fact["cost_asset_identifier"]),
                    "balance_role": "settled_cash",
                    "quantity_delta": cost_delta,
                    "quantity_unit": str(fact["cost_asset_identifier"]),
                    "recognized_pnl": cost_delta * float(fact["fx_rate"]),
                }
            )
        progress = {
            "schema_version": 1,
            "rebalance_intent_id": str(fact["rebalance_intent_id"]),
            "target_signal_time_index": _utc_timestamp(
                fact["target_signal_time_index"]
            ).isoformat(),
            "event_source": str(fact["event_source"]),
            "execution_status": str(fact["execution_status"]),
            "target_weight": float(fact["signal_target_weight"]),
            "weight_before": float(fact["weight_before"]),
            "weight_after": float(fact["target_weight"]),
            "remaining_weight_delta": float(fact["signal_target_weight"])
            - float(fact["target_weight"]),
            "strategy_state": fact["strategy_state"],
        }
        ledger_cut = float(fact.get("ledger_cut_quantity") or 0.0)
        if ledger_cut and np.isfinite(ledger_cut):
            # The part of the fill the ledger's own cash could not cover (ADR 0058).
            progress["ledger_cut"] = {
                "quantity": ledger_cut,
                "reason": str(fact["ledger_cut_reason"]),
            }
        rows.append(
            {
                **common,
                "record_kind": "execution_progress",
                "state_identifier": f"execution:{fact['asset_identifier']}",
                "asset_identifier": str(fact["asset_identifier"]),
                "extension_payload": json.dumps(
                    progress,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
            }
        )
    return EventBatch.from_frame(pd.DataFrame(rows))


def _progress_only_event_batch(
    context: AccountingExecutionContext,
    *,
    assets: set[str],
    model_identifier: str,
    model_version: str,
) -> EventBatch:
    rows: list[dict[str, Any]] = []
    for asset in sorted(assets):
        execution = context.asset_executions[asset]
        identity = {
            "rebalance_intent_id": context.rebalance_intent_id,
            "time_index": context.time_index.isoformat(),
            "asset_identifier": asset,
            "execution_model": model_identifier,
            "progress_only": True,
        }
        execution_identifier = _digest(identity)
        strategy_state = dict(getattr(execution, "strategy_state", {}) or {})
        source_revision = _digest(
            {
                **identity,
                "model_version": model_version,
                "strategy_revision": context.strategy_revision,
                "input_state_identifier": context.state.state_identifier,
                "signal_target_weight": context.signal_target_weights.get(asset, 0.0),
                "desired_weight": context.desired_weights[asset],
                "weight_before": context.weight_before.get(asset, 0.0),
                "strategy_state": strategy_state,
            }
        )
        progress = {
            "schema_version": 1,
            "rebalance_intent_id": context.rebalance_intent_id,
            "target_signal_time_index": context.signal_time_index.isoformat(),
            "event_source": context.event_source,
            "execution_status": _execution_status(context, asset),
            "target_weight": float(context.signal_target_weights.get(asset, 0.0)),
            "weight_before": float(context.weight_before.get(asset, 0.0)),
            "weight_after": float(context.desired_weights[asset]),
            "remaining_weight_delta": float(
                context.signal_target_weights.get(asset, 0.0)
            )
            - float(context.desired_weights[asset]),
            "strategy_state": strategy_state,
        }
        rows.append(
            {
                "event_local_identifier": execution_identifier,
                "time_index": context.time_index,
                "observed_at": context.time_index,
                "source_identifier": execution_identifier,
                "source_revision": source_revision,
                "event_type": "execution",
                "phase": "execution",
                "record_kind": "execution_progress",
                "state_identifier": f"execution:{asset}",
                "asset_identifier": asset,
                "extension_payload": json.dumps(
                    progress,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "recognized_pnl": 0.0,
            }
        )
    return EventBatch.from_frame(pd.DataFrame(rows))


def _combine_event_batches(batches: list[EventBatch]) -> EventBatch:
    frames = [batch.to_frame() for batch in batches if batch.record_count]
    if not frames:
        return _empty_event_batch()
    combined = pd.concat(frames, ignore_index=True, sort=False)
    combined = combined.sort_values(
        ["event_local_identifier", "record_kind"],
        kind="stable",
    ).reset_index(drop=True)
    return EventBatch.from_frame(combined)


def _execution_status(context: AccountingExecutionContext, asset: str) -> str:
    status = getattr(context.asset_executions.get(asset), "status", None)
    if status is not None:
        return str(status)
    remaining = float(context.signal_target_weights.get(asset, 0.0)) - float(
        context.desired_weights[asset]
    )
    changed = abs(
        float(context.desired_weights[asset]) - float(context.weight_before.get(asset, 0.0))
    )
    if abs(remaining) <= context.completion_tolerance:
        return "complete"
    if changed <= context.completion_tolerance:
        return "pending"
    return "partial"


def _round_to_steps(raw_quantity: np.ndarray, steps: np.ndarray) -> np.ndarray:
    """Round toward zero to whole lot steps, keeping a value already on a step.

    A step of NaN, an instrument without a lot step, keeps the fractional quantity.
    """
    raw_quantity = np.asarray(raw_quantity, dtype="float64")
    steps = np.asarray(steps, dtype="float64")
    fractional = np.isnan(steps)
    lot = np.where(fractional, 1.0, steps)
    scaled_quantity = raw_quantity / lot
    nearest_step = np.rint(scaled_quantity)
    rounded_steps = np.where(
        np.isclose(scaled_quantity, nearest_step, rtol=0.0, atol=1e-12),
        nearest_step,
        np.trunc(scaled_quantity),
    )
    quantity = np.where(fractional, raw_quantity, rounded_steps * lot)
    quantity[np.isclose(quantity, 0.0, rtol=0.0, atol=1e-15)] = 0.0
    return quantity


def _select_execution_marks(
    frame: pd.DataFrame,
    *,
    time_index: pd.Timestamp,
    asset_identifiers: list[str],
    price_column: str,
) -> pd.DataFrame:
    flat = frame.copy().reset_index()
    required = {
        "time_index",
        "asset_identifier",
        price_column,
        "price_asset_identifier",
        "source_revision",
    }
    missing = sorted(required - set(flat.columns))
    if missing:
        raise ValueError("Execution valuations are missing: " + ", ".join(missing))
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
    if flat.duplicated(subset=["time_index", "asset_identifier"]).any():
        raise ValueError("Execution valuations contain duplicate grain coordinates.")
    selected = flat[
        flat["asset_identifier"].astype(str).isin(asset_identifiers)
        & (flat["time_index"] <= time_index)
    ]
    selected = (
        selected.sort_values(["asset_identifier", "time_index"], kind="stable")
        .groupby("asset_identifier", sort=False)
        .tail(1)
    )
    missing_assets = sorted(set(asset_identifiers) - set(selected["asset_identifier"].astype(str)))
    if missing_assets:
        raise ValueError(
            f"No observed price at or before {time_index.isoformat()} for: "
            + ", ".join(missing_assets)
        )
    prices = pd.to_numeric(selected[price_column], errors="raise").astype("float64")
    if not np.isfinite(prices).all() or (prices <= 0.0).any():
        raise ValueError("Execution prices must be finite and strictly positive.")
    selected[price_column] = prices
    selected["asset_identifier"] = selected["asset_identifier"].astype(str)
    selected["price_asset_identifier"] = selected["price_asset_identifier"].astype(str)
    selected["mark_observed_at"] = pd.to_datetime(
        selected.get("observed_at", selected["time_index"]), utc=True
    )
    if (selected["mark_observed_at"] > time_index).any():
        raise ValueError("Execution valuation was observed after its economic timestamp.")
    return selected[
        [
            "asset_identifier",
            price_column,
            "price_asset_identifier",
            "source_revision",
            "mark_observed_at",
        ]
    ]


def _execution_fx_rates(
    asset_identifiers: pd.Series,
    *,
    valuation_asset_identifier: str,
    time_index: pd.Timestamp,
    fx_observations: pd.DataFrame,
) -> tuple[np.ndarray, np.ndarray]:
    assets = asset_identifiers.astype(str).to_numpy()
    foreign = sorted(set(assets) - {valuation_asset_identifier})
    rates = {valuation_asset_identifier: 1.0}
    revisions = {valuation_asset_identifier: "identity"}
    if foreign:
        if fx_observations is None or fx_observations.empty:
            raise ValueError(
                "Missing explicit execution FX into "
                f"{valuation_asset_identifier}: {', '.join(foreign)}"
            )
        flat = fx_observations.copy().reset_index()
        required = {
            "time_index",
            "base_asset_identifier",
            "quote_asset_identifier",
            "rate",
            "source_revision",
        }
        missing = sorted(required - set(flat.columns))
        if missing:
            raise ValueError("Execution FX observations are missing: " + ", ".join(missing))
        flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True)
        if flat.duplicated(
            subset=["time_index", "base_asset_identifier", "quote_asset_identifier"]
        ).any():
            raise ValueError("Execution FX observations contain duplicate grain coordinates.")
        selected = flat[
            flat["base_asset_identifier"].astype(str).isin(foreign)
            & (flat["quote_asset_identifier"].astype(str) == valuation_asset_identifier)
            & (flat["time_index"] <= time_index)
        ]
        selected = (
            selected.sort_values(["base_asset_identifier", "time_index"], kind="stable")
            .groupby("base_asset_identifier", sort=False)
            .tail(1)
        )
        missing_assets = sorted(
            set(foreign) - set(selected["base_asset_identifier"].astype(str))
        )
        if missing_assets:
            raise ValueError(
                "Missing explicit execution FX into "
                f"{valuation_asset_identifier}: {', '.join(missing_assets)}"
            )
        numeric = pd.to_numeric(selected["rate"], errors="raise").astype("float64")
        if not np.isfinite(numeric).all() or (numeric <= 0.0).any():
            raise ValueError("Execution FX rates must be finite and strictly positive.")
        rates.update(
            dict(zip(selected["base_asset_identifier"].astype(str), numeric, strict=True))
        )
        revisions.update(
            dict(
                zip(
                    selected["base_asset_identifier"].astype(str),
                    selected["source_revision"].astype(str),
                    strict=True,
                )
            )
        )
    return (
        np.asarray([rates[asset] for asset in assets], dtype="float64"),
        np.asarray([revisions[asset] for asset in assets], dtype=object),
    )


def _current_quantities(positions: pd.DataFrame, *, specs: pd.DataFrame) -> np.ndarray:
    if positions.empty:
        return np.zeros(len(specs), dtype="float64")
    current = positions.copy()
    current["position_identifier"] = current["position_identifier"].astype(str)
    current["asset_identifier"] = current["asset_identifier"].astype(str)
    current["quantity_unit"] = current["quantity_unit"].astype(str)
    if current["position_identifier"].duplicated().any():
        raise ValueError("Accounting state contains duplicate position identifiers.")
    merged = specs[
        ["position_identifier", "asset_identifier", "quantity_unit"]
    ].merge(
        current[
            ["position_identifier", "asset_identifier", "quantity_unit", "quantity"]
        ],
        on="position_identifier",
        how="left",
        suffixes=("_expected", "_actual"),
        validate="one_to_one",
    )
    present = merged["quantity"].notna()
    mismatched = merged[
        present
        & (
            (merged["asset_identifier_expected"] != merged["asset_identifier_actual"])
            | (merged["quantity_unit_expected"] != merged["quantity_unit_actual"])
        )
    ]
    if not mismatched.empty:
        raise ValueError("Position state disagrees with explicit instrument execution terms.")
    return merged["quantity"].fillna(0.0).to_numpy(dtype="float64")


def _instrument_specs_frame(specs: Iterable[InstrumentExecutionSpec]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                **spec.model_dump(),
                "position_identifier": spec.resolved_position_identifier,
            }
            for spec in specs
        ]
    ).sort_values("asset_identifier", kind="stable")


def _economically_required_execution_assets(
    context: AccountingExecutionContext,
) -> set[str]:
    """Return the filled assets that trade: a nonzero target or a position to change.

    A cancellation with nothing filled carries no price and only records progress.
    """
    held: set[str] = set()
    if not context.state.positions.empty:
        positions = context.state.positions
        held = set(
            positions.loc[
                ~np.isclose(
                    positions["quantity"].to_numpy(dtype="float64"), 0.0, rtol=0.0, atol=1e-15
                ),
                "asset_identifier",
            ].astype(str)
        )
    return {
        str(asset)
        for asset, desired_weight in context.desired_weights.items()
        if getattr(context.asset_executions.get(asset), "execution_price", 0.0) is not None
        and (
            str(asset) in held
            or not np.isclose(float(desired_weight), 0.0, rtol=0.0, atol=1e-15)
        )
    }


def _empty_event_batch() -> EventBatch:
    return EventBatch.from_frame(
        pd.DataFrame(
            columns=[
                "event_local_identifier",
                "time_index",
                "observed_at",
                "source_identifier",
                "source_revision",
                "event_type",
                "phase",
                "record_kind",
            ]
        )
    )


def _market_value_weights(valuation_result: Any) -> dict[str, float]:
    nav = float(valuation_result.nav)
    if not np.isfinite(nav) or nav <= 0.0:
        raise ValueError("Position-aware target-weight execution requires positive finite NAV.")
    components = valuation_result.components
    if components is None or components.empty:
        return {}
    positions = components[components["component_kind"].astype(str) == "position"]
    if positions.empty:
        return {}
    values = positions.groupby("asset_identifier", sort=False)["value"].sum()
    return {str(asset): float(value) / nav for asset, value in values.items()}


def _strategy_observation_reference(
    event_observations: Mapping[str, pd.DataFrame],
    *,
    asset_identifier: str,
    time_index: pd.Timestamp,
) -> tuple[str, pd.Timestamp]:
    references: list[dict[str, Any]] = []
    observed_times: list[pd.Timestamp] = []
    for dependency_name, frame in sorted(event_observations.items()):
        if frame is None or frame.empty:
            continue
        flat = frame.copy().reset_index()
        if "asset_identifier" in flat.columns:
            flat = flat[flat["asset_identifier"].astype(str) == asset_identifier]
        if flat.empty:
            continue
        if "source_revision" not in flat.columns:
            raise ValueError(
                f"Strategy execution observations {dependency_name!r} require source_revision."
            )
        if "time_index" not in flat.columns:
            raise ValueError(
                f"Strategy execution observations {dependency_name!r} require time_index."
            )
        times = pd.to_datetime(flat.get("observed_at", flat["time_index"]), utc=True)
        if (times > time_index).any():
            raise ValueError(
                f"Strategy execution observations {dependency_name!r} contain look-ahead."
            )
        observed_times.extend(_utc_timestamp(value) for value in times)
        records = [
            {
                "time_index": _utc_timestamp(row["time_index"]).isoformat(),
                "source_revision": str(row["source_revision"]),
            }
            for row in flat.to_dict(orient="records")
        ]
        references.append(
            {
                "dependency_name": dependency_name,
                "records": sorted(records, key=lambda value: json.dumps(value, sort_keys=True)),
            }
        )
    if not references:
        return "none", time_index
    return _digest(references), max(observed_times)


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.as_unit("ns")


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


__all__ = [
    "AccountingExecutionContext",
    "ExecutionCostModel",
    "InstrumentExecutionSpec",
    "PositionExecutionModel",
    "ProportionalExecutionCostModel",
    "SettlementStyle",
    "TargetMeasure",
    "TargetWeightExecutionModel",
]
