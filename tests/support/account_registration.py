"""Account registration requests, and a log of the MetaTables requests they cost."""

from __future__ import annotations

import datetime as dt

from metatables import MetaTable

DAY_1 = dt.datetime(2026, 11, 10, 21, 0, tzinfo=dt.UTC)


def _record_operations(monkeypatch) -> list[str]:
    """Each MetaTables request from here on: ``read`` or ``transaction``."""

    operations: list[str] = []
    execute_operation, execute_transaction = MetaTable.execute_operation, MetaTable.execute_transaction

    def recorded_operation(cls, operation, *, timeout=None):
        operations.append("read" if operation.operation == "select" else operation.operation)
        return execute_operation(operation, timeout=timeout)

    def recorded_transaction(cls, transaction, *, timeout=None):
        operations.append("transaction")
        return execute_transaction(transaction, timeout=timeout)

    monkeypatch.setattr(MetaTable, "execute_operation", classmethod(recorded_operation))
    monkeypatch.setattr(MetaTable, "execute_transaction", classmethod(recorded_transaction))
    return operations


def _request(
    *,
    holdings_date=DAY_1,
    positions=None,
    overwrite=False,
    account_name="Venue account",
    assets=None,
    cash_currency="USD",
    **account,
):
    return {
        "account": {
            "unique_identifier": "venue::account-1",
            "account_name": account_name,
            "is_paper": True,
            "account_is_active": True,
            **account,
        },
        "assets": assets
        if assets is not None
        else [
            {
                "unique_identifier": "venue::AAPL",
                "asset_type": {"asset_type": "Venue Equity", "display_name": "Venue equity"},
                "snapshot": {"name": "Apple Inc.", "ticker": "AAPL", "exchange_code": "XNAS"},
            },
            {
                "unique_identifier": "venue::MSFT",
                "asset_type": {"asset_type": "venue_equity", "display_name": "Other name"},
                "snapshot": {"name": "Microsoft", "ticker": "MSFT", "exchange_code": "XNAS"},
            },
        ],
        "cash_currency": cash_currency,
        "holdings_date": holdings_date.isoformat(),
        "overwrite": overwrite,
        "positions": positions
        if positions is not None
        else [
            {"asset_identifier": "venue::AAPL", "quantity": "3", "extra_details": {"lot": 1}},
            {"asset_identifier": "venue::MSFT", "quantity": "1.5", "direction": -1},
            {"asset_identifier": "USD", "quantity": "1000"},
        ],
    }
