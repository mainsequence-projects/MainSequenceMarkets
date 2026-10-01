"""Pure data preparation: no authentication, catalog calls, or live downloads."""

from datetime import UTC, datetime
from math import sqrt
from pathlib import Path

import pandas as pd

FIXTURE_NAME = "yahoo_spy_qqq_iwm_2026-06-15_2026-07-17.csv"
START = datetime(2026, 6, 15, tzinfo=UTC)
SYMBOLS = ("SPY", "QQQ", "IWM")
VOLATILITY_WINDOW = 5


def recorded_prices(*, symbols=SYMBOLS, start=START, after=None) -> pd.DataFrame:
    table = pd.read_csv(Path(__file__).with_name("data") / FIXTURE_NAME)
    table = table.rename(columns={"date": "time_index"})
    table["time_index"] = pd.to_datetime(table["time_index"], utc=True).astype(
        "datetime64[ns, UTC]"
    )
    table = table.loc[table.symbol.isin(symbols) & (table.time_index >= start)]
    if after is not None:
        table = table.loc[table.time_index > after]
    return table.sort_values(["time_index", "symbol"]).set_index(["time_index", "symbol"])[
        ["adjusted_close"]
    ]


def daily_returns(prices: pd.DataFrame, *, after=None) -> pd.DataFrame:
    """Compute within each symbol before filtering to the new output interval."""
    if prices.empty:
        index = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([], dtype="datetime64[ns, UTC]"), []],
            names=["time_index", "symbol"],
        )
        return pd.DataFrame(index=index, columns=["daily_return"], dtype=float)
    table = prices.reset_index().sort_values(["symbol", "time_index"])
    table["daily_return"] = table.groupby("symbol")["adjusted_close"].pct_change(fill_method=None)
    table = table.dropna(subset=["daily_return"])
    if after is not None:
        table = table.loc[table.time_index > after]
    return table.sort_values(["time_index", "symbol"]).set_index(["time_index", "symbol"])[
        ["daily_return"]
    ]


def rolling_volatility(
    returns: pd.DataFrame, *, window_sessions=VOLATILITY_WINDOW, after=None
) -> pd.DataFrame:
    """Calculate full trailing windows per symbol before filtering new observations."""
    if window_sessions < 2:
        raise ValueError("Volatility requires at least two return observations.")
    if returns.empty:
        index = pd.MultiIndex.from_arrays(
            [pd.DatetimeIndex([], dtype="datetime64[ns, UTC]"), []],
            names=["time_index", "symbol"],
        )
        return pd.DataFrame(index=index, columns=["annualized_volatility"], dtype=float)
    table = returns.reset_index().sort_values(["symbol", "time_index"])
    table["annualized_volatility"] = table.groupby("symbol")["daily_return"].transform(
        lambda values: values.rolling(window_sessions, min_periods=window_sessions).std(ddof=1)
    ) * sqrt(252)
    table = table.dropna(subset=["annualized_volatility"])
    if after is not None:
        table = table.loc[table.time_index > after]
    return table.sort_values(["time_index", "symbol"]).set_index(["time_index", "symbol"])[
        ["annualized_volatility"]
    ]


def preview() -> str:
    prices = recorded_prices()
    returns = daily_returns(prices)
    volatility = rolling_volatility(returns)
    return (
        f"Recorded prices: {len(prices)} rows\nDaily returns: {len(returns)} rows\n"
        f"Rolling volatility ({VOLATILITY_WINDOW} sessions): {len(volatility)} rows\n\n"
        f"{volatility.tail(6)}"
    )
