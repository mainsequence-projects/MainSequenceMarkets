from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import pandas as pd

from msm.data_nodes.accounts import HoldingsDataNode

from msm_portfolios.data_nodes.storage import FundHoldingsStorage
from msm_portfolios.services.holdings import (
    build_fund_holdings_frame as build_fund_holdings_service_frame,
)


class VirtualFundHoldings(HoldingsDataNode):
    """DataNode users can subclass to import virtual-fund holdings."""

    @classmethod
    def _required_storage_table(cls) -> type[FundHoldingsStorage]:
        return FundHoldingsStorage

    def build_fund_holdings_frame(
        self,
        *,
        holdings_date: dt.datetime | str,
        fund_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
        holdings_set_uid: UUID | str | None = None,
        is_trade_snapshot: bool = False,
        target_trade_time: dt.datetime | str | None = None,
    ) -> pd.DataFrame:
        return build_fund_holdings_service_frame(
            holdings_date=holdings_date,
            fund_uid=fund_uid,
            positions=positions,
            holdings_set_uid=holdings_set_uid,
            is_trade_snapshot=is_trade_snapshot,
            target_trade_time=target_trade_time,
        )

    def set_fund_holdings_frame(
        self,
        *,
        holdings_date: dt.datetime | str,
        fund_uid: UUID | str,
        positions: list[dict[str, Any] | Any],
        holdings_set_uid: UUID | str | None = None,
        is_trade_snapshot: bool = False,
        target_trade_time: dt.datetime | str | None = None,
    ) -> VirtualFundHoldings:
        return self.set_frame(
            self.build_fund_holdings_frame(
                holdings_date=holdings_date,
                fund_uid=fund_uid,
                positions=positions,
                holdings_set_uid=holdings_set_uid,
                is_trade_snapshot=is_trade_snapshot,
                target_trade_time=target_trade_time,
            )
        )


__all__ = ["VirtualFundHoldings"]
