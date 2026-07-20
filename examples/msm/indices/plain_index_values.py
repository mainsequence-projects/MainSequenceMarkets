"""Publish one Index identity through separate frequency-owned datasets.

This is an identity and storage example. It deliberately does not model the
instrument or process that supplied the 10-year swap-yield observation.
"""

from __future__ import annotations

import pandas as pd

from mainsequence.meta_tables import PlatformTimeIndexMetaTable

from msm.data_nodes.indices import IndexValuesDataNode, configured_index_values_storage
from msm.api.indices import Index

INDEX_IDENTIFIER = "USD_SWAP_10Y"
ONE_MINUTE_VALUES_STORAGE = configured_index_values_storage(cadence="1m")
DAILY_VALUES_STORAGE = configured_index_values_storage(cadence="1d")
FREQUENCY_STORAGE_MODELS = (ONE_MINUTE_VALUES_STORAGE, DAILY_VALUES_STORAGE)


def reconcile_and_list_dataset_states(index_uid: str):
    """Backfill and inspect population after storage registration and persistence."""

    reconciliation = Index.reconcile_dataset_availability(index_uids=(index_uid,))
    states = Index.list_datasets(index_uid, include_empty=True)
    return reconciliation, states


def list_numeric_timestamped_related_meta_tables(index_uid: str):
    """Discover related time-series tables with at least one numeric data column."""

    return Index.list_related_meta_tables(
        index_uid,
        numeric=True,
        timestamped=True,
    )


class Swap10YOneMinuteDataNode(IndexValuesDataNode):
    """Publish the one-minute `USD_SWAP_10Y` dataset."""

    @classmethod
    def _required_storage_table(cls) -> type[PlatformTimeIndexMetaTable]:
        return ONE_MINUTE_VALUES_STORAGE


class Swap10YDailyDataNode(IndexValuesDataNode):
    """Publish the daily `USD_SWAP_10Y` dataset."""

    @classmethod
    def _required_storage_table(cls) -> type[PlatformTimeIndexMetaTable]:
        return DAILY_VALUES_STORAGE


def run() -> dict[str, object]:
    """Return normalized intraday/daily observations and calculation identity rules."""

    intraday_source = pd.DataFrame(
        [
            {
                "time_index": "2026-07-17T14:00:00Z",
                "index_identifier": INDEX_IDENTIFIER,
                "value": 0.04192,
                "observation_status": "preliminary",
            },
            {
                "time_index": "2026-07-17T14:01:00Z",
                "index_identifier": INDEX_IDENTIFIER,
                "value": 0.04195,
                "observation_status": "preliminary",
            },
        ]
    )
    daily_source = pd.DataFrame(
        [
            {
                "time_index": "2026-07-17T23:59:59Z",
                "index_identifier": INDEX_IDENTIFIER,
                "value": 0.04205,
                "observation_status": "final",
            }
        ]
    )

    one_minute_values = Swap10YOneMinuteDataNode.validate_frame(intraday_source)
    daily_values = Swap10YDailyDataNode.validate_frame(daily_source)
    calculation_identity = {
        # A software-only implementation change preserves the economic meaning.
        "implementation_change": (INDEX_IDENTIFIER, INDEX_IDENTIFIER),
        # Formula Indexes use prospective formula versions under one identity.
        "prospective_formula_versions": (INDEX_IDENTIFIER, "v1 -> v2"),
        # Simultaneously observable methods are different Index identities.
        "coexisting_methods": ("USD_SWAP_10Y_METHOD_A", "USD_SWAP_10Y_METHOD_B"),
    }
    return {
        "index_identity": {
            "unique_identifier": INDEX_IDENTIFIER,
            "index_type": "interest_rate",
            "display_name": "USD 10-Year Swap Yield",
        },
        "index_identifier": INDEX_IDENTIFIER,
        "migration_models": FREQUENCY_STORAGE_MODELS,
        "frequency_datasets": {
            "1m": {
                "data_node": Swap10YOneMinuteDataNode,
                "storage_table": ONE_MINUTE_VALUES_STORAGE,
                "values": one_minute_values,
            },
            "1d": {
                "data_node": Swap10YDailyDataNode,
                "storage_table": DAILY_VALUES_STORAGE,
                "values": daily_values,
            },
        },
        "calculation_identity": calculation_identity,
    }


if __name__ == "__main__":
    output = run()
    for frequency, dataset in output["frequency_datasets"].items():
        storage_table = dataset["storage_table"]
        print(f"{frequency}: {storage_table.__table__.name}")
        print(dataset["values"])
    print(output["calculation_identity"])
