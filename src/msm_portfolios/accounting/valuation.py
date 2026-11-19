"""Vectorized position, cash, obligation, and FX valuation."""

from __future__ import annotations

import datetime as dt
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from metatables import TimeIndexTableRef, TimeIndexTableUpdater

from .contracts import AccountingStateView, LifecycleInputContract


ValuationDependency = TimeIndexTableUpdater | TimeIndexTableRef


@dataclass(frozen=True)
class ValuationResult:
    """Disjoint valued state components and their reconciled NAV."""

    time_index: pd.Timestamp
    valuation_asset_identifier: str
    components: pd.DataFrame
    nav: float
    valuation_references: str
    stale_sources: tuple[str, ...] = ()
    """Prices and rates older than ``maximum_staleness`` used here, as
    ``"valuation:<asset>"`` or ``"fx:<asset>"``. Their references carry
    ``"stale": "true"``."""


class PositionValuationModel(BaseModel, ABC):
    """Public pure boundary for valuing signed portfolio accounting state."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    model_identifier: ClassVar[str]
    model_version: ClassVar[str] = "1"

    def declared_dependencies(self) -> dict[str, ValuationDependency]:
        return {}

    def required_input_contracts(self) -> dict[str, LifecycleInputContract]:
        return {}

    @abstractmethod
    def value(
        self,
        *,
        state: AccountingStateView,
        time_index: pd.Timestamp,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> ValuationResult:
        """Value one immutable state snapshot at an explicit economic timestamp."""


class MarketPriceValuationModel(PositionValuationModel):
    """Value positions from asset prices and convert every component with explicit FX."""

    model_identifier: ClassVar[str] = "msm.market_price_valuation"
    model_version: ClassVar[str] = "1"

    valuation_source: ValuationDependency | None = Field(default=None, exclude=True)
    price_column: str = "price"
    maximum_staleness: dt.timedelta = Field(
        default=dt.timedelta(days=1),
        gt=dt.timedelta(0),
        description=(
            "Age past which a price or FX rate is marked stale. A held asset is always "
            "valued at its last observed price, however old; a stale one is listed in "
            "ValuationResult.stale_sources and its valuation reference carries "
            '"stale": "true". Only a held asset with no observed price at all raises '
            "(ADR 0058)."
        ),
    )
    fail_on_missing_values: bool = Field(
        default=False,
        description=(
            "Raise when a held asset's last observed price, or a needed FX rate, is "
            "older than maximum_staleness, instead of using it and marking it stale "
            "(the default)."
        ),
    )

    def declared_dependencies(self) -> dict[str, ValuationDependency]:
        dependencies: dict[str, ValuationDependency] = {}
        if self.valuation_source is not None:
            dependencies["valuations"] = self.valuation_source
        return dependencies

    def required_input_contracts(self) -> dict[str, LifecycleInputContract]:
        contracts = {
            "valuations": LifecycleInputContract(
                index_names=("time_index", "asset_identifier"),
                required_columns=(
                    self.price_column,
                    "price_asset_identifier",
                    "source_revision",
                ),
            )
        }
        return contracts

    def value(
        self,
        *,
        state: AccountingStateView,
        time_index: pd.Timestamp,
        valuation_asset_identifier: str,
        valuation_observations: pd.DataFrame,
        fx_observations: pd.DataFrame,
    ) -> ValuationResult:
        timestamp = _utc_timestamp(time_index)
        components: list[pd.DataFrame] = []
        references: list[dict[str, str]] = []

        if not state.positions.empty:
            positions = state.positions.copy().reset_index(drop=True)
            positions = positions[positions["quantity"].astype("float64") != 0.0]
        else:
            positions = pd.DataFrame()
        if not positions.empty:
            marks = _select_latest_rows(
                valuation_observations,
                timestamp=timestamp,
                keys=("asset_identifier",),
                required_values=positions["asset_identifier"].astype(str).unique(),
                value_columns=(self.price_column, "price_asset_identifier"),
                maximum_staleness=self.maximum_staleness,
                frame_name="valuation",
                fail_on_stale=self.fail_on_missing_values,
            )
            marked = positions.merge(
                marks, on="asset_identifier", how="left", validate="many_to_one"
            )
            marked["native_value"] = marked["quantity"].to_numpy(dtype="float64") * marked[
                self.price_column
            ].to_numpy(dtype="float64")
            fx_rates, fx_refs = _fx_rates(
                marked["price_asset_identifier"],
                valuation_asset_identifier=valuation_asset_identifier,
                timestamp=timestamp,
                fx_observations=fx_observations,
                maximum_staleness=self.maximum_staleness,
                fail_on_stale=self.fail_on_missing_values,
            )
            marked["value"] = marked["native_value"].to_numpy() * fx_rates
            marked["component_kind"] = "position"
            marked["state_identifier"] = marked["position_identifier"].astype(str)
            marked["value_asset_identifier"] = valuation_asset_identifier
            components.append(marked[_component_columns()])
            references.extend(_references_from_rows(marks, "valuation"))
            references.extend(fx_refs)

        for frame, kind, identity_column in (
            (state.cash, "cash", "state_identifier"),
            (state.obligations, "obligation", "obligation_identifier"),
        ):
            if frame.empty:
                continue
            native = frame.copy().reset_index(drop=True)
            fx_rates, fx_refs = _fx_rates(
                native["asset_identifier"],
                valuation_asset_identifier=valuation_asset_identifier,
                timestamp=timestamp,
                fx_observations=fx_observations,
                maximum_staleness=self.maximum_staleness,
                fail_on_stale=self.fail_on_missing_values,
            )
            native["native_value"] = native["quantity"].to_numpy(dtype="float64")
            native["value"] = native["native_value"].to_numpy() * fx_rates
            native["component_kind"] = kind
            native["state_identifier"] = native[identity_column].astype(str)
            native["price_asset_identifier"] = native["asset_identifier"].astype(str)
            native["value_asset_identifier"] = valuation_asset_identifier
            components.append(native[_component_columns()])
            references.extend(fx_refs)

        result = (
            pd.concat(components, ignore_index=True)
            if components
            else pd.DataFrame(columns=_component_columns())
        )
        nav = float(result["value"].sum()) if not result.empty else 0.0
        if not np.isfinite(nav):
            raise ValueError("Portfolio NAV must be finite.")
        serialized_references = json.dumps(
            sorted(references, key=lambda value: json.dumps(value, sort_keys=True)),
            sort_keys=True,
            separators=(",", ":"),
        )
        stale_sources = sorted(
            {
                f"{reference['source_kind']}:"
                + reference.get("asset_identifier", reference.get("base_asset_identifier", ""))
                for reference in references
                if reference.get("stale") == "true"
            }
        )
        return ValuationResult(
            time_index=timestamp,
            valuation_asset_identifier=str(valuation_asset_identifier),
            components=result,
            nav=nav,
            valuation_references=serialized_references,
            stale_sources=tuple(stale_sources),
        )


def _component_columns() -> list[str]:
    return [
        "component_kind",
        "state_identifier",
        "asset_identifier",
        "balance_role",
        "quantity",
        "quantity_unit",
        "native_value",
        "price_asset_identifier",
        "value",
        "value_asset_identifier",
    ]


def _utc_timestamp(value: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.as_unit("ns")


def _normalize_time_frame(frame: pd.DataFrame, *, frame_name: str) -> pd.DataFrame:
    flat = frame.copy().reset_index()
    if "time_index" not in flat.columns:
        raise ValueError(f"{frame_name} observations require time_index.")
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype("datetime64[ns, UTC]")
    return flat


def _select_latest_rows(
    frame: pd.DataFrame,
    *,
    timestamp: pd.Timestamp,
    keys: tuple[str, ...],
    required_values: np.ndarray,
    value_columns: tuple[str, ...],
    maximum_staleness: dt.timedelta,
    frame_name: str,
    fail_on_stale: bool = False,
) -> pd.DataFrame:
    flat = _normalize_time_frame(frame, frame_name=frame_name)
    required_columns = {*keys, *value_columns}
    missing_columns = sorted(required_columns - set(flat.columns))
    if missing_columns:
        raise ValueError(f"{frame_name} observations are missing: {', '.join(missing_columns)}")
    if flat.duplicated(subset=["time_index", *keys]).any():
        raise ValueError(f"{frame_name} observations contain duplicate grain coordinates.")
    # The last observation at or before the timestamp, however old: past
    # maximum_staleness it is marked stale, never refused.
    selected = flat[flat["time_index"] <= timestamp]
    selected = (
        selected.sort_values([*keys, "time_index"], kind="stable")
        .groupby(list(keys), sort=False)
        .tail(1)
        .copy()
    )
    present = set(selected[keys[0]].astype(str))
    missing_values = sorted(set(map(str, required_values)) - present)
    if missing_values:
        raise ValueError(
            f"No observed {frame_name} price at or before {timestamp.isoformat()} for: "
            + ", ".join(missing_values)
        )
    selected["stale"] = (timestamp - selected["time_index"]) > pd.Timedelta(maximum_staleness)
    if fail_on_stale and selected["stale"].any():
        raise ValueError(
            f"Missing fresh {frame_name} observations for: "
            + ", ".join(sorted(selected.loc[selected["stale"], keys[0]].astype(str)))
        )
    for column in value_columns:
        if selected[column].isna().any():
            raise ValueError(f"{frame_name}.{column} contains missing values.")
    if "source_revision" not in selected.columns:
        raise ValueError(f"{frame_name} observations require source_revision.")
    return selected


def _fx_rates(
    asset_identifiers: pd.Series,
    *,
    valuation_asset_identifier: str,
    timestamp: pd.Timestamp,
    fx_observations: pd.DataFrame,
    maximum_staleness: dt.timedelta,
    fail_on_stale: bool = False,
) -> tuple[np.ndarray, list[dict[str, str]]]:
    assets = asset_identifiers.astype(str).to_numpy()
    unique = np.unique(assets)
    rates_by_asset = {str(valuation_asset_identifier): 1.0}
    references: list[dict[str, str]] = []
    foreign = np.asarray([asset for asset in unique if asset != valuation_asset_identifier])
    if len(foreign):
        if fx_observations is None or fx_observations.empty:
            raise ValueError(
                "Missing explicit FX observations into "
                f"{valuation_asset_identifier}: {', '.join(sorted(foreign))}"
            )
        flat = _normalize_time_frame(fx_observations, frame_name="FX")
        required = {
            "base_asset_identifier",
            "quote_asset_identifier",
            "rate",
            "source_revision",
        }
        missing = sorted(required - set(flat.columns))
        if missing:
            raise ValueError("FX observations are missing: " + ", ".join(missing))
        if flat.duplicated(
            subset=["time_index", "base_asset_identifier", "quote_asset_identifier"]
        ).any():
            raise ValueError("FX observations contain duplicate grain coordinates.")
        # The last observed rate, however old: past maximum_staleness it is marked
        # stale, never refused.
        selected = flat[
            (flat["base_asset_identifier"].astype(str).isin(foreign))
            & (flat["quote_asset_identifier"].astype(str) == valuation_asset_identifier)
            & (flat["time_index"] <= timestamp)
        ]
        selected = (
            selected.sort_values(["base_asset_identifier", "time_index"], kind="stable")
            .groupby("base_asset_identifier", sort=False)
            .tail(1)
            .copy()
        )
        selected["stale"] = (timestamp - selected["time_index"]) > pd.Timedelta(
            maximum_staleness
        )
        if fail_on_stale and selected["stale"].any():
            raise ValueError(
                "Missing fresh FX observations into "
                f"{valuation_asset_identifier}: "
                + ", ".join(sorted(selected.loc[selected["stale"], "base_asset_identifier"]))
            )
        missing_fx = sorted(set(foreign) - set(selected["base_asset_identifier"].astype(str)))
        if missing_fx:
            raise ValueError(
                "Missing explicit FX observations into "
                f"{valuation_asset_identifier}: {', '.join(missing_fx)}"
            )
        numeric_rates = pd.to_numeric(selected["rate"], errors="raise").astype("float64")
        if (numeric_rates <= 0).any() or not np.isfinite(numeric_rates).all():
            raise ValueError("FX rates must be finite and strictly positive.")
        rates_by_asset.update(
            dict(zip(selected["base_asset_identifier"].astype(str), numeric_rates, strict=True))
        )
        references.extend(_references_from_rows(selected, "fx"))
    return np.asarray([rates_by_asset[asset] for asset in assets], dtype=np.float64), references


def _references_from_rows(frame: pd.DataFrame, source_kind: str) -> list[dict[str, str]]:
    if frame.empty:
        return []
    keys = [
        column
        for column in (
            "time_index",
            "asset_identifier",
            "base_asset_identifier",
            "quote_asset_identifier",
            "source_revision",
        )
        if column in frame.columns
    ]
    return [
        {
            "source_kind": source_kind,
            **{key: str(row[key]) for key in keys},
            **({"stale": "true"} if bool(row.get("stale", False)) else {}),
        }
        for row in frame.to_dict(orient="records")
    ]


__all__ = [
    "MarketPriceValuationModel",
    "PositionValuationModel",
    "ValuationDependency",
    "ValuationResult",
]
