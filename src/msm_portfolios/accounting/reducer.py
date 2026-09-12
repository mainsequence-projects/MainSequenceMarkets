"""Deterministic position-aware accounting coordinator and reducer."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

from .contracts import (
    AccountingStateView,
    EventBatch,
    EventCandidateBatch,
    LifecycleBatchContext,
    LifecycleInputBatch,
)
from .lifecycle import LifecycleEventModel
from .valuation import PositionValuationModel, ValuationResult


PHASE_ORDER = {"pre_execution": 0, "execution": 1, "post_execution": 2}
ECONOMIC_RECORD_KINDS = frozenset(
    {"position_delta", "cash_delta", "obligation_delta", "lifecycle_state", "cost"}
)


class CorrectionReplayRequired(RuntimeError):
    """Raised when an existing economic event arrives with a new source revision."""


@dataclass
class _AccountingState:
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)
    cash: dict[str, dict[str, Any]] = field(default_factory=dict)
    obligations: dict[str, dict[str, Any]] = field(default_factory=dict)
    lifecycle_state: dict[str, dict[str, Any]] = field(default_factory=dict)
    applied_events: dict[str, str] = field(default_factory=dict)
    event_sequence: int = 0
    last_nav: float | None = None

    def view(self) -> AccountingStateView:
        return AccountingStateView(
            positions=_state_frame(
                self.positions,
                columns=(
                    "position_identifier",
                    "asset_identifier",
                    "balance_role",
                    "quantity",
                    "quantity_unit",
                ),
            ),
            cash=_state_frame(
                self.cash,
                columns=(
                    "state_identifier",
                    "asset_identifier",
                    "balance_role",
                    "quantity",
                    "quantity_unit",
                ),
            ),
            obligations=_state_frame(
                self.obligations,
                columns=(
                    "obligation_identifier",
                    "asset_identifier",
                    "balance_role",
                    "quantity",
                    "quantity_unit",
                ),
            ),
            lifecycle_state=_state_frame(
                self.lifecycle_state,
                columns=("state_identifier", "state_schema_version", "extension_payload"),
            ),
            state_identifier=self.identifier(),
        )

    def identifier(self) -> str:
        payload = {
            "positions": _sorted_state(self.positions),
            "cash": _sorted_state(self.cash),
            "obligations": _sorted_state(self.obligations),
            "lifecycle_state": _sorted_state(self.lifecycle_state),
            "applied_events": sorted(self.applied_events.items()),
        }
        return _digest(payload)


class PortfolioAccounting:
    """Pure accounting state machine whose output is a canonical long ledger."""

    def __init__(
        self,
        *,
        portfolio_identifier: str,
        valuation_asset_identifier: str,
        initial_nav: float,
        initial_state_time_index: pd.Timestamp | str,
        valuation_model: PositionValuationModel,
        balance_tolerance: float = 1e-9,
        historical_information_mode: str = "as_known",
    ) -> None:
        if not portfolio_identifier:
            raise ValueError("portfolio_identifier is required.")
        if not valuation_asset_identifier:
            raise ValueError("valuation_asset_identifier is required.")
        initial_nav = float(initial_nav)
        if not np.isfinite(initial_nav) or initial_nav <= 0:
            raise ValueError("initial_nav must be finite and strictly positive.")
        self.portfolio_identifier = str(portfolio_identifier)
        self.valuation_asset_identifier = str(valuation_asset_identifier)
        self.initial_nav = initial_nav
        self.initial_state_time_index = _utc_timestamp(initial_state_time_index)
        self.valuation_model = valuation_model
        self.balance_tolerance = float(balance_tolerance)
        if historical_information_mode != "as_known":
            raise NotImplementedError(
                "Corrected-history tail replay is not implemented; use as_known mode."
            )
        self.historical_information_mode = historical_information_mode
        self._state = _AccountingState()
        self._ledger_parts: list[pd.DataFrame] = []
        self._initialized = False

    @classmethod
    def from_ledger(
        cls,
        *,
        ledger: pd.DataFrame,
        portfolio_identifier: str,
        valuation_asset_identifier: str,
        initial_nav: float,
        initial_state_time_index: pd.Timestamp | str,
        valuation_model: PositionValuationModel,
        balance_tolerance: float = 1e-9,
        historical_information_mode: str = "as_known",
    ) -> PortfolioAccounting:
        """Reconstruct reducer state from a complete, active canonical ledger."""

        accounting = cls(
            portfolio_identifier=portfolio_identifier,
            valuation_asset_identifier=valuation_asset_identifier,
            initial_nav=initial_nav,
            initial_state_time_index=initial_state_time_index,
            valuation_model=valuation_model,
            balance_tolerance=balance_tolerance,
            historical_information_mode=historical_information_mode,
        )
        flat = ledger.copy()
        if not set(_LEDGER_COLUMNS).issubset(flat.columns):
            flat = flat.reset_index()
        else:
            flat = flat.reset_index(drop=True)
        missing = sorted(set(_LEDGER_COLUMNS) - set(flat.columns))
        if missing:
            raise ValueError(
                "Portfolio event ledger is missing canonical columns: " + ", ".join(missing)
            )
        if flat.empty:
            raise ValueError("Cannot reconstruct accounting state from an empty ledger.")
        portfolios = set(flat["portfolio_identifier"].astype(str))
        if portfolios != {accounting.portfolio_identifier}:
            raise ValueError(
                "Ledger portfolio identity does not match the requested accounting state."
            )
        if set(flat["event_status"].astype(str)) != {"active"}:
            raise NotImplementedError(
                "Restart from superseded ledger revisions requires corrected-history tail replay."
            )

        sequence_values = pd.to_numeric(flat["event_sequence"], errors="raise").astype("int64")
        flat["event_sequence"] = sequence_values
        event_sequences = sorted(sequence_values.unique())
        if event_sequences != list(range(1, len(event_sequences) + 1)):
            raise ValueError("Canonical ledger event_sequence values must be contiguous from one.")

        first_event: pd.DataFrame | None = None
        for event_sequence, event in flat.groupby("event_sequence", sort=True):
            event = event.sort_values("record_sequence", kind="stable").reset_index(drop=True)
            if first_event is None:
                first_event = event
            for column in (
                "event_identifier",
                "event_revision",
                "source_revision",
                "input_state_identifier",
                "ledger_state_identifier",
                "event_digest",
                "event_record_count",
            ):
                if event[column].nunique(dropna=False) != 1:
                    raise ValueError(
                        f"Ledger event_sequence {event_sequence} has inconsistent {column}."
                    )
            if int(event["event_record_count"].iloc[0]) != len(event):
                raise ValueError("Portfolio event ledger contains an incomplete event group.")
            expected_record_sequence = list(range(len(event)))
            if event["record_sequence"].astype("int64").tolist() != expected_record_sequence:
                raise ValueError("Canonical ledger record_sequence values must be contiguous.")
            if event_digest(event) != str(event["event_digest"].iloc[0]):
                raise ValueError("Portfolio event ledger event_digest does not match its records.")
            summaries = event[event["record_kind"] == "valuation_summary"]
            if len(summaries) != 1:
                raise ValueError("Every canonical ledger event requires one valuation summary.")
            if str(event["input_state_identifier"].iloc[0]) != accounting._state.identifier():
                raise ValueError("Portfolio event ledger has a broken input-state chain.")

            accounting._apply_records(event)
            event_identifier = str(event["event_identifier"].iloc[0])
            accounting._state.applied_events[event_identifier] = str(
                event["source_revision"].iloc[0]
            )
            if str(event["ledger_state_identifier"].iloc[0]) != accounting._state.identifier():
                raise ValueError("Portfolio event ledger has a broken output-state chain.")
            accounting._state.event_sequence = int(event_sequence)
            accounting._state.last_nav = float(summaries["nav_after"].iloc[0])
            accounting._ledger_parts.append(event[list(_LEDGER_COLUMNS)].copy())

        assert first_event is not None
        if set(first_event["event_type"].astype(str)) != {"opening_state"}:
            raise ValueError("Canonical ledger must begin with the opening-state event.")
        opening_cash = first_event[first_event["record_kind"] == "cash_delta"]
        if len(opening_cash) != 1:
            raise ValueError("Opening-state event must contain exactly one cash balance record.")
        opening_row = opening_cash.iloc[0]
        if (
            _utc_timestamp(opening_row["time_index"]) != accounting.initial_state_time_index
            or str(opening_row["asset_identifier"]) != accounting.valuation_asset_identifier
            or not np.isclose(
                float(opening_row["quantity_delta"]),
                accounting.initial_nav,
                rtol=0.0,
                atol=accounting.balance_tolerance,
            )
        ):
            raise ValueError("Ledger opening state does not match accounting configuration.")
        accounting._initialized = True
        return accounting

    @property
    def state(self) -> AccountingStateView:
        return self._state.view()

    @property
    def ledger(self) -> pd.DataFrame:
        if not self._ledger_parts:
            return pd.DataFrame()
        return pd.concat(self._ledger_parts, ignore_index=True)

    def initialize(
        self,
        *,
        valuation_observations: pd.DataFrame | None = None,
        fx_observations: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        if self._initialized:
            return pd.DataFrame()
        batch = opening_cash_event_batch(
            time_index=self.initial_state_time_index,
            amount=self.initial_nav,
            asset_identifier=self.valuation_asset_identifier,
        )
        result = self.apply_event_batch(
            batch,
            model_identifier="msm.opening_state",
            model_version="1",
            valuation_observations=_empty_if_none(valuation_observations),
            fx_observations=_empty_if_none(fx_observations),
        )
        self._initialized = True
        return result

    def run(
        self,
        *,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame | None = None,
        execution_facts: pd.DataFrame | None = None,
        lifecycle_models: Iterable[LifecycleEventModel] = (),
        lifecycle_inputs: Mapping[str, Mapping[str, pd.DataFrame]] | None = None,
        valuation_times: Iterable[pd.Timestamp | str] = (),
    ) -> pd.DataFrame:
        """Run a deterministic time scan and vectorize within compatible groups."""

        fx = _empty_if_none(fx_observations)
        self.initialize(
            valuation_observations=valuation_observations,
            fx_observations=fx,
        )
        inputs_by_model = dict(lifecycle_inputs or {})
        models = tuple(lifecycle_models)
        candidates_by_model: dict[str, pd.DataFrame] = {}
        seen_model_ids: set[str] = set()
        for model in models:
            model.validate_extension_contract()
            if model.model_identifier in seen_model_ids:
                raise ValueError(
                    f"Duplicate lifecycle model_identifier {model.model_identifier!r}."
                )
            seen_model_ids.add(model.model_identifier)
            provided = inputs_by_model.get(model.model_identifier, {})
            candidates = model.select_event_candidates(LifecycleInputBatch(provided)).frame
            if (
                not candidates.empty
                and (candidates["observed_at"] > candidates["time_index"]).any()
            ):
                raise ValueError(
                    f"{model.model_identifier} contains an event observed after its economic "
                    "time; as_known calculation cannot use that revision without look-ahead."
                )
            candidates_by_model[model.model_identifier] = candidates

        _reject_cross_model_event_ownership(candidates_by_model)

        executions = _normalize_execution_facts(execution_facts)
        times: set[pd.Timestamp] = {_utc_timestamp(value) for value in valuation_times}
        if not executions.empty:
            times.update(pd.DatetimeIndex(executions["time_index"]))
        for candidates in candidates_by_model.values():
            if not candidates.empty:
                times.update(pd.DatetimeIndex(candidates["time_index"]))
        times.discard(self.initial_state_time_index)

        model_map = {model.model_identifier: model for model in models}
        ordered_model_identifiers = sorted(
            model_map,
            key=lambda identifier: (
                model_map[identifier].economic_ordering_priority,
                identifier,
            ),
        )
        for timestamp in sorted(times):
            for phase in ("pre_execution", "execution", "post_execution"):
                if phase == "execution" and not executions.empty:
                    selected = executions[executions["time_index"] == timestamp]
                    if not selected.empty:
                        self.apply_event_batch(
                            execution_event_batch(selected),
                            model_identifier="msm.execution_fact",
                            model_version="1",
                            valuation_observations=valuation_observations,
                            fx_observations=fx,
                        )
                for model_identifier in ordered_model_identifiers:
                    model = model_map[model_identifier]
                    candidates = candidates_by_model[model_identifier]
                    selected = candidates[
                        (candidates["time_index"] == timestamp)
                        & (candidates["phase"].astype(str) == phase)
                    ]
                    if selected.empty:
                        continue
                    self._run_model_candidates(
                        model,
                        selected,
                        valuation_observations=valuation_observations,
                        fx_observations=fx,
                    )
            if timestamp in {_utc_timestamp(value) for value in valuation_times}:
                self.apply_event_batch(
                    valuation_marker_event_batch(timestamp),
                    model_identifier=self.valuation_model.model_identifier,
                    model_version=self.valuation_model.model_version,
                    valuation_observations=valuation_observations,
                    fx_observations=fx,
                )
        return self.ledger

    def _run_model_candidates(
        self,
        model: LifecycleEventModel,
        candidates: pd.DataFrame,
        *,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> None:
        candidate_batch = EventCandidateBatch(candidates)
        model_keys = model.vectorization_keys(candidate_batch)
        missing_keys = sorted(set(model_keys) - set(candidates.columns))
        if missing_keys:
            raise ValueError(
                f"{model.model_identifier} vectorization keys are missing: "
                + ", ".join(missing_keys)
            )
        signature_keys = ["event_type", "phase", *model_keys]
        grouped = candidates.groupby(signature_keys, sort=True, dropna=False)
        for _, partition in grouped:
            context = LifecycleBatchContext(
                candidates=partition.reset_index(drop=True),
                state=self.state,
                valuation_context=None,
            )
            batch = model.build_event_batch(context)
            self.apply_event_batch(
                batch,
                model_identifier=model.model_identifier,
                model_version=model.model_version,
                valuation_observations=valuation_observations,
                fx_observations=fx_observations,
            )

    def apply_event_batch(
        self,
        batch: EventBatch,
        *,
        model_identifier: str,
        model_version: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> pd.DataFrame:
        """Validate, apply, value, and canonicalize every complete event segment."""

        if batch.record_count == 0:
            return pd.DataFrame()
        raw = batch.to_frame()
        parts: list[pd.DataFrame] = []
        for start, end in zip(batch.event_offsets[:-1], batch.event_offsets[1:], strict=True):
            event = raw.iloc[int(start) : int(end)].copy().reset_index(drop=True)
            _validate_event_records(event)
            envelope = _one_event_envelope(event)
            event_identifier = _digest(
                {
                    "portfolio_identifier": self.portfolio_identifier,
                    "model_identifier": model_identifier,
                    "source_identifier": envelope["source_identifier"],
                    "event_local_identifier": envelope["event_local_identifier"],
                }
            )
            prior_source_revision = self._state.applied_events.get(event_identifier)
            if prior_source_revision == envelope["source_revision"]:
                continue
            if prior_source_revision is not None:
                raise CorrectionReplayRequired(
                    "A corrected source revision requires portfolio-tail replay for event "
                    f"{event_identifier}."
                )
            input_state_identifier = self._state.identifier()
            event_revision = _digest(
                {
                    "event_identifier": event_identifier,
                    "model_version": model_version,
                    "source_revision": envelope["source_revision"],
                    "input_state_identifier": input_state_identifier,
                }
            )
            timestamp = _utc_timestamp(envelope["time_index"])
            before = self._value(
                timestamp,
                valuation_observations=valuation_observations,
                fx_observations=fx_observations,
            )
            declared_recognized_pnl = float(
                pd.to_numeric(event.get("recognized_pnl", 0.0), errors="coerce").fillna(0.0).sum()
            )
            self._apply_records(event)
            self._state.applied_events[event_identifier] = str(envelope["source_revision"])
            after = self._value(
                timestamp,
                valuation_observations=valuation_observations,
                fx_observations=fx_observations,
            )
            difference = after.nav - before.nav
            is_opening_state = envelope["event_type"] == "opening_state"
            if is_opening_state:
                recognized_pnl = 0.0
            elif np.isclose(declared_recognized_pnl, 0.0, rtol=0.0, atol=self.balance_tolerance):
                recognized_pnl = 0.0
            else:
                recognized_pnl = difference
            if (
                not is_opening_state
                and declared_recognized_pnl == 0.0
                and not np.isclose(difference, 0.0, rtol=0.0, atol=self.balance_tolerance)
            ):
                raise ValueError(
                    "Accounting event does not reconcile at unchanged marks: "
                    f"NAV delta={difference}, declared recognized_pnl=0.0."
                )
            self._state.event_sequence += 1
            self._state.last_nav = after.nav
            canonical = self._canonical_event_records(
                event,
                envelope=envelope,
                event_identifier=event_identifier,
                event_revision=event_revision,
                input_state_identifier=input_state_identifier,
                valuation_before=after if is_opening_state else before,
                valuation_after=after,
                recognized_pnl=recognized_pnl,
                model_identifier=model_identifier,
                model_version=model_version,
            )
            parts.append(canonical)
        if not parts:
            return pd.DataFrame()
        result = pd.concat(parts, ignore_index=True)
        self._ledger_parts.append(result)
        return result

    def _apply_records(self, event: pd.DataFrame) -> None:
        kinds = set(event["record_kind"].astype(str))
        unsupported = sorted(
            kinds
            - ECONOMIC_RECORD_KINDS
            - {
                "event_marker",
                "execution_progress",
                "valuation_summary",
            }
        )
        if unsupported:
            raise ValueError(f"Unsupported accounting record kinds: {unsupported}")
        self._apply_position_deltas(event[event["record_kind"] == "position_delta"])
        self._apply_balance_deltas(
            event[event["record_kind"].isin({"cash_delta", "cost"})],
            target=self._state.cash,
            identity_column=None,
            default_role="settled_cash",
        )
        self._apply_balance_deltas(
            event[event["record_kind"] == "obligation_delta"],
            target=self._state.obligations,
            identity_column="obligation_identifier",
            default_role="obligation",
        )
        for row in event[event["record_kind"] == "lifecycle_state"].to_dict(orient="records"):
            state_identifier = _required_text(row, "state_identifier")
            self._state.lifecycle_state[state_identifier] = {
                "state_identifier": state_identifier,
                "state_schema_version": int(row.get("state_schema_version") or 1),
                "extension_payload": _required_text(row, "extension_payload"),
            }

    def _apply_position_deltas(self, rows: pd.DataFrame) -> None:
        if rows.empty:
            return
        _require_finite_column(rows, "quantity_delta")
        prepared = rows.copy()
        prepared["position_identifier"] = prepared["position_identifier"].map(str)
        prepared["asset_identifier"] = prepared["asset_identifier"].map(str)
        prepared["quantity_unit"] = prepared["quantity_unit"].map(str)
        grouped = prepared.groupby(
            ["position_identifier", "asset_identifier", "quantity_unit"], sort=False
        )["quantity_delta"].sum()
        for (position_identifier, asset_identifier, quantity_unit), delta in grouped.items():
            prior = self._state.positions.get(position_identifier)
            if prior is not None and (
                prior["asset_identifier"] != asset_identifier
                or prior["quantity_unit"] != quantity_unit
            ):
                raise ValueError("A position identifier cannot change Asset or quantity unit.")
            quantity = float((prior or {}).get("quantity", 0.0)) + float(delta)
            self._state.positions[position_identifier] = {
                "position_identifier": position_identifier,
                "asset_identifier": asset_identifier,
                "balance_role": "instrument",
                "quantity": quantity,
                "quantity_unit": quantity_unit,
            }

    def _apply_balance_deltas(
        self,
        rows: pd.DataFrame,
        *,
        target: dict[str, dict[str, Any]],
        identity_column: str | None,
        default_role: str,
    ) -> None:
        if rows.empty:
            return
        _require_finite_column(rows, "quantity_delta")
        prepared = rows.copy()
        prepared["asset_identifier"] = prepared["asset_identifier"].map(str)
        prepared["balance_role"] = (
            prepared.get("balance_role", pd.Series(default_role, index=prepared.index))
            .fillna(default_role)
            .map(str)
        )
        prepared["quantity_unit"] = prepared["quantity_unit"].map(str)
        if identity_column is None:
            prepared["_identity"] = (
                "cash:" + prepared["balance_role"] + ":" + prepared["asset_identifier"]
            )
        else:
            prepared["_identity"] = prepared[identity_column].map(str)
        grouped = prepared.groupby(
            ["_identity", "asset_identifier", "balance_role", "quantity_unit"], sort=False
        )["quantity_delta"].sum()
        for (identifier, asset_identifier, role, quantity_unit), delta in grouped.items():
            prior = target.get(identifier)
            if prior is not None and (
                prior["asset_identifier"] != asset_identifier
                or prior["quantity_unit"] != quantity_unit
                or prior["balance_role"] != role
            ):
                raise ValueError("A balance identifier cannot change its accounting contract.")
            quantity = float((prior or {}).get("quantity", 0.0)) + float(delta)
            row = {
                "asset_identifier": asset_identifier,
                "balance_role": role,
                "quantity": quantity,
                "quantity_unit": quantity_unit,
            }
            row[identity_column or "state_identifier"] = identifier
            target[identifier] = row

    def _value(
        self,
        timestamp: pd.Timestamp,
        *,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> ValuationResult:
        return self.valuation_model.value(
            state=self.state,
            time_index=timestamp,
            valuation_asset_identifier=self.valuation_asset_identifier,
            valuation_observations=valuation_observations,
            fx_observations=fx_observations,
        )

    def _canonical_event_records(
        self,
        event: pd.DataFrame,
        *,
        envelope: dict[str, Any],
        event_identifier: str,
        event_revision: str,
        input_state_identifier: str,
        valuation_before: ValuationResult,
        valuation_after: ValuationResult,
        recognized_pnl: float,
        model_identifier: str,
        model_version: str,
    ) -> pd.DataFrame:
        economic = event.copy()
        economic["recognized_pnl"] = np.nan
        summary = pd.DataFrame(
            [
                {
                    **envelope,
                    "record_kind": "valuation_summary",
                    "nav_before": valuation_before.nav,
                    "nav_after": valuation_after.nav,
                    "recognized_pnl": recognized_pnl,
                    "valuation_asset_identifier": self.valuation_asset_identifier,
                }
            ]
        )
        records = pd.concat([economic, summary], ignore_index=True, sort=False)
        records["portfolio_identifier"] = self.portfolio_identifier
        records["event_identifier"] = event_identifier
        records["event_revision"] = event_revision
        records["event_sequence"] = self._state.event_sequence
        records["input_state_identifier"] = input_state_identifier
        records["ledger_state_identifier"] = self._state.identifier()
        records["model_identifier"] = model_identifier
        records["model_version"] = model_version
        records["supersedes_event_revision"] = None
        records["valuation_references"] = valuation_after.valuation_references
        records["causal_event_identifiers"] = records.get(
            "causal_event_identifiers", pd.Series(None, index=records.index)
        )
        records["terms_version"] = records.get(
            "terms_version", pd.Series(None, index=records.index)
        )
        records["extension_payload"] = records.get(
            "extension_payload", pd.Series(None, index=records.index)
        )
        records["event_status"] = "active"
        records["record_sequence"] = np.arange(len(records), dtype=np.int64)
        records["record_identifier"] = [
            _digest(
                {
                    "event_identifier": event_identifier,
                    "event_revision": event_revision,
                    "record_sequence": sequence,
                    "record_kind": kind,
                }
            )
            for sequence, kind in zip(
                records["record_sequence"], records["record_kind"], strict=True
            )
        ]
        for column in _LEDGER_COLUMNS:
            if column not in records.columns:
                records[column] = np.nan
        records["event_record_count"] = len(records)
        persisted = records[list(_LEDGER_COLUMNS)].copy()
        persisted["event_digest"] = event_digest(persisted)
        return persisted


def opening_cash_event_batch(
    *,
    time_index: pd.Timestamp,
    amount: float,
    asset_identifier: str,
) -> EventBatch:
    return EventBatch.from_frame(
        pd.DataFrame(
            [
                {
                    "event_local_identifier": "opening-state",
                    "time_index": _utc_timestamp(time_index),
                    "observed_at": _utc_timestamp(time_index),
                    "source_identifier": "opening-state",
                    "source_revision": "1",
                    "event_type": "opening_state",
                    "phase": "pre_execution",
                    "record_kind": "cash_delta",
                    "asset_identifier": str(asset_identifier),
                    "balance_role": "settled_cash",
                    "quantity_delta": float(amount),
                    "quantity_unit": str(asset_identifier),
                    "recognized_pnl": 0.0,
                }
            ]
        )
    )


def execution_event_batch(execution_facts: pd.DataFrame) -> EventBatch:
    """Convert explicit signed execution facts into position and cash records."""

    facts = _normalize_execution_facts(execution_facts)
    required = {
        "execution_identifier",
        "source_revision",
        "asset_identifier",
        "quantity_delta",
        "quantity_unit",
        "execution_price",
        "price_asset_identifier",
    }
    missing = sorted(required - set(facts.columns))
    if missing:
        raise ValueError("Execution facts are missing: " + ", ".join(missing))
    for column in ("quantity_delta", "execution_price"):
        facts[column] = pd.to_numeric(facts[column], errors="raise").astype("float64")
        if not np.isfinite(facts[column]).all():
            raise ValueError(f"Execution {column} values must be finite.")
    facts["position_identifier"] = facts.get(
        "position_identifier", facts["asset_identifier"]
    ).astype(str)
    facts["observed_at"] = pd.to_datetime(
        facts.get("observed_at", facts["time_index"]), utc=True
    ).astype("datetime64[ns, UTC]")
    rows: list[pd.DataFrame] = []
    for record_order, record_kind in enumerate(("position_delta", "cash_delta")):
        part = pd.DataFrame(
            {
                "_fact_order": np.arange(len(facts), dtype=np.int64),
                "_record_order": record_order,
                "event_local_identifier": facts["execution_identifier"].astype(str),
                "time_index": facts["time_index"],
                "observed_at": facts["observed_at"],
                "source_identifier": facts["execution_identifier"].astype(str),
                "source_revision": facts["source_revision"].astype(str),
                "event_type": "execution",
                "phase": "execution",
                "record_kind": record_kind,
                "position_identifier": facts["position_identifier"].astype(str),
                "asset_identifier": (
                    facts["asset_identifier"].astype(str)
                    if record_kind == "position_delta"
                    else facts["price_asset_identifier"].astype(str)
                ),
                "balance_role": (
                    "instrument" if record_kind == "position_delta" else "settled_cash"
                ),
                "quantity_delta": (
                    facts["quantity_delta"].to_numpy(dtype="float64")
                    if record_kind == "position_delta"
                    else -facts["quantity_delta"].to_numpy(dtype="float64")
                    * facts["execution_price"].to_numpy(dtype="float64")
                ),
                "quantity_unit": (
                    facts["quantity_unit"].astype(str)
                    if record_kind == "position_delta"
                    else facts["price_asset_identifier"].astype(str)
                ),
                "price": facts["execution_price"],
                "price_asset_identifier": facts["price_asset_identifier"].astype(str),
                "recognized_pnl": 0.0,
            }
        )
        rows.append(part)
    result = pd.concat(rows, ignore_index=True).sort_values(
        ["_fact_order", "_record_order"], kind="stable"
    )
    return EventBatch.from_frame(result.drop(columns=["_fact_order", "_record_order"]))


def valuation_marker_event_batch(time_index: pd.Timestamp | str) -> EventBatch:
    timestamp = _utc_timestamp(time_index)
    identifier = f"valuation:{timestamp.isoformat()}"
    return EventBatch.from_frame(
        pd.DataFrame(
            [
                {
                    "event_local_identifier": identifier,
                    "time_index": timestamp,
                    "observed_at": timestamp,
                    "source_identifier": identifier,
                    "source_revision": "1",
                    "event_type": "valuation",
                    "phase": "post_execution",
                    "record_kind": "event_marker",
                    "recognized_pnl": 0.0,
                }
            ]
        )
    )


def _normalize_execution_facts(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    flat = frame.copy().reset_index()
    if "time_index" not in flat.columns:
        raise ValueError("Execution facts require time_index.")
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype("datetime64[ns, UTC]")
    if flat.duplicated(subset=["execution_identifier", "source_revision"]).any():
        raise ValueError("Execution facts contain duplicate economic identities.")
    return flat.sort_values(["time_index", "execution_identifier"], kind="stable")


def _reject_cross_model_event_ownership(
    candidates_by_model: Mapping[str, pd.DataFrame],
) -> None:
    ownership: list[pd.DataFrame] = []
    for model_identifier, candidates in candidates_by_model.items():
        if candidates.empty:
            continue
        selected = candidates[
            ["time_index", "source_identifier", "source_revision", "event_type"]
        ].copy()
        selected["model_identifier"] = model_identifier
        ownership.append(selected)
    if not ownership:
        return
    combined = pd.concat(ownership, ignore_index=True)
    identity = ["time_index", "source_identifier", "source_revision", "event_type"]
    conflicts = combined.groupby(identity, sort=False)["model_identifier"].nunique()
    conflicts = conflicts[conflicts > 1]
    if not conflicts.empty:
        raise ValueError(
            "Multiple lifecycle models claim the same economic source events: "
            + ", ".join(str(value) for value in conflicts.index)
        )


def _validate_event_records(event: pd.DataFrame) -> None:
    if event.empty:
        raise ValueError("Accounting events must contain at least one record.")
    for column in (
        "event_local_identifier",
        "source_identifier",
        "source_revision",
        "event_type",
        "phase",
        "record_kind",
    ):
        if event[column].isna().any() or (event[column].astype(str).str.len() == 0).any():
            raise ValueError(f"Accounting event has empty {column} values.")
    if len(set(event["phase"].astype(str))) != 1:
        raise ValueError("One accounting event cannot span multiple phases.")
    invalid_phases = set(event["phase"].astype(str)) - set(PHASE_ORDER)
    if invalid_phases:
        raise ValueError(f"Unsupported event phases: {sorted(invalid_phases)}")
    for kind in ("position_delta", "cash_delta", "obligation_delta", "cost"):
        selected = event[event["record_kind"] == kind]
        if selected.empty:
            continue
        for column in ("asset_identifier", "quantity_delta", "quantity_unit"):
            if column not in selected.columns or selected[column].isna().any():
                raise ValueError(f"{kind} records require {column}.")
        _require_finite_column(selected, "quantity_delta")
    positions = event[event["record_kind"] == "position_delta"]
    if not positions.empty and (
        "position_identifier" not in positions.columns
        or positions["position_identifier"].isna().any()
    ):
        raise ValueError("position_delta records require position_identifier.")
    obligations = event[event["record_kind"] == "obligation_delta"]
    if not obligations.empty and (
        "obligation_identifier" not in obligations.columns
        or obligations["obligation_identifier"].isna().any()
    ):
        raise ValueError("obligation_delta records require obligation_identifier.")


def _one_event_envelope(event: pd.DataFrame) -> dict[str, Any]:
    fields = (
        "event_local_identifier",
        "time_index",
        "observed_at",
        "source_identifier",
        "source_revision",
        "event_type",
        "phase",
    )
    envelope: dict[str, Any] = {}
    for field_name in fields:
        values = event[field_name].drop_duplicates()
        if len(values) != 1:
            raise ValueError(f"One event must have exactly one {field_name} value.")
        envelope[field_name] = values.iloc[0]
    return envelope


def _require_finite_column(frame: pd.DataFrame, column: str) -> None:
    numeric = pd.to_numeric(frame[column], errors="raise").astype("float64")
    if not np.isfinite(numeric).all():
        raise ValueError(f"Accounting {column} values must be finite.")


def _required_text(row: Mapping[str, Any], field_name: str) -> str:
    value = row.get(field_name)
    if value is None or pd.isna(value) or not str(value):
        raise ValueError(f"Accounting records require {field_name}.")
    return str(value)


def _state_frame(
    values: Mapping[str, Mapping[str, Any]], *, columns: tuple[str, ...]
) -> pd.DataFrame:
    if not values:
        return pd.DataFrame(columns=list(columns))
    return (
        pd.DataFrame(values.values(), columns=list(columns))
        .sort_values(columns[0], kind="stable")
        .reset_index(drop=True)
    )


def _sorted_state(values: Mapping[str, Mapping[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [(key, dict(sorted(value.items()))) for key, value in sorted(values.items())]


def _digest(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def event_digest(records: pd.DataFrame) -> str:
    excluded = {"event_digest", "event_record_count"}
    ordered = records.sort_values("record_sequence", kind="stable")
    payload = [
        {key: _json_value(value) for key, value in sorted(row.items()) if key not in excluded}
        for row in ordered.to_dict(orient="records")
    ]
    return _digest(payload)


def _json_value(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (float, np.floating)) and np.isnan(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return _utc_timestamp(value).isoformat()
    return value


def _utc_timestamp(value: pd.Timestamp | str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.as_unit("ns")


def _empty_if_none(frame: pd.DataFrame | None) -> pd.DataFrame:
    return pd.DataFrame() if frame is None else frame


_LEDGER_COLUMNS = (
    "time_index",
    "portfolio_identifier",
    "event_identifier",
    "event_revision",
    "record_identifier",
    "observed_at",
    "event_type",
    "event_status",
    "phase",
    "event_sequence",
    "record_sequence",
    "event_record_count",
    "event_digest",
    "source_identifier",
    "source_revision",
    "model_identifier",
    "model_version",
    "supersedes_event_revision",
    "causal_event_identifiers",
    "input_state_identifier",
    "ledger_state_identifier",
    "terms_version",
    "valuation_references",
    "record_kind",
    "position_identifier",
    "obligation_identifier",
    "state_identifier",
    "asset_identifier",
    "balance_role",
    "quantity_delta",
    "quantity_unit",
    "amount_delta",
    "amount_asset_identifier",
    "price",
    "price_asset_identifier",
    "eligible_quantity",
    "recognized_pnl",
    "nav_before",
    "nav_after",
    "valuation_asset_identifier",
    "state_schema_version",
    "extension_payload",
)


__all__ = [
    "CorrectionReplayRequired",
    "PortfolioAccounting",
    "event_digest",
    "execution_event_batch",
    "opening_cash_event_batch",
    "valuation_marker_event_batch",
]
