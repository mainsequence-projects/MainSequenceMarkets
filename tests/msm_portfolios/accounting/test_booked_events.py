"""A portfolio refuses to run while it holds an asset with an event nothing books (ADR 0065).

An asset's type lists the events it can have (``AssetType.event_types``). Each must be
booked by a lifecycle model or included in the prices. Adjusted prices, the default,
include every event. The asset rows and types are read from a migrated SQLite Markets.
"""

from __future__ import annotations

import pytest

from msm_portfolios.accounting import DividendCashFlowModel
from msm_portfolios.accounting.events import ADJUSTED
from msm_portfolios.time_index.portfolios.accounting import require_booked_events
from tests.support.sqlite_markets import (
    _insert,
    make_sqlite_markets,
    serve_row_operations,
)


@pytest.fixture
def markets(tmp_path, monkeypatch, sqlite_revisions):
    markets = make_sqlite_markets(tmp_path, monkeypatch, template=sqlite_revisions.file("head"))
    for asset_type, event_types in (("equity", ["dividend", "split"]), ("crypto", [])):
        _insert(
            markets.engine,
            "ms_markets__assettype",
            asset_type=asset_type,
            event_types=event_types,
        )
    for identifier, asset_type in (("AAPL", "equity"), ("BTC", "crypto")):
        _insert(
            markets.engine,
            "ms_markets__asset",
            unique_identifier=identifier,
            asset_type=asset_type,
        )
    serve_row_operations(monkeypatch, markets)
    return markets


def test_adjusted_prices_book_every_event_and_read_nothing() -> None:
    """No Markets read: the test runs without a database."""
    require_booked_events(["AAPL", "UNREGISTERED"], in_price=ADJUSTED, lifecycle_models=())


def test_an_event_nothing_books_refuses_the_run(markets) -> None:
    with pytest.raises(ValueError, match="AAPL: dividend, split"):
        require_booked_events(["AAPL", "BTC"], in_price=(), lifecycle_models=())


def test_a_model_or_the_price_books_each_event(markets) -> None:
    with pytest.raises(ValueError, match=r"AAPL: split\."):
        require_booked_events(
            ["AAPL"], in_price=(), lifecycle_models=(DividendCashFlowModel(),)
        )

    require_booked_events(
        ["AAPL", "BTC"], in_price=("split",), lifecycle_models=(DividendCashFlowModel(),)
    )


def test_an_asset_markets_does_not_know_is_refused(markets) -> None:
    with pytest.raises(ValueError, match="does not know, so their events are unknown: GHOST"):
        require_booked_events(["BTC", "GHOST"], in_price=(), lifecycle_models=())
