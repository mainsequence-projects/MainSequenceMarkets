"""Publish portfolio-calculated delta-hedged performance as a custom Index.

Position lags, financing, turnover, and transaction costs belong to the
portfolio calculation. The Index layer receives only the resulting observable.
"""

from __future__ import annotations

import pandas as pd

from msm.data_nodes.indices import configured_index_values_storage, normalize_index_values_frame


DAILY_INDEX_VALUES = configured_index_values_storage(cadence="1d")
INDEX_IDENTIFIER = "OPTION-DELTA-HEDGED-PERFORMANCE"


def publish_portfolio_values(portfolio_values: pd.DataFrame) -> pd.DataFrame:
    source = portfolio_values.rename(columns={"close": "value"}).copy()
    source["index_identifier"] = INDEX_IDENTIFIER
    source["definition_uid"] = None
    source["observation_status"] = "ready"
    source["source_as_of"] = source["time_index"]
    source["metadata_json"] = None
    return normalize_index_values_frame(source, storage_table=DAILY_INDEX_VALUES)


def run() -> dict[str, object]:
    portfolio_values = pd.DataFrame(
        {
            "time_index": pd.date_range("2026-01-01", periods=3, freq="D", tz="UTC"),
            "portfolio_identifier": ["DELTA-HEDGE"] * 3,
            "close": [100.0, 100.7, 100.2],
        }
    )
    published = publish_portfolio_values(
        portfolio_values[["time_index", "close"]]
    )
    return {
        "calculation_method": "custom",
        "portfolio_values": portfolio_values,
        "index_values": published,
    }


if __name__ == "__main__":
    print(run()["index_values"])
