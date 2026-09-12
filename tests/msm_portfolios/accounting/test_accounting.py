from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from mainsequence.client.metatables import TimeIndexMetaTable
from mainsequence.meta_tables import TimeIndexTableUpdater
from mainsequence.meta_tables.time_index_table_updates.configuration import ConfigRebuilder
from msm.models import AssetTable, PortfolioTable
from msm_portfolios.accounting import (
    DividendCashFlowModel,
    MarketPriceValuationModel,
    PortfolioAccounting,
    PortfolioAccountingConfiguration,
    canonical_lifecycle_model_configuration,
    project_cash_flows,
    project_state,
)
from msm_portfolios.configuration import (
    BacktestingWeightsConfig,
    PortfolioBuildConfiguration,
    PortfolioConfiguration,
    PortfolioExecutionConfiguration,
    PortfolioMarketsConfig,
)
from msm_portfolios.data_nodes import SignalWeights
from msm_portfolios.data_nodes import compute_portfolio_configuration_hash
from msm_portfolios.data_nodes.portfolios.accounting import (
    PortfolioEngine,
    PortfolioEngineConfiguration,
    _new_ledger_tail,
    _validate_replay_against_existing,
    normalize_portfolio_event_ledger_frame,
)
from msm_portfolios.data_nodes.portfolios.storage import (
    PortfolioCashFlowsStorage,
    PortfolioEventLedgerStorage,
    PortfolioStateStorage,
)
from msm_portfolios.models import portfolio_sqlalchemy_models
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    InstrumentExecutionSpec,
    ProportionalExecutionCostModel,
    TargetWeightExecutionModel,
    TimeWeighted,
)

from examples.msm_portfolios.portfolio_cashflows_and_fx_valuation_example import (
    build_example,
)
from examples.msm_portfolios.portfolio_custom_cashflow_model_example import (
    UsageRoyalty,
    build_example as build_custom_example,
)
from examples.msm_portfolios.portfolio_perpetual_funding_example import (
    build_example as build_perpetual_example,
)


class _Source(TimeIndexTableUpdater):
    def update(self) -> pd.DataFrame:
        return pd.DataFrame()

    def dependencies(self) -> dict:
        return {}


def _source(update_hash: str) -> _Source:
    source = object.__new__(_Source)
    source.update_hash = update_hash
    source._output_table = SimpleNamespace(
        get_time_index_meta_table=lambda: TimeIndexMetaTable.model_construct(
            uid=f"{update_hash}-table",
            data_source_uid="source",
        ),
        get_data_source_uid=lambda: "source",
    )
    return source


def _legacy_build_configuration() -> PortfolioBuildConfiguration:
    signal = object.__new__(SignalWeights)
    signal.update_hash = "signal"
    signal._output_table = _source("signal")._output_table
    signal.signal_configuration = {"kind": "legacy-test-signal"}
    return PortfolioBuildConfiguration(
        valuation_source_instance=_source("valuation"),
        execution_configuration=PortfolioExecutionConfiguration(commission_fee=0.0),
        backtesting_weights_configuration=BacktestingWeightsConfig(
            signal_weights_instance=signal,
            rebalance_strategy_instance=ImmediateSignal(),
        ),
    )


def test_legacy_build_configuration_omits_disabled_accounting_field() -> None:
    omitted = _legacy_build_configuration()
    explicit_none = _legacy_build_configuration()
    explicit_none.accounting_configuration = None

    assert "accounting_configuration" not in omitted.model_dump(mode="json")
    assert omitted.model_dump(mode="json") == explicit_none.model_dump(mode="json")


def test_enabled_accounting_configuration_is_hash_bearing() -> None:
    build = _legacy_build_configuration()
    build.accounting_configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        position_valuation_model_instance=MarketPriceValuationModel(),
    )

    assert "accounting_configuration" in build.model_dump(mode="json")


def test_accounting_configuration_rejects_external_execution_ingress() -> None:
    with pytest.raises(ValidationError, match="execution_fact_source_instance"):
        PortfolioAccountingConfiguration(
            valuation_asset_identifier="USD",
            initial_nav=1_000.0,
            initial_state_time_index=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            position_valuation_model_instance=MarketPriceValuationModel(),
            execution_fact_source_instance=_source("broker-fills"),
        )


def test_unconfigured_rebalance_strategy_keeps_legacy_serialized_shape() -> None:
    payload = ImmediateSignal().model_dump(mode="json")

    assert "execution_model_instance" not in payload
    assert "execution_cost_model_instances" not in payload


def test_portfolio_engine_configuration_serializes_its_runtime_dependencies() -> None:
    build = _legacy_build_configuration()
    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="STOCK",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="USD",
                    settlement_style="cash",
                    terms_version="stock-v1",
                ),
            )
        ),
        execution_cost_model_instances=(ProportionalExecutionCostModel(rate=0.001),),
    )
    payload = PortfolioEngineConfiguration(
        portfolio_identifier="position-aware",
        accounting_configuration=PortfolioAccountingConfiguration(
            valuation_asset_identifier="USD",
            initial_nav=1_000.0,
            initial_state_time_index=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            position_valuation_model_instance=MarketPriceValuationModel(),
        ),
        signal_weights_instance=(
            build.backtesting_weights_configuration.signal_weights_instance
        ),
        rebalance_strategy_instance=strategy,
    ).model_dump(mode="json")

    assert payload["portfolio_identifier"] == "position-aware"
    assert payload["signal_weights_instance"]
    assert payload["rebalance_strategy_instance"]
    assert payload["rebalance_strategy_instance"]["config"]["execution_model_instance"]
    rebuilt = ConfigRebuilder().rebuild(payload["rebalance_strategy_instance"]["config"])
    assert isinstance(rebuilt["execution_model_instance"], TargetWeightExecutionModel)
    assert isinstance(rebuilt["execution_cost_model_instances"][0], ProportionalExecutionCostModel)


def test_disabled_accounting_preserves_legacy_portfolio_hash() -> None:
    omitted = PortfolioConfiguration(
        portfolio_build_configuration=_legacy_build_configuration(),
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name="legacy"),
    )
    explicit_none_build = _legacy_build_configuration()
    explicit_none_build.accounting_configuration = None
    explicit_none = PortfolioConfiguration(
        portfolio_build_configuration=explicit_none_build,
        portfolio_markets_configuration=PortfolioMarketsConfig(portfolio_name="legacy"),
    )

    assert compute_portfolio_configuration_hash(omitted) == compute_portfolio_configuration_hash(
        explicit_none
    )


def test_dividend_entitlement_survives_sale_and_settles_once() -> None:
    result = build_example()
    ledger = result["ledger"]
    summaries = ledger[ledger["record_kind"] == "valuation_summary"]

    entitlement = summaries[summaries["event_type"] == "entitlement"].iloc[0]
    settlement = summaries[summaries["event_type"] == "settlement"].iloc[0]
    assert entitlement["recognized_pnl"] == pytest.approx(11.0)
    assert settlement["recognized_pnl"] == pytest.approx(0.0)
    assert settlement["nav_after"] == pytest.approx(1_000.0)
    assert result["positions"].iloc[0]["quantity"] == pytest.approx(0.0)
    assert result["obligations"].iloc[0]["quantity"] == pytest.approx(0.0)
    eur_cash = result["cash"].set_index("asset_identifier").loc["EUR", "quantity"]
    assert eur_cash == pytest.approx(0.0)


def test_post_entitlement_entry_receives_no_dividend() -> None:
    prices = pd.DataFrame(
        [
            ("2026-01-03T10:00:00Z", "STOCK", 10.0, "USD", "p1"),
            ("2026-01-04T10:00:00Z", "STOCK", 10.0, "USD", "p2"),
            ("2026-01-05T10:00:00Z", "STOCK", 10.0, "USD", "p3"),
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
        [("2026-01-04T10:00:00Z", "late-entry", "STOCK", 0.1)],
        columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
    ).set_index(["time_index", "signal_uid", "asset_identifier"])
    dividends = pd.DataFrame(
        [
            (
                "2026-01-03T10:00:00Z",
                "d1",
                "1",
                "2026-01-01T00:00:00Z",
                "STOCK",
                "2026-01-03T10:00:00Z",
                "2026-01-05T10:00:00Z",
                1.0,
                "USD",
            )
        ],
        columns=[
            "time_index",
            "source_event_identifier",
            "source_revision",
            "observed_at",
            "asset_identifier",
            "entitlement_time_index",
            "payment_time_index",
            "amount_per_unit",
            "settlement_asset_identifier",
        ],
    )
    configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=100.0,
        initial_state_time_index="2026-01-02T10:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(
            maximum_staleness=dt.timedelta(days=3)
        ),
        lifecycle_event_model_instances=(DividendCashFlowModel(),),
    )
    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="STOCK",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="USD",
                    settlement_style="cash",
                    terms_version="stock-v1",
                ),
            )
        )
    )
    accounting = PortfolioEngine.calculate_backtest(
        portfolio_identifier="late-entry",
        accounting_configuration=configuration,
        rebalance_strategy=strategy,
        signal_observations=signals,
        rebalance_inputs={},
        valuation_observations=prices,
        lifecycle_inputs={"msm.dividend_cash_flow": {"dividends": dividends}},
    )
    ledger = accounting.ledger

    settlement_cash = ledger[
        (ledger["event_type"] == "settlement") & (ledger["record_kind"] == "cash_delta")
    ]
    assert settlement_cash.iloc[0]["quantity_delta"] == pytest.approx(0.0)


def test_missing_fx_is_a_hard_error() -> None:
    configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=100.0,
        initial_state_time_index="2026-01-01T00:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(),
    )
    signals = pd.DataFrame(
        [("2026-01-02T00:00:00Z", "missing-fx", "EUR-STOCK", 0.1)],
        columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
    ).set_index(["time_index", "signal_uid", "asset_identifier"])
    prices = pd.DataFrame(
        [
            {
                "time_index": "2026-01-02T00:00:00Z",
                "asset_identifier": "EUR-STOCK",
                "price": 10.0,
                "price_asset_identifier": "EUR",
                "source_revision": "p1",
            }
        ]
    )

    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="EUR-STOCK",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="EUR",
                    settlement_style="cash",
                    terms_version="stock-v1",
                ),
            )
        )
    )

    with pytest.raises(ValueError, match="Missing explicit execution FX"):
        PortfolioEngine.calculate_backtest(
            portfolio_identifier="missing-fx",
            accounting_configuration=configuration,
            rebalance_strategy=strategy,
            signal_observations=signals,
            rebalance_inputs={},
            valuation_observations=prices,
        )


def test_unchanged_zero_target_requires_neither_terms_nor_a_mark() -> None:
    signals = pd.DataFrame(
        [("2026-01-02T00:00:00Z", "zero", "UNHELD", 0.0)],
        columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
    ).set_index(["time_index", "signal_uid", "asset_identifier"])
    configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=100.0,
        initial_state_time_index="2026-01-01T00:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(),
    )
    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(instrument_specs=())
    )

    ledger = PortfolioEngine.calculate_backtest(
        portfolio_identifier="zero-target",
        accounting_configuration=configuration,
        rebalance_strategy=strategy,
        signal_observations=signals,
        rebalance_inputs={},
        valuation_observations=pd.DataFrame(),
    ).ledger

    zero_execution = ledger[ledger["event_type"] == "execution"]
    assert set(zero_execution["record_kind"]) == {
        "execution_progress",
        "valuation_summary",
    }
    assert signals.reset_index().iloc[0]["asset_identifier"] == "UNHELD"


def test_full_retry_is_deterministic_and_publishes_no_duplicate_tail() -> None:
    first = build_example()["ledger"]
    second = build_example()["ledger"]

    pd.testing.assert_frame_equal(first, second)
    _validate_replay_against_existing(first, second)
    assert _new_ledger_tail(first, second).empty


def test_simulated_cost_is_applied_once_and_identifiers_ignore_signal_row_order(
    monkeypatch,
) -> None:
    cost_kernel_calls = 0
    sizing_kernel_calls = 0
    original_cost_kernel = ProportionalExecutionCostModel.cost_quantity_deltas
    original_sizing_kernel = TargetWeightExecutionModel._execution_facts

    def counted_cost_kernel(self, execution_facts):
        nonlocal cost_kernel_calls
        cost_kernel_calls += 1
        return original_cost_kernel(self, execution_facts)

    def counted_sizing_kernel(self, context, *, execution_assets):
        nonlocal sizing_kernel_calls
        sizing_kernel_calls += 1
        return original_sizing_kernel(
            self,
            context,
            execution_assets=execution_assets,
        )

    monkeypatch.setattr(
        ProportionalExecutionCostModel,
        "cost_quantity_deltas",
        counted_cost_kernel,
    )
    monkeypatch.setattr(
        TargetWeightExecutionModel,
        "_execution_facts",
        counted_sizing_kernel,
    )
    prices = pd.DataFrame(
        [
            ("2026-01-02T00:00:00Z", "A", 100.0, "USD", "a-price-1"),
            ("2026-01-02T00:00:00Z", "B", 50.0, "USD", "b-price-1"),
        ],
        columns=[
            "time_index",
            "asset_identifier",
            "price",
            "price_asset_identifier",
            "source_revision",
        ],
    )
    signal_rows = [
        ("2026-01-02T00:00:00Z", "ordered", "A", 0.5),
        ("2026-01-02T00:00:00Z", "ordered", "B", 0.25),
    ]
    configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-01T00:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(),
    )
    strategy = ImmediateSignal(
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=tuple(
                InstrumentExecutionSpec(
                    asset_identifier=asset,
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="USD",
                    settlement_style="cash",
                    terms_version="stock-v1",
                )
                for asset in ("A", "B")
            )
        ),
        execution_cost_model_instances=(ProportionalExecutionCostModel(rate=0.01),),
    )

    def calculate(rows):
        signals = pd.DataFrame(
            rows,
            columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
        ).set_index(["time_index", "signal_uid", "asset_identifier"])
        return PortfolioEngine.calculate_backtest(
            portfolio_identifier="cost-and-order",
            accounting_configuration=configuration,
            rebalance_strategy=strategy,
            signal_observations=signals,
            rebalance_inputs={},
            valuation_observations=prices,
        ).ledger

    ordered = calculate(signal_rows)
    assert cost_kernel_calls == 1
    assert sizing_kernel_calls == 1
    reversed_rows = calculate(list(reversed(signal_rows)))
    costs = ordered[ordered["record_kind"] == "cost"]

    assert len(costs) == 2
    assert costs["quantity_delta"].sum() == pytest.approx(-7.5)
    assert cost_kernel_calls == 2
    assert sizing_kernel_calls == 2
    assert ordered["event_identifier"].tolist() == reversed_rows["event_identifier"].tolist()
    pd.testing.assert_frame_equal(ordered, reversed_rows)


def test_linear_perpetual_funding_precedes_sizing_without_notional_cash() -> None:
    result = build_perpetual_example()
    ledger = result["ledger"]
    execution = ledger[ledger["event_type"] == "execution"]
    execution_summaries = execution[execution["record_kind"] == "valuation_summary"]
    funding_summaries = ledger[
        (ledger["event_type"] == "perpetual_funding")
        & (ledger["record_kind"] == "valuation_summary")
    ].reset_index(drop=True)
    costs = execution[execution["record_kind"] == "cost"]

    assert execution[execution["record_kind"] == "cash_delta"].empty
    assert result["positions"].iloc[0]["quantity"] == pytest.approx(8.0)
    assert result["cash"].iloc[0]["quantity"] == pytest.approx(880.0)
    assert funding_summaries.iloc[0]["nav_before"] == pytest.approx(990.0)
    assert funding_summaries.iloc[0]["nav_after"] == pytest.approx(890.0)
    assert execution_summaries.iloc[-1]["nav_before"] == pytest.approx(890.0)
    assert funding_summaries.iloc[1]["nav_before"] == pytest.approx(888.0)
    assert funding_summaries.iloc[1]["nav_after"] == pytest.approx(880.0)
    assert costs["quantity_delta"].sum() == pytest.approx(-12.0)
    assert ledger.loc[
        ledger["record_kind"] == "valuation_summary", "recognized_pnl"
    ].sum() == pytest.approx(-120.0)


def test_strategy_execution_price_and_revision_drive_partial_execution() -> None:
    signals = pd.DataFrame(
        [("2026-01-02T09:00:00Z", "time-weighted", "STOCK", 1.0)],
        columns=["time_index", "signal_uid", "asset_identifier", "signal_weight"],
    ).set_index(["time_index", "signal_uid", "asset_identifier"])
    bars = pd.DataFrame(
        [
            ("2026-01-02T10:00:00Z", "STOCK", 90.0, "bar-1"),
            ("2026-01-02T16:00:00Z", "STOCK", 80.0, "bar-2"),
        ],
        columns=["time_index", "asset_identifier", "close", "source_revision"],
    )
    prices = pd.DataFrame(
        [
            ("2026-01-02T10:00:00Z", "STOCK", 100.0, "USD", "mark-1"),
            ("2026-01-02T16:00:00Z", "STOCK", 100.0, "USD", "mark-2"),
        ],
        columns=[
            "time_index",
            "asset_identifier",
            "price",
            "price_asset_identifier",
            "source_revision",
        ],
    )
    strategy = TimeWeighted(
        execution_bars_instance=_source("execution-bars"),
        rebalance_start=dt.time(9, 0),
        rebalance_end=dt.time(23, 0),
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="STOCK",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="USD",
                    settlement_style="cash",
                    terms_version="stock-v1",
                ),
            )
        ),
    )
    configuration = PortfolioAccountingConfiguration(
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-02T08:00:00Z",
        position_valuation_model_instance=MarketPriceValuationModel(),
    )
    def calculate(execution_bars):
        return PortfolioEngine.calculate_backtest(
            portfolio_identifier="time-weighted-price",
            accounting_configuration=configuration,
            rebalance_strategy=strategy,
            signal_observations=signals,
            rebalance_inputs={"execution_bars": execution_bars},
            valuation_observations=prices,
        ).ledger

    ledger = calculate(bars)
    position_rows = ledger[ledger["record_kind"] == "position_delta"]
    summary = ledger[
        (ledger["event_type"] == "execution")
        & (ledger["record_kind"] == "valuation_summary")
    ].iloc[-1]

    assert position_rows.iloc[-1]["price"] == pytest.approx(80.0)
    assert position_rows.iloc[-1]["quantity_delta"] == pytest.approx(5.0)
    assert summary["recognized_pnl"] == pytest.approx(100.0)

    revised_bars = bars.copy()
    revised_bars.loc[revised_bars["source_revision"] == "bar-2", "source_revision"] = (
        "bar-2-corrected"
    )
    revised_ledger = calculate(revised_bars)
    assert position_rows.iloc[-1]["source_revision"] != revised_ledger[
        revised_ledger["record_kind"] == "position_delta"
    ].iloc[-1]["source_revision"]


def test_ledger_storage_and_model_graph_are_additive() -> None:
    models = set(portfolio_sqlalchemy_models())
    assert {PortfolioEventLedgerStorage, PortfolioStateStorage, PortfolioCashFlowsStorage} <= models
    assert PortfolioEngine._required_output_table() is PortfolioEventLedgerStorage
    assert PortfolioEventLedgerStorage.__index_names__ == [
        "time_index",
        "portfolio_identifier",
        "event_identifier",
        "event_revision",
        "record_identifier",
    ]
    assert (
        next(iter(PortfolioEventLedgerStorage.__table__.c.portfolio_identifier.foreign_keys)).column
        is PortfolioTable.__table__.c.unique_identifier
    )
    assert (
        next(iter(PortfolioEventLedgerStorage.__table__.c.asset_identifier.foreign_keys)).column
        is AssetTable.__table__.c.unique_identifier
    )


def test_canonical_ledger_groups_validate_and_cash_projection_is_derived() -> None:
    ledger = build_example()["ledger"]
    canonical = normalize_portfolio_event_ledger_frame(ledger)
    cash_flows = project_cash_flows(ledger)

    assert not canonical.index.has_duplicates
    assert "obligation_delta" not in set(cash_flows["cash_flow_type"])
    assert "obligation_settlement" in set(cash_flows["cash_flow_type"])


def test_accounting_state_restarts_from_the_canonical_ledger() -> None:
    result = build_example()
    restored = PortfolioAccounting.from_ledger(
        ledger=result["ledger"],
        portfolio_identifier="mock-eur-stock-portfolio",
        valuation_asset_identifier="USD",
        initial_nav=1_000.0,
        initial_state_time_index="2026-01-01T10:00:00Z",
        valuation_model=MarketPriceValuationModel(
            maximum_staleness=dt.timedelta(days=10)
        ),
    )

    pd.testing.assert_frame_equal(restored.state.positions, result["positions"])
    pd.testing.assert_frame_equal(restored.state.cash, result["cash"])
    pd.testing.assert_frame_equal(restored.state.obligations, result["obligations"])
    pd.testing.assert_frame_equal(
        restored.state.execution_progress,
        result["execution_progress"],
    )
    assert restored.ledger["event_digest"].tolist() == result["ledger"][
        "event_digest"
    ].tolist()


def test_state_projection_keeps_explicit_closed_rows() -> None:
    state = project_state(build_example()["ledger"]).reset_index()
    stock = state[state["state_identifier"] == "STOCK-EUR"].iloc[-1]
    receivable = state[state["state_kind"] == "obligation"].iloc[-1]

    assert stock["quantity"] == pytest.approx(0.0)
    assert bool(stock["is_closed"])
    assert receivable["quantity"] == pytest.approx(0.0)
    assert bool(receivable["is_closed"])


def test_canonical_ledger_rejects_tampered_event_record() -> None:
    ledger = build_example()["ledger"]
    tampered = ledger.copy()
    row_index = tampered[tampered["record_kind"] == "cash_delta"].index[0]
    tampered.loc[row_index, "quantity_delta"] += 1.0

    with pytest.raises(ValueError, match="event_digest"):
        normalize_portfolio_event_ledger_frame(tampered)


def test_existing_ledger_allows_exact_retry_and_blocks_unimplemented_correction() -> None:
    ledger = build_example()["ledger"]
    _validate_replay_against_existing(ledger, ledger.copy())
    corrected = ledger.copy()
    event_identifier = corrected.loc[
        corrected["event_type"] == "entitlement", "event_identifier"
    ].iloc[0]
    corrected.loc[corrected["event_identifier"] == event_identifier, "source_revision"] = (
        "corrected"
    )

    with pytest.raises(NotImplementedError, match="tail replay"):
        _validate_replay_against_existing(ledger, corrected)


def test_incremental_ledger_tail_equals_the_full_backtest() -> None:
    full = build_example()["ledger"]
    prefix = full[full["event_sequence"] <= 3].copy()

    _validate_replay_against_existing(prefix, full)
    tail = _new_ledger_tail(prefix, full)
    incremental = pd.concat([prefix, tail], ignore_index=True)

    pd.testing.assert_frame_equal(incremental, full)


def test_custom_model_example_executes_without_core_registration() -> None:
    ledger = build_custom_example()
    summaries = ledger[
        (ledger["record_kind"] == "valuation_summary") & (ledger["event_type"] == "usage_royalty")
    ]

    assert list(summaries["recognized_pnl"]) == pytest.approx([-24.0, -48.0])
    assert summaries.iloc[-1]["nav_after"] == pytest.approx(928.0)


def test_custom_model_configuration_is_importable_and_hash_stable() -> None:
    first = canonical_lifecycle_model_configuration(UsageRoyalty(rate_per_unit=2.0))
    second = canonical_lifecycle_model_configuration(UsageRoyalty(rate_per_unit=2.0))
    changed = canonical_lifecycle_model_configuration(UsageRoyalty(rate_per_unit=3.0))

    assert first == second
    assert first != changed
    assert first["class_import_path"] == {
        "module": "examples.msm_portfolios.portfolio_custom_cashflow_model_example",
        "qualname": "UsageRoyalty",
    }


def test_custom_model_batches_homogeneous_events_once(monkeypatch) -> None:
    calls = 0
    original = UsageRoyalty.calculate_cash_deltas

    def counted(self, context):
        nonlocal calls
        calls += 1
        return original(self, context)

    monkeypatch.setattr(UsageRoyalty, "calculate_cash_deltas", counted)
    build_custom_example()

    assert calls == 1


def test_as_known_mode_rejects_late_observation_lookahead() -> None:
    usage = pd.DataFrame(
        [
            {
                "time_index": "2026-02-01T00:00:00Z",
                "usage_event_identifier": "late",
                "source_revision": "1",
                "observed_at": "2026-02-02T00:00:00Z",
                "usage_units": 1.0,
                "settlement_asset_identifier": "USD",
            }
        ]
    )
    model = UsageRoyalty(rate_per_unit=1.0)
    accounting = PortfolioAccounting(
        portfolio_identifier="as-known",
        valuation_asset_identifier="USD",
        initial_nav=100.0,
        initial_state_time_index="2026-01-31T00:00:00Z",
        valuation_model=MarketPriceValuationModel(),
    )

    with pytest.raises(ValueError, match="without look-ahead"):
        accounting.run(
            valuation_observations=pd.DataFrame(),
            lifecycle_models=(model,),
            lifecycle_inputs={model.model_identifier: {"usage": usage}},
        )
