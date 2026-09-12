"""Directly inject a user-defined vectorized lifecycle cash-flow model."""

from __future__ import annotations

from typing import ClassVar

import numpy as np
import pandas as pd

from msm_portfolios.accounting import (
    CashDeltaBatch,
    EventCandidateBatch,
    LifecycleBatchContext,
    LifecycleInputBatch,
    MarketPriceValuationModel,
    PortfolioAccounting,
    PositionCashFlowModel,
)


class UsageRoyalty(PositionCashFlowModel):
    """Example customer model: charge a EUR royalty for observed usage."""

    model_identifier: ClassVar[str] = "example.usage_royalty"
    model_version: ClassVar[str] = "1"
    configuration_schema_version: ClassVar[int] = 1

    rate_per_unit: float
    dependency_name: str = "usage"

    def select_event_candidates(self, inputs: LifecycleInputBatch) -> EventCandidateBatch:
        usage = inputs.frames[self.dependency_name].copy().reset_index()
        frame = pd.DataFrame(
            {
                "event_local_identifier": usage["usage_event_identifier"].astype(str),
                "time_index": usage["time_index"],
                "observed_at": usage["observed_at"],
                "source_identifier": usage["usage_event_identifier"].astype(str),
                "source_revision": usage["source_revision"].astype(str),
                "event_type": "usage_royalty",
                "phase": "pre_execution",
                "usage_units": usage["usage_units"].astype("float64"),
                "settlement_asset_identifier": usage["settlement_asset_identifier"].astype(str),
            }
        )
        return EventCandidateBatch(frame)

    def vectorization_keys(self, candidates: EventCandidateBatch) -> tuple[str, ...]:
        del candidates
        return ("settlement_asset_identifier",)

    def calculate_cash_deltas(self, context: LifecycleBatchContext) -> CashDeltaBatch:
        candidates = context.candidates
        amounts = -candidates["usage_units"].to_numpy(dtype="float64") * self.rate_per_unit
        return CashDeltaBatch(
            event_local_identifier=candidates["event_local_identifier"].to_numpy(),
            amount_delta=amounts,
            amount_asset_identifier=candidates["settlement_asset_identifier"].to_numpy(),
            balance_role=np.repeat("settled_cash", len(candidates)),
            recognized_pnl=amounts,
        )


def build_example() -> pd.DataFrame:
    usage = pd.DataFrame(
        [
            (
                "2026-02-01T12:00:00Z",
                "royalty-contract-a",
                "1",
                "2026-02-01T12:00:00Z",
                10.0,
                "EUR",
            ),
            (
                "2026-02-01T12:00:00Z",
                "royalty-contract-b",
                "1",
                "2026-02-01T12:00:00Z",
                20.0,
                "EUR",
            ),
        ],
        columns=[
            "time_index",
            "usage_event_identifier",
            "source_revision",
            "observed_at",
            "usage_units",
            "settlement_asset_identifier",
        ],
    )
    fx = pd.DataFrame(
        [
            (
                "2026-02-01T12:00:00Z",
                "EUR",
                "USD",
                1.20,
                "eur-usd-1",
            )
        ],
        columns=[
            "time_index",
            "base_asset_identifier",
            "quote_asset_identifier",
            "rate",
            "source_revision",
        ],
    )
    model = UsageRoyalty(rate_per_unit=2.0)
    accounting = PortfolioAccounting(
        portfolio_identifier="mock-custom-cash-flow",
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-31T12:00:00Z",
        valuation_model=MarketPriceValuationModel(),
    )
    return accounting.run(
        valuation_observations=pd.DataFrame(),
        fx_observations=fx,
        lifecycle_models=(model,),
        lifecycle_inputs={model.model_identifier: {"usage": usage}},
        valuation_times=("2026-02-01T12:00:00Z",),
    )


def main() -> None:
    ledger = build_example()
    summaries = ledger.query("record_kind == 'valuation_summary'")
    print(summaries[["event_type", "recognized_pnl", "nav_after"]].to_string(index=False))


if __name__ == "__main__":
    main()
