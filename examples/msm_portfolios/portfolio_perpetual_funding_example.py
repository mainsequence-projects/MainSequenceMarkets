"""Linear perpetual backtest with pre-execution funding and variation margin.

Run with:
    uv run --extra portfolios python examples/msm_portfolios/portfolio_perpetual_funding_example.py
"""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd

from msm_portfolios.accounting import (
    AccountingStateView,
    CashDeltaBatch,
    EventCandidateBatch,
    LifecycleBatchContext,
    LifecycleInputBatch,
    MarketPriceValuationModel,
    PortfolioAccountingConfiguration,
    PositionCashFlowModel,
    PositionValuationModel,
    ValuationResult,
)
from msm_portfolios.data_nodes import PortfolioEngine
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    InstrumentExecutionSpec,
    ProportionalExecutionCostModel,
    TargetWeightExecutionModel,
)


class PerpetualFundingCashFlowModel(PositionCashFlowModel):
    """Debit funding from the position that exists before same-time rebalancing."""

    model_identifier: ClassVar[str] = "example.perpetual_funding"
    model_version: ClassVar[str] = "1"
    configuration_schema_version: ClassVar[int] = 1

    dependency_name: str = "funding"

    def select_event_candidates(self, inputs: LifecycleInputBatch) -> EventCandidateBatch:
        funding = inputs.frames[self.dependency_name].copy().reset_index()
        return EventCandidateBatch(
            pd.DataFrame(
                {
                    "event_local_identifier": funding["funding_event_identifier"].astype(str),
                    "time_index": funding["time_index"],
                    "observed_at": funding["observed_at"],
                    "source_identifier": funding["funding_event_identifier"].astype(str),
                    "source_revision": funding["source_revision"].astype(str),
                    "event_type": "perpetual_funding",
                    "phase": "pre_execution",
                    "asset_identifier": funding["asset_identifier"].astype(str),
                    "mark_price": funding["mark_price"].astype("float64"),
                    "funding_rate": funding["funding_rate"].astype("float64"),
                    "settlement_asset_identifier": funding[
                        "settlement_asset_identifier"
                    ].astype(str),
                }
            )
        )

    def vectorization_keys(self, candidates: EventCandidateBatch) -> tuple[str, ...]:
        del candidates
        return ("settlement_asset_identifier",)

    def calculate_cash_deltas(self, context: LifecycleBatchContext) -> CashDeltaBatch:
        candidates = context.candidates
        quantities = pd.Series(0.0, index=candidates.index, dtype="float64")
        if not context.state.positions.empty:
            by_asset = context.state.positions.groupby("asset_identifier", sort=False)[
                "quantity"
            ].sum()
            quantities = (
                candidates["asset_identifier"].map(by_asset).fillna(0.0).astype("float64")
            )
        amounts = -(
            np.abs(quantities.to_numpy())
            * candidates["mark_price"].to_numpy(dtype="float64")
            * candidates["funding_rate"].to_numpy(dtype="float64")
        )
        return CashDeltaBatch(
            event_local_identifier=candidates["event_local_identifier"].to_numpy(),
            amount_delta=amounts,
            amount_asset_identifier=candidates[
                "settlement_asset_identifier"
            ].to_numpy(),
            balance_role=np.repeat("settled_cash", len(candidates)),
            recognized_pnl=amounts,
        )


class VariationMarginValuationModel(PositionValuationModel):
    """Value linear perpetual positions at zero between variation-margin events."""

    model_identifier: ClassVar[str] = "example.variation_margin_valuation"
    model_version: ClassVar[str] = "1"

    def value(
        self,
        *,
        state: AccountingStateView,
        time_index: pd.Timestamp,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> ValuationResult:
        cash_state = AccountingStateView(
            positions=state.positions.iloc[0:0].copy(),
            cash=state.cash,
            obligations=state.obligations,
            lifecycle_state=state.lifecycle_state,
            execution_progress=state.execution_progress,
            state_identifier=state.state_identifier,
        )
        return MarketPriceValuationModel().value(
            state=cash_state,
            time_index=time_index,
            valuation_asset_identifier=valuation_asset_identifier,
            valuation_observations=valuation_observations,
            fx_observations=fx_observations,
        )


def build_example() -> dict[str, pd.DataFrame]:
    """Open ten contracts, pay costs/funding, resize, then fund without rebalancing."""

    prices = pd.DataFrame(
        [
            ("2026-03-01T00:00:00Z", "BTC-PERP", 100.0, "USD", "mark-1"),
            ("2026-03-02T00:00:00Z", "BTC-PERP", 100.0, "USD", "mark-2"),
            ("2026-03-03T00:00:00Z", "BTC-PERP", 100.0, "USD", "mark-3"),
        ],
        columns=[
            "time_index",
            "asset_identifier",
            "price",
            "price_asset_identifier",
            "source_revision",
        ],
    )
    signals = pd.DataFrame(
        [
            ("2026-03-01T00:00:00Z", "perpetual-signal", "BTC-PERP", 1.0),
            ("2026-03-02T00:00:00Z", "perpetual-signal", "BTC-PERP", 1.0),
        ],
        columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
    ).set_index(["time_index", "signal_uid", "asset_identifier"])
    funding = pd.DataFrame(
        [
            (
                "2026-03-02T00:00:00Z",
                "btc-funding-1",
                "1",
                "2026-03-02T00:00:00Z",
                "BTC-PERP",
                100.0,
                0.10,
                "USD",
            ),
            (
                "2026-03-03T00:00:00Z",
                "btc-funding-2",
                "1",
                "2026-03-03T00:00:00Z",
                "BTC-PERP",
                100.0,
                0.01,
                "USD",
            ),
        ],
        columns=[
            "time_index",
            "funding_event_identifier",
            "source_revision",
            "observed_at",
            "asset_identifier",
            "mark_price",
            "funding_rate",
            "settlement_asset_identifier",
        ],
    )
    funding_model = PerpetualFundingCashFlowModel()
    configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-02-28T00:00:00Z",
        position_valuation_model_instance=VariationMarginValuationModel(),
        lifecycle_event_model_instances=(funding_model,),
    )
    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="BTC-PERP",
                    quantity_unit="contracts",
                    target_measure="notional_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="USD",
                    settlement_style="variation_margin",
                    terms_version="linear-perpetual-v1",
                ),
            )
        ),
        execution_cost_model_instances=(ProportionalExecutionCostModel(rate=0.01),),
    )
    accounting = PortfolioEngine.calculate_backtest(
        portfolio_identifier="mock-linear-perpetual",
        accounting_configuration=configuration,
        rebalance_strategy=strategy,
        signal_observations=signals,
        rebalance_inputs={},
        valuation_observations=prices,
        lifecycle_inputs={funding_model.model_identifier: {"funding": funding}},
        valuation_times=("2026-03-03T00:00:00Z",),
    )
    return {
        "ledger": accounting.ledger,
        "positions": accounting.state.positions,
        "cash": accounting.state.cash,
        "execution_progress": accounting.state.execution_progress,
    }


def main() -> None:
    result = build_example()
    executions = result["ledger"].query("event_type == 'execution'")
    print("Simulated execution records:")
    print(
        executions[
            [
                "time_index",
                "record_kind",
                "quantity_delta",
                "asset_identifier",
                "nav_before",
                "nav_after",
            ]
        ].to_string(index=False)
    )
    print("\nEnding position:")
    print(result["positions"].to_string(index=False))
    print("\nEnding cash after commissions and funding:")
    print(result["cash"].to_string(index=False))


if __name__ == "__main__":
    main()
