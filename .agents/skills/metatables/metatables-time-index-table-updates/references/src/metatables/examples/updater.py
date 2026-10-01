"""Incremental producer using deterministic sample data, not a market data feed."""
from datetime import datetime
from uuid import UUID

import pandas as pd
from pydantic import Field

from metatables import TimeIndexTableUpdateConfig, TimeIndexTableUpdater

from .tables import Balance


class BalanceConfig(TimeIndexTableUpdateConfig):
    account_uid: UUID = Field(description="Account populated by this producer.")
    start: datetime = Field(description="First UTC observation to include in a backfill.")


def sample_balances(config: BalanceConfig, after: datetime | None = None) -> pd.DataFrame:
    times = pd.date_range("2026-01-01", periods=3, tz="UTC").as_unit("ns")
    frame = pd.DataFrame({
        "time_index": times, "account_uid": [config.account_uid] * len(times),
        "balance": [100.0, 105.0, 103.0],
    })
    frame = frame.loc[frame.time_index >= config.start]
    if after is not None:
        frame = frame.loc[frame.time_index > after]
    return frame.set_index(["time_index", "account_uid"])


class BalanceUpdater(TimeIndexTableUpdater):
    def dependencies(self):
        return {}

    def update(self):
        latest = self.update_statistics.get_max_time_in_update_statistics()
        return sample_balances(self.config, after=latest)


def run(config: BalanceConfig):
    # Migrate Account and Balance, and insert the account row, before running.
    updater = BalanceUpdater(config=config, output_table=Balance, hash_namespace="ledger-example")
    return updater.run()
