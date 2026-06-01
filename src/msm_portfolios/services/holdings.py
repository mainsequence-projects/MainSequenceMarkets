from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

import pandas as pd

from msm.services.holdings import build_holdings_frame, validate_holdings_frame

from msm_portfolios.data_nodes.storage import FundHoldingsStorage


def build_fund_holdings_frame(
    *,
    holdings_date: dt.datetime | str,
    fund_uid: UUID | str,
    positions: Sequence[Mapping[str, Any] | Any],
    holdings_set_uid: UUID | str | None = None,
    is_trade_snapshot: bool = False,
    target_trade_time: dt.datetime | str | None = None,
) -> pd.DataFrame:
    return build_holdings_frame(
        storage_table=FundHoldingsStorage,
        holdings_date=holdings_date,
        owner_uid=fund_uid,
        positions=positions,
        holdings_set_uid=holdings_set_uid,
        is_trade_snapshot=is_trade_snapshot,
        target_trade_time=target_trade_time,
    )


__all__ = [
    "build_fund_holdings_frame",
    "validate_holdings_frame",
]
