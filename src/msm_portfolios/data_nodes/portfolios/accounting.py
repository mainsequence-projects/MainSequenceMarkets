"""Authoritative position-aware portfolio accounting updater."""

from __future__ import annotations

import os
import pandas as pd
from pydantic import Field

from mainsequence.meta_tables import TimeIndexTableRef, TimeIndexTableUpdater
from msm_portfolios.accounting import (
    LifecycleInputContract,
    PortfolioAccounting,
    PortfolioAccountingConfiguration,
    event_digest,
)

from ..base import PortfolioCanonicalDataNode, PortfolioCanonicalDataNodeConfiguration
from .storage import PortfolioEventLedgerStorage


class PortfolioEngineConfiguration(PortfolioCanonicalDataNodeConfiguration):
    """Hash-bearing opt-in position-accounting updater configuration."""

    portfolio_identifier: str = Field(min_length=1)
    accounting_configuration: PortfolioAccountingConfiguration


class PortfolioEngine(PortfolioCanonicalDataNode):
    """Coordinate declared inputs and publish one authoritative event ledger."""

    @classmethod
    def from_portfolio_configuration(
        cls,
        portfolio_configuration,
        *,
        portfolio_identifier: str,
        namespace: str | None = None,
        **kwargs,
    ) -> PortfolioEngine:
        """Construct the opt-in engine from the nested portfolio build contract."""

        accounting = getattr(
            portfolio_configuration.portfolio_build_configuration,
            "accounting_configuration",
            None,
        )
        if accounting is None:
            raise ValueError(
                "PortfolioEngine requires enabled PortfolioBuildConfiguration.accounting_configuration."
            )
        return cls(
            config=PortfolioEngineConfiguration(
                portfolio_identifier=portfolio_identifier,
                accounting_configuration=accounting,
            ),
            namespace=namespace,
            **kwargs,
        )

    def dependencies(self) -> dict[str, TimeIndexTableUpdater | TimeIndexTableRef]:
        accounting = self._engine_config().accounting_configuration
        dependencies: dict[str, TimeIndexTableUpdater | TimeIndexTableRef] = {}
        if accounting.execution_fact_source_instance is not None:
            dependencies["execution_facts"] = accounting.execution_fact_source_instance
        for name, dependency in sorted(
            accounting.position_valuation_model_instance.declared_dependencies().items()
        ):
            dependencies[f"valuation.{name}"] = dependency
        for model in sorted(
            accounting.lifecycle_event_model_instances,
            key=lambda value: value.model_identifier,
        ):
            for name, dependency in sorted(model.declared_dependencies().items()):
                key = f"lifecycle.{model.model_identifier}.{name}"
                if key in dependencies:
                    raise ValueError(f"Duplicate accounting dependency key {key!r}.")
                dependencies[key] = dependency
        return dependencies

    def update(self) -> pd.DataFrame:
        config = self._engine_config()
        accounting_config = config.accounting_configuration
        dependencies = self.dependencies()
        start = pd.Timestamp(accounting_config.initial_state_time_index)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        else:
            start = start.tz_convert("UTC")
        end = pd.Timestamp.now(tz="UTC")
        maximum_window = os.getenv("MAX_TD_FROM_LATEST_VALUE")
        if maximum_window:
            end = min(end, start + pd.Timedelta(maximum_window))

        frames = {
            name: _read_dependency(dependency, start=start, end=end)
            for name, dependency in dependencies.items()
        }
        valuation_dependencies = (
            accounting_config.position_valuation_model_instance.declared_dependencies()
        )
        valuation_contracts = (
            accounting_config.position_valuation_model_instance.required_input_contracts()
        )
        if set(valuation_dependencies) != set(valuation_contracts):
            raise ValueError("Valuation dependency names and input-contract names must match.")
        for name, contract in valuation_contracts.items():
            key = f"valuation.{name}"
            frames[key] = _validate_declared_input(frames[key], contract=contract, name=key)
        for model in accounting_config.lifecycle_event_model_instances:
            for name, contract in model.required_input_contracts().items():
                key = f"lifecycle.{model.model_identifier}.{name}"
                frames[key] = _validate_declared_input(frames[key], contract=contract, name=key)
        valuations = frames.get("valuation.valuations", pd.DataFrame())
        if valuations.empty:
            raise ValueError("PortfolioEngine requires declared valuation observations.")
        fx = frames.get("valuation.fx", pd.DataFrame())
        lifecycle_inputs: dict[str, dict[str, pd.DataFrame]] = {}
        for model in accounting_config.lifecycle_event_model_instances:
            lifecycle_inputs[model.model_identifier] = {
                name: frames[f"lifecycle.{model.model_identifier}.{name}"]
                for name in model.declared_dependencies()
            }
        valuation_times = pd.to_datetime(valuations.reset_index()["time_index"], utc=True).unique()
        reducer = PortfolioAccounting(
            portfolio_identifier=config.portfolio_identifier,
            valuation_asset_identifier=accounting_config.valuation_asset_identifier,
            initial_nav=accounting_config.initial_nav,
            initial_state_time_index=accounting_config.initial_state_time_index,
            valuation_model=accounting_config.position_valuation_model_instance,
            balance_tolerance=(accounting_config.rounding_and_balance_policy.balance_tolerance),
            historical_information_mode=accounting_config.historical_information_policy.mode,
        )
        ledger = reducer.run(
            valuation_observations=valuations,
            fx_observations=fx,
            execution_facts=frames.get("execution_facts"),
            lifecycle_models=accounting_config.lifecycle_event_model_instances,
            lifecycle_inputs=lifecycle_inputs,
            valuation_times=valuation_times,
        )
        existing = self.get_df_between_dates(
            start_date=start,
            end_date=end,
            great_or_equal=True,
            less_or_equal=True,
            dimension_filters={
                "portfolio_identifier": [config.portfolio_identifier],
            },
        )
        _validate_replay_against_existing(existing, ledger)
        return normalize_portfolio_event_ledger_frame(
            ledger,
            output_table=self.output_table,
        )

    @classmethod
    def _validate_config(
        cls,
        config: PortfolioCanonicalDataNodeConfiguration,
    ) -> PortfolioEngineConfiguration:
        if not isinstance(config, PortfolioEngineConfiguration):
            raise TypeError("PortfolioEngine requires PortfolioEngineConfiguration.")
        return config

    def _engine_config(self) -> PortfolioEngineConfiguration:
        return self.__class__._validate_config(self.config)

    @classmethod
    def _required_output_table(cls) -> type[PortfolioEventLedgerStorage]:
        return PortfolioEventLedgerStorage


def normalize_portfolio_event_ledger_frame(
    frame: pd.DataFrame,
    *,
    output_table: type[PortfolioEventLedgerStorage] | None = None,
) -> pd.DataFrame:
    """Validate a complete canonical ledger frame against its storage schema."""

    required = list(PortfolioEngine._column_dtypes_map_for_storage(output_table))
    flat = frame.copy().reset_index()
    if flat.empty:
        flat = pd.DataFrame(columns=required)
    missing = sorted(set(required) - set(flat.columns))
    if missing:
        raise ValueError("Portfolio event ledger is missing columns: " + ", ".join(missing))
    canonical = PortfolioEngine.validate_frame(flat[required], output_table=output_table)
    _validate_complete_event_groups(canonical.reset_index())
    return canonical


def _validate_complete_event_groups(frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    keys = ["portfolio_identifier", "event_identifier", "event_revision"]
    grouped = frame.groupby(keys, sort=False, dropna=False)
    sizes = grouped.size()
    counts = grouped["event_record_count"].first()
    if not sizes.equals(counts.astype("int64")):
        raise ValueError("Portfolio event ledger contains an incomplete event group.")
    digest_counts = grouped["event_digest"].nunique()
    if (digest_counts != 1).any():
        raise ValueError("Portfolio event ledger event records disagree on event_digest.")
    for _, event in grouped:
        expected = str(event["event_digest"].iloc[0])
        if event_digest(event) != expected:
            raise ValueError("Portfolio event ledger event_digest does not match its records.")


def _read_dependency(
    dependency: TimeIndexTableUpdater | TimeIndexTableRef,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    frame = dependency.get_df_between_dates(
        start_date=start,
        end_date=end,
        great_or_equal=True,
        less_or_equal=True,
    )
    return pd.DataFrame() if frame is None else frame


def _validate_declared_input(
    frame: pd.DataFrame,
    *,
    contract: LifecycleInputContract,
    name: str,
) -> pd.DataFrame:
    flat = frame.copy().reset_index()
    required = {
        *contract.index_names,
        *contract.required_columns,
        contract.source_revision_column,
    }
    missing = sorted(required - set(flat.columns))
    if missing:
        raise ValueError(f"Accounting dependency {name!r} is missing: {', '.join(missing)}")
    flat["time_index"] = pd.to_datetime(flat["time_index"], utc=True).astype("datetime64[ns, UTC]")
    if flat.duplicated(subset=list(contract.index_names)).any():
        raise ValueError(f"Accounting dependency {name!r} contains duplicate grain rows.")
    return flat.set_index(list(contract.index_names)).sort_index()


def _validate_replay_against_existing(
    existing: pd.DataFrame | None,
    calculated: pd.DataFrame,
) -> None:
    """Allow exact idempotent replay and block unsupported correction publication."""

    if existing is None or existing.empty:
        return
    old = existing.copy().reset_index()
    new = calculated.copy().reset_index()
    identity_columns = ["event_identifier", "source_revision", "event_revision"]
    old_events = (
        old[identity_columns].drop_duplicates("event_identifier").set_index("event_identifier")
    )
    new_events = (
        new[identity_columns].drop_duplicates("event_identifier").set_index("event_identifier")
    )
    removed = sorted(set(old_events.index) - set(new_events.index))
    if removed:
        raise NotImplementedError(
            "Source deletions require corrected portfolio-tail replay; affected events: "
            + ", ".join(removed)
        )
    shared = old_events.join(new_events, how="inner", lsuffix="_old", rsuffix="_new")
    corrected = shared[
        (shared["source_revision_old"] != shared["source_revision_new"])
        | (shared["event_revision_old"] != shared["event_revision_new"])
    ]
    if not corrected.empty:
        raise NotImplementedError(
            "Corrected source/state revisions require portfolio-tail replay; affected events: "
            + ", ".join(sorted(corrected.index.astype(str)))
        )
    old_digests = old.groupby("event_identifier", sort=False)["event_digest"].first()
    new_digests = new.groupby("event_identifier", sort=False)["event_digest"].first()
    mismatched = [
        identifier
        for identifier in sorted(set(old_digests.index) & set(new_digests.index))
        if str(old_digests[identifier]) != str(new_digests[identifier])
    ]
    if mismatched:
        raise ValueError(
            "Exact replay changed canonical event records without a new revision: "
            + ", ".join(mismatched)
        )


__all__ = [
    "PortfolioEngine",
    "PortfolioEngineConfiguration",
    "normalize_portfolio_event_ledger_frame",
]
