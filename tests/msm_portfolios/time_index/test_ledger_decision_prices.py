"""A ledger books a rebalance with the prices it was decided with (issue #150, ADR 0058).

A rebalance sized at its decision fixes its shares at the instant before its earliest
moment, from each asset's last price then. The ledger books exactly those shares, even
when that price is older than the ledger's opening: a ledger that opens at its first
rebalance books it at the opening, and a ledger that opens with no price before the
decision finds the one before its opening. In a portfolio run the rows the rebalance
kept give that price; outside one, as in a node Job, the ledger reads it.

The ledger converts every price at its currency's last FX rate, as the rebalance does,
even one older than its opening (issue #153, ADR 0059).

NYSE closes (21:00 UTC) are 40, 50, 60, 70 and 80 on 2026-11-17, 18, 19, 20 and 23; each
rebalance targets half of a 10,000 USD NAV unless stated.
"""

from __future__ import annotations

import json
import uuid
from contextlib import nullcontext
from dataclasses import dataclass

import pandas as pd
import pytest

from msm_portfolios.accounting import MarketPriceValuationModel, PortfolioAccountingConfiguration
from msm_portfolios.accounting.projections import project_portfolio_values
from msm_portfolios.rebalance_strategy import (
    ImmediateSignal,
    InstrumentExecutionSpec,
    TargetWeightExecutionModel,
)
from msm_portfolios.time_index.constants import ASSET_IDENTIFIER
from msm_portfolios.time_index.portfolios.accounting import (
    PortfolioEngine,
    PortfolioEngineConfiguration,
    _Decision,
    _unpriced,
)
from msm_portfolios.time_index.portfolios.run_rows import run_rows
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioEventLedgerStorage,
    PortfolioRebalanceStateStorage,
)
from tests.support.pinned_identities import _bound
from tests.support.rebalance import (
    IncrementalRebalance,
    PublishedTable,
    calendar,
    position_deltas,
    prices,
    signal_frame,
    stock_strategy,
    utc,
)

CLOSES = {
    "2026-11-17": 40.0,
    "2026-11-18": 50.0,
    "2026-11-19": 60.0,
    "2026-11-20": 70.0,
    "2026-11-23": 80.0,
}
FX_INDEX = ["time_index", "base_asset_identifier", "quote_asset_identifier"]


def closes(asset: str = "AAPL", values: dict[str, float] = CLOSES) -> pd.DataFrame:
    return prices(*((asset, f"{day}T21:00Z", price) for day, price in values.items()))


@dataclass
class Portfolio:
    """One portfolio's rebalance and ledger over published prices."""

    strategy: object
    signals: PublishedTable
    source: PublishedTable
    fx: PublishedTable | None
    rebalance: IncrementalRebalance
    opens: str

    def ledger(self) -> tuple[pd.DataFrame, list[str]]:
        """Run the ledger on the rebalance state so far: its rows, and the reads it made
        of the price source."""

        node = object.__new__(PortfolioEngine)
        node.config = PortfolioEngineConfiguration(
            portfolio_identifier="portfolio",
            valuation_asset_identifier="USD",
            valuation_source_instance=self.source,
            valuation_column="close",
            fx_source_instance=self.fx,
            accounting_configuration=PortfolioAccountingConfiguration(
                initial_nav=10_000.0,
                initial_state_time_index=self.opens,
                position_valuation_model_instance=MarketPriceValuationModel(),
            ),
            portfolio_rebalance_instance=PublishedTable.build(
                "portfolio-rebalance",
                self.rebalance.persisted,
                index=["time_index", "portfolio_identifier", "rebalance_intent_id", ASSET_IDENTIFIER],
            ),
            rebalance_strategy_instance=self.strategy,
        )
        node._retirement_boundary = lambda _portfolio_identifier: None
        node.get_df_between_dates = lambda **_kwargs: pd.DataFrame()
        reads: list[str] = []
        originals = {}
        for name in ("get_df_between_dates", "get_last_observation"):
            originals[name] = getattr(self.source, name)
            setattr(self.source, name, _counted(reads, name, originals[name]))
        try:
            with _bound(PortfolioEventLedgerStorage, str(uuid.uuid4())) as storage:
                node.output_table = storage
                ledger = node.update().reset_index()
        finally:
            for name, method in originals.items():
                setattr(self.source, name, method)
        return ledger, reads

    def decision_prices(self) -> dict[str, float]:
        """The price each rebalance recorded as its decision price, by signal time."""

        rows = self.rebalance.persisted.reset_index()
        return {
            row["target_signal_time_index"].isoformat(): json.loads(row["strategy_state"])[
                "decision_price"
            ]
            for row in rows.sort_values("time_index").to_dict("records")
        }


def _counted(reads: list[str], name: str, method):
    def counted(**kwargs):
        reads.append(name)
        return method(**kwargs)

    return counted


def portfolio(
    storage,
    *,
    signals: list[tuple[str, dict[str, float]]],
    opens: str,
    price_rows: pd.DataFrame | None = None,
    fx_rows: pd.DataFrame | None = None,
    strategy=None,
    assets: tuple[str, ...] = ("AAPL",),
) -> Portfolio:
    strategy = stock_strategy(calendar(), assets) if strategy is None else strategy
    signal_table = PublishedTable.build(
        "signals", signal_frame(signals), index=["time_index", "signal_uid", ASSET_IDENTIFIER]
    )
    source = PublishedTable.build(
        "prices",
        closes() if price_rows is None else price_rows,
        index=["time_index", ASSET_IDENTIFIER],
    )
    fx = None if fx_rows is None else PublishedTable.build("fx", fx_rows, index=FX_INDEX)
    rebalance = IncrementalRebalance(
        strategy=strategy, signals=signal_table, prices=source, storage=storage, assets=assets
    )
    # The rebalance reads its prices from the ledger's opening in a portfolio run (#139).
    rebalance.node.ledger_initial_state = utc(opens)
    rebalance.node.fx_source = fx
    return Portfolio(strategy, signal_table, source, fx, rebalance, opens)


def run_once(*, signal: str, opens: str, in_run: bool) -> tuple[Portfolio, list, list]:
    """One run of the rebalance and then its ledger, after the 11-20 close."""

    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        built = portfolio(storage, signals=[(signal, {"AAPL": 0.5})], opens=opens)
        with run_rows() if in_run else nullcontext():
            built.rebalance.run("2026-11-20T23:00:00Z")
            ledger, reads = built.ledger()
    return built, position_deltas(ledger), reads


RUNS = pytest.mark.parametrize("in_run", [False, True], ids=["alone", "in_a_run"])


@RUNS
@pytest.mark.parametrize(
    "opens",
    ["2026-11-19T15:30:00Z", "2026-11-19T00:00:00Z"],
    ids=["opening_at_the_signal", "opening_after_the_last_close"],
)
def test_a_mid_session_rebalance_is_booked_with_the_close_before_it(opens, in_run) -> None:
    """A signal an hour into the 11-19 session is decided with the 11-18 close of 50: the
    ledger buys 100 shares at the 11-19 close, whether it opens at the signal or earlier
    that day, with no price between its opening and the decision.

    In a run the rows the rebalance kept hold that close, and the ledger reads nothing.
    """

    built, deltas, reads = run_once(signal="2026-11-19T15:30:00Z", opens=opens, in_run=in_run)

    assert built.decision_prices() == {"2026-11-19T15:30:00+00:00": 50.0}
    assert deltas == [(utc("2026-11-19T21:00Z"), "AAPL", 100.0, 60.0)]
    assert reads == ([] if in_run else ["get_df_between_dates", "get_last_observation"])


@RUNS
def test_a_price_at_the_opening_does_not_size_a_rebalance_decided_before_it(in_run) -> None:
    """A signal at the 11-18 close is decided with the 11-17 close of 40. A ledger that
    opens at the signal books it at its opening with that price, not the close of 50 at
    the opening, and buys 125 shares, as a ledger that opened the day before does."""

    at_signal, deltas, reads = run_once(
        signal="2026-11-18T21:00:00Z", opens="2026-11-18T21:00:00Z", in_run=in_run
    )
    _, earlier, _ = run_once(
        signal="2026-11-18T21:00:00Z", opens="2026-11-17T00:00:00Z", in_run=in_run
    )

    assert at_signal.decision_prices() == {"2026-11-18T21:00:00+00:00": 40.0}
    assert deltas == earlier == [(utc("2026-11-19T21:00Z"), "AAPL", 125.0, 60.0)]
    assert reads == ([] if in_run else ["get_df_between_dates", "get_last_observation"])


def test_in_a_later_run_the_ledger_reads_the_price_the_kept_rows_lack() -> None:
    """The ledger opens at its first rebalance (11-19 15:30, 100 shares); a second one at
    11-20 15:30 targets 0.2. In the run after both, the rebalance reads from the ledger's
    opening and needs no row before it, so the ledger reads the 11-18 close itself and
    books what it books outside a run."""

    def booked(*, in_run: bool) -> tuple[list, list]:
        with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
            built = portfolio(
                storage,
                signals=[
                    ("2026-11-19T15:30:00Z", {"AAPL": 0.5}),
                    ("2026-11-20T15:30:00Z", {"AAPL": 0.2}),
                ],
                opens="2026-11-19T15:30:00Z",
            )
            built.rebalance.run("2026-11-19T23:00:00Z")
            built.rebalance.run("2026-11-20T23:00:00Z")
            with run_rows() if in_run else nullcontext():
                built.rebalance.run("2026-11-23T23:00:00Z")
                ledger, reads = built.ledger()
        return position_deltas(ledger), reads

    alone, alone_reads = booked(in_run=False)
    shared, shared_reads = booked(in_run=True)

    assert shared == alone
    # 0.2 of 4,000 cash and 100 shares at 60 is 33 shares: 67 are sold.
    assert alone == [
        (utc("2026-11-19T21:00Z"), "AAPL", 100.0, 60.0),
        (utc("2026-11-20T21:00Z"), "AAPL", -67.0, 70.0),
    ]
    assert alone_reads == ["get_df_between_dates", "get_last_observation"]
    assert shared_reads == ["get_last_observation"]


def eur_stock() -> ImmediateSignal:
    """A strategy trading SAP in whole shares quoted in EUR."""

    return ImmediateSignal(
        calendar_events_instance=calendar(),
        calendar_identifier="XNYS",
        execution_model_instance=TargetWeightExecutionModel(
            instrument_specs=(
                InstrumentExecutionSpec(
                    asset_identifier="SAP",
                    quantity_unit="shares",
                    target_measure="market_value_weight",
                    contract_multiplier=1.0,
                    quantity_step=1.0,
                    price_asset_identifier="EUR",
                    settlement_style="cash",
                    terms_version="stock-v1",
                ),
            )
        ),
    )


def eur_rates(*rows: tuple[str, float]) -> pd.DataFrame:
    """``(time, rate)`` rows of EUR into USD."""

    return pd.DataFrame(
        [
            (utc(stamp), "EUR", "USD", rate, f"fx-{position}")
            for position, (stamp, rate) in enumerate(rows)
        ],
        columns=[*FX_INDEX, "rate", "source_revision"],
    )


def sap_portfolio(storage, *, opens: str, closes_eur: dict[str, float], rates) -> Portfolio:
    return portfolio(
        storage,
        signals=[("2026-11-19T15:30:00Z", {"SAP": 0.5})],
        opens=opens,
        price_rows=closes("SAP", closes_eur).assign(price_asset_identifier="EUR"),
        fx_rows=rates,
        strategy=eur_stock(),
        assets=("SAP",),
    )


def test_a_rebalance_decided_before_the_opening_converts_at_the_rate_it_was_decided_with() -> None:
    """SAP closes at 50 EUR. EUR is worth 1.25 USD from the 11-18 close and 2 USD from
    11-19 20:00. The rebalance decided at 11-19 15:30, the ledger's opening, converts at
    1.25, so the ledger buys 5,000 / 62.5 = 80 shares at the 11-19 close."""

    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        built = sap_portfolio(
            storage,
            opens="2026-11-19T15:30:00Z",
            closes_eur={"2026-11-18": 50.0, "2026-11-19": 50.0},
            rates=eur_rates(("2026-11-18T21:00Z", 1.25), ("2026-11-19T20:00Z", 2.0)),
        )
        built.rebalance.run("2026-11-20T23:00:00Z")
        ledger, _ = built.ledger()

    assert built.decision_prices() == {"2026-11-19T15:30:00+00:00": 62.5}
    assert position_deltas(ledger) == [(utc("2026-11-19T21:00Z"), "SAP", 80.0, 50.0)]


@RUNS
@pytest.mark.parametrize(
    "opens",
    ["2026-11-19T15:30:00Z", "2026-11-19T00:00:00Z"],
    ids=["opening_at_the_signal", "opening_before_the_signal"],
)
def test_the_ledger_converts_at_the_last_rate_before_its_opening(opens, in_run) -> None:
    """SAP closes at 50, 50 and 60 EUR on 11-18, 11-19 and 11-20. The only EUR rate is
    1.25 USD, at the 11-18 close, before the ledger opens. The ledger converts at it, as
    the rebalance does: it buys 80 shares at the 11-19 close, and values them at the 11-20
    close at 80 x 60 x 1.25 = 6,000 USD, for a NAV of 11,000."""

    with _bound(PortfolioRebalanceStateStorage, str(uuid.uuid4())) as storage:
        built = sap_portfolio(
            storage,
            opens=opens,
            closes_eur={"2026-11-18": 50.0, "2026-11-19": 50.0, "2026-11-20": 60.0},
            rates=eur_rates(("2026-11-18T21:00Z", 1.25)),
        )
        with run_rows() if in_run else nullcontext():
            built.rebalance.run("2026-11-20T23:00:00Z")
            ledger, _ = built.ledger()

    assert position_deltas(ledger) == [(utc("2026-11-19T21:00Z"), "SAP", 80.0, 50.0)]
    values = project_portfolio_values(ledger, initial_nav=10_000.0).reset_index()
    closes_by_time = dict(zip(values["time_index"], values["close"], strict=True))
    assert closes_by_time[utc("2026-11-19T21:00Z")] == pytest.approx(1.0)
    assert closes_by_time[utc("2026-11-20T21:00Z")] == pytest.approx(1.1)


def test_a_decision_needs_the_earlier_rows_of_the_items_it_has_no_row_for() -> None:
    """The ledger opens on 11-19. AAPL has rows from 11-19, MSFT first appears at the 11-20
    close, between the decisions of 11-20 and 11-23, and SAP never does. Each decision needs
    the last row before the opening of the items it has no row for by then. A decision
    made before the opening, on 11-18, needs every item's last row before its earliest
    moment. A zero target needs none. The rows are read once, flat or indexed."""

    opens = utc("2026-11-19T00:00Z")
    rows = prices(
        ("AAPL", "2026-11-19T14:00Z", 1.0),
        ("AAPL", "2026-11-19T21:00Z", 1.0),
        ("MSFT", "2026-11-20T21:00Z", 1.0),
        ("MSFT", "2026-11-23T14:00Z", 1.0),
    )
    weights = {"AAPL": 0.3, "MSFT": 0.3, "SAP": 0.3, "IBM": 0.0}
    decisions = [
        _Decision(intent_id=intent, earliest=utc(earliest), target_weights=weights)
        for intent, earliest in (
            ("before-the-opening", "2026-11-18T15:30Z"),
            ("before-msft", "2026-11-20T15:30Z"),
            ("after-msft", "2026-11-23T15:30Z"),
        )
    ]

    for frame in (rows, rows.set_index(["time_index", ASSET_IDENTIFIER])):
        assert _unpriced(
            decisions,
            frame,
            start=opens,
            key=ASSET_IDENTIFIER,
            items=lambda decision: decision.sized_assets,
        ) == {
            utc("2026-11-18T15:30Z"): ["AAPL", "MSFT", "SAP"],
            opens: ["MSFT", "SAP"],
        }
