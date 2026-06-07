from __future__ import annotations

import datetime as dt
from typing import Any
from uuid import UUID

import pandas as pd

from msm.data_nodes.accounts import HoldingsDataNode

from msm.data_nodes.accounts.virtual_funds.storage import VirtualFundHoldingsStorage
from msm.services.accounts.virtual_fund_holdings import (
    build_virtual_fund_holdings_frame as build_virtual_fund_holdings_service_frame,
)


class VirtualFundHoldings(HoldingsDataNode):
    """DataNode users can subclass to import virtual-fund holdings."""

    @classmethod
    def _required_storage_table(cls) -> type[VirtualFundHoldingsStorage]:
        return VirtualFundHoldingsStorage

    def build_virtual_fund_holdings_frame(
        self,
        *,
        allocation_time: dt.datetime | str,
        virtual_fund_uid: UUID | str,
        source_account_holdings_set_uid: UUID | str,
        virtual_fund_holdings_set_uid: UUID | str,
        allocations: list[dict[str, Any] | Any],
        target_trade_time: dt.datetime | str | None = None,
    ) -> pd.DataFrame:
        return build_virtual_fund_holdings_service_frame(
            allocation_time=allocation_time,
            virtual_fund_uid=virtual_fund_uid,
            source_account_holdings_set_uid=source_account_holdings_set_uid,
            virtual_fund_holdings_set_uid=virtual_fund_holdings_set_uid,
            allocations=allocations,
            target_trade_time=target_trade_time,
        )

    def set_virtual_fund_holdings_frame(
        self,
        *,
        allocation_time: dt.datetime | str,
        virtual_fund_uid: UUID | str,
        source_account_holdings_set_uid: UUID | str,
        virtual_fund_holdings_set_uid: UUID | str,
        allocations: list[dict[str, Any] | Any],
        target_trade_time: dt.datetime | str | None = None,
    ) -> VirtualFundHoldings:
        return self.set_frame(
            self.build_virtual_fund_holdings_frame(
                allocation_time=allocation_time,
                virtual_fund_uid=virtual_fund_uid,
                source_account_holdings_set_uid=source_account_holdings_set_uid,
                virtual_fund_holdings_set_uid=virtual_fund_holdings_set_uid,
                allocations=allocations,
                target_trade_time=target_trade_time,
            )
        )


__all__ = ["VirtualFundHoldings"]
