"""Serializable lifecycle-event extension models."""

from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from typing import ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater

from .contracts import (
    CashDeltaBatch,
    EventBatch,
    EventCandidateBatch,
    LifecycleAlignmentContract,
    LifecycleBatchContext,
    LifecycleInputBatch,
    LifecycleInputContract,
    LifecycleStateContract,
    SourceWindow,
)


LifecycleDependency = TimeIndexTableUpdater | TimeIndexTableRef


class LifecycleEventModel(BaseModel, ABC):
    """Public, pure, directly injected lifecycle-model boundary."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_identifier: ClassVar[str]
    model_version: ClassVar[str] = "1"
    configuration_schema_version: ClassVar[int] = 1
    economic_ordering_priority: ClassVar[int] = 0

    def declared_dependencies(self) -> dict[str, LifecycleDependency]:
        return {}

    def required_input_contracts(self) -> dict[str, LifecycleInputContract]:
        return {}

    def dependency_window(
        self,
        dependency_name: str,
        start: dt.datetime | pd.Timestamp,
        end: dt.datetime | pd.Timestamp,
    ) -> SourceWindow:
        del dependency_name
        return SourceWindow(start=start, end=end)

    def alignment_contracts(self) -> dict[str, LifecycleAlignmentContract]:
        return {}

    def lifecycle_state_contract(self) -> LifecycleStateContract | None:
        return None

    @abstractmethod
    def select_event_candidates(self, inputs: LifecycleInputBatch) -> EventCandidateBatch:
        """Select source-backed economic candidates without emitting ledger rows."""

    def vectorization_keys(self, candidates: EventCandidateBatch) -> tuple[str, ...]:
        del candidates
        return ()

    @abstractmethod
    def build_event_batch(self, context: LifecycleBatchContext) -> EventBatch:
        """Build one flat record batch for an aligned compatible partition."""

    @classmethod
    def validate_extension_contract(cls) -> None:
        if not getattr(cls, "model_identifier", ""):
            raise TypeError(f"{cls.__name__} must declare a stable model_identifier.")
        if "<locals>" in cls.__qualname__:
            raise TypeError("LifecycleEventModel implementations must be module-level classes.")
        if cls.configuration_schema_version < 1:
            raise TypeError("configuration_schema_version must be positive.")


class PositionCashFlowModel(LifecycleEventModel, ABC):
    """Convenience base for lifecycle events whose only posting is settled cash."""

    @abstractmethod
    def calculate_cash_deltas(self, context: LifecycleBatchContext) -> CashDeltaBatch:
        """Calculate one vectorized cash result for the supplied candidate partition."""

    def build_event_batch(self, context: LifecycleBatchContext) -> EventBatch:
        cash = self.calculate_cash_deltas(context)
        candidates = context.candidates.reset_index(drop=True)
        local_ids = np.asarray(cash.event_local_identifier).astype(str)
        by_id = candidates.set_index("event_local_identifier", drop=False)
        selected = by_id.loc[local_ids].reset_index(drop=True)
        rows = pd.DataFrame(
            {
                "event_local_identifier": local_ids,
                "time_index": selected["time_index"],
                "observed_at": selected["observed_at"],
                "source_identifier": selected["source_identifier"].astype(str),
                "source_revision": selected["source_revision"].astype(str),
                "event_type": selected["event_type"].astype(str),
                "phase": selected["phase"].astype(str),
                "record_kind": "cash_delta",
                "asset_identifier": np.asarray(cash.amount_asset_identifier).astype(str),
                "quantity_delta": np.asarray(cash.amount_delta, dtype=np.float64),
                "quantity_unit": np.asarray(cash.amount_asset_identifier).astype(str),
                "amount_delta": np.asarray(cash.amount_delta, dtype=np.float64),
                "amount_asset_identifier": np.asarray(cash.amount_asset_identifier).astype(str),
                "balance_role": np.asarray(cash.balance_role).astype(str),
                "recognized_pnl": np.asarray(cash.recognized_pnl, dtype=np.float64),
            }
        )
        return EventBatch.from_frame(rows)


class DividendCashFlowModel(LifecycleEventModel):
    """Recognize dividend receivables at entitlement and settle them at payment."""

    model_identifier: ClassVar[str] = "msm.dividend_cash_flow"
    model_version: ClassVar[str] = "1"
    configuration_schema_version: ClassVar[int] = 1

    dividend_source: LifecycleDependency | None = Field(
        default=None,
        description="Declared dividend observation source; optional only for in-memory calculation.",
        exclude=True,
    )
    dependency_name: str = "dividends"
    quantity_unit: str = "units"

    def declared_dependencies(self) -> dict[str, LifecycleDependency]:
        if self.dividend_source is None:
            return {}
        return {self.dependency_name: self.dividend_source}

    def required_input_contracts(self) -> dict[str, LifecycleInputContract]:
        return {
            self.dependency_name: LifecycleInputContract(
                index_names=("time_index", "source_event_identifier", "source_revision"),
                required_columns=(
                    "observed_at",
                    "asset_identifier",
                    "entitlement_time_index",
                    "payment_time_index",
                    "amount_per_unit",
                    "settlement_asset_identifier",
                ),
            )
        }

    def alignment_contracts(self) -> dict[str, LifecycleAlignmentContract]:
        return {
            self.dependency_name: LifecycleAlignmentContract(
                mode="event_to_position",
                left_on=("asset_identifier", "entitlement_time_index"),
                right_on=("asset_identifier", "time_index"),
            )
        }

    def select_event_candidates(self, inputs: LifecycleInputBatch) -> EventCandidateBatch:
        frame = inputs.frames.get(self.dependency_name)
        if frame is None or frame.empty:
            return EventCandidateBatch.empty()
        flat = frame.copy().reset_index()
        required = set(self.required_input_contracts()[self.dependency_name].required_columns) | {
            "source_event_identifier",
            "source_revision",
        }
        missing = sorted(required - set(flat.columns))
        if missing:
            raise ValueError("Dividend observations are missing columns: " + ", ".join(missing))
        for column in ("entitlement_time_index", "payment_time_index", "observed_at"):
            flat[column] = pd.to_datetime(flat[column], utc=True).astype("datetime64[ns, UTC]")
        numeric = pd.to_numeric(flat["amount_per_unit"], errors="raise").astype("float64")
        if not np.isfinite(numeric).all():
            raise ValueError("Dividend amount_per_unit values must be finite.")
        flat["amount_per_unit"] = numeric
        identity = flat["source_event_identifier"].astype(str)
        common = {
            "observed_at": flat["observed_at"],
            "source_identifier": identity,
            "source_revision": flat["source_revision"].astype(str),
            "asset_identifier": flat["asset_identifier"].astype(str),
            "amount_per_unit": flat["amount_per_unit"],
            "settlement_asset_identifier": flat["settlement_asset_identifier"].astype(str),
            "quantity_unit": self.quantity_unit,
        }
        recognition = pd.DataFrame(
            {
                **common,
                "event_local_identifier": identity + ":entitlement",
                "time_index": flat["entitlement_time_index"],
                "event_type": "entitlement",
                "phase": "pre_execution",
                "lifecycle_step": "recognition",
            }
        )
        settlement = pd.DataFrame(
            {
                **common,
                "event_local_identifier": identity + ":settlement",
                "time_index": flat["payment_time_index"],
                "event_type": "settlement",
                "phase": "pre_execution",
                "lifecycle_step": "settlement",
            }
        )
        candidates = pd.concat([recognition, settlement], ignore_index=True)
        return EventCandidateBatch(
            candidates.sort_values(["time_index", "event_local_identifier"], kind="stable")
        )

    def vectorization_keys(self, candidates: EventCandidateBatch) -> tuple[str, ...]:
        del candidates
        return ("lifecycle_step", "settlement_asset_identifier", "quantity_unit")

    def build_event_batch(self, context: LifecycleBatchContext) -> EventBatch:
        candidates = context.candidates.reset_index(drop=True)
        steps = set(candidates["lifecycle_step"].astype(str))
        if len(steps) != 1:
            raise ValueError("Dividend batches must contain one lifecycle_step.")
        step = next(iter(steps))
        if step == "recognition":
            return self._recognition_batch(candidates, context)
        if step == "settlement":
            return self._settlement_batch(candidates, context)
        raise ValueError(f"Unsupported dividend lifecycle step {step!r}.")

    def _recognition_batch(
        self,
        candidates: pd.DataFrame,
        context: LifecycleBatchContext,
    ) -> EventBatch:
        positions = context.state.positions
        quantities = pd.Series(0.0, index=candidates.index, dtype="float64")
        if not positions.empty:
            by_asset = positions.groupby("asset_identifier", sort=False)["quantity"].sum()
            quantities = candidates["asset_identifier"].map(by_asset).fillna(0.0).astype("float64")
        amounts = quantities.to_numpy() * candidates["amount_per_unit"].to_numpy(dtype="float64")
        rows = candidates[
            [
                "event_local_identifier",
                "time_index",
                "observed_at",
                "source_identifier",
                "source_revision",
                "event_type",
                "phase",
            ]
        ].copy()
        rows["record_kind"] = "obligation_delta"
        rows["obligation_identifier"] = "dividend:" + candidates["source_identifier"].astype(str)
        rows["asset_identifier"] = candidates["settlement_asset_identifier"].astype(str)
        rows["balance_role"] = "receivable"
        rows["quantity_delta"] = amounts
        rows["quantity_unit"] = candidates["settlement_asset_identifier"].astype(str)
        rows["eligible_quantity"] = quantities
        rows["recognized_pnl"] = amounts
        rows["originating_asset_identifier"] = candidates["asset_identifier"].astype(str)
        return EventBatch.from_frame(rows)

    def _settlement_batch(
        self,
        candidates: pd.DataFrame,
        context: LifecycleBatchContext,
    ) -> EventBatch:
        obligations = context.state.obligations
        obligation_ids = "dividend:" + candidates["source_identifier"].astype(str)
        if obligations.empty:
            raise ValueError("Dividend settlement has no recognized receivable.")
        by_id = obligations.set_index("obligation_identifier")["quantity"]
        missing = sorted(set(obligation_ids) - set(by_id.index.astype(str)))
        if missing:
            raise ValueError("Dividend settlement is missing receivables: " + ", ".join(missing))
        amounts = obligation_ids.map(by_id).to_numpy(dtype="float64")
        if np.any(amounts < 0):
            raise ValueError("Dividend settlement cannot consume a negative receivable.")
        envelope = candidates[
            [
                "event_local_identifier",
                "time_index",
                "observed_at",
                "source_identifier",
                "source_revision",
                "event_type",
                "phase",
            ]
        ].copy()
        obligation_rows = envelope.copy()
        obligation_rows["record_kind"] = "obligation_delta"
        obligation_rows["obligation_identifier"] = obligation_ids
        obligation_rows["asset_identifier"] = candidates["settlement_asset_identifier"].astype(str)
        obligation_rows["balance_role"] = "receivable"
        obligation_rows["quantity_delta"] = -amounts
        obligation_rows["quantity_unit"] = candidates["settlement_asset_identifier"].astype(str)
        obligation_rows["recognized_pnl"] = 0.0

        cash_rows = envelope.copy()
        cash_rows["record_kind"] = "cash_delta"
        cash_rows["asset_identifier"] = candidates["settlement_asset_identifier"].astype(str)
        cash_rows["balance_role"] = "settled_cash"
        cash_rows["quantity_delta"] = amounts
        cash_rows["quantity_unit"] = candidates["settlement_asset_identifier"].astype(str)
        cash_rows["recognized_pnl"] = 0.0
        rows = pd.concat([obligation_rows, cash_rows], ignore_index=True).sort_values(
            ["event_local_identifier", "record_kind"], kind="stable"
        )
        return EventBatch.from_frame(rows.reset_index(drop=True))


__all__ = [
    "DividendCashFlowModel",
    "LifecycleDependency",
    "LifecycleEventModel",
    "PositionCashFlowModel",
]
