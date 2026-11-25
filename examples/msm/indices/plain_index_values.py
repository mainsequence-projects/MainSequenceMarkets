"""Publish one Index identity through separate frequency-owned datasets.

The two tables are the provider's own: class statements on its declarative base, in its
namespace and storage app, migrated by its own provider
(`index_values_frequency_migration.py`), which lists the classes.

This is an identity and storage example. It deliberately does not model the
instrument or process that supplied the 10-year swap-yield observation.
"""

from __future__ import annotations

import pandas as pd
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import PlatformTimeIndexMetaTable, sqlalchemy_naming_convention

from msm.time_index.indices import IndexValuesInstance, IndexValuesUpdater
from msm.api.indices import Index

INDEX_IDENTIFIER = "USD_SWAP_10Y"
PROVIDER_NAMESPACE = "index-values-example"
PROVIDER_STORAGE_APP = "index_values_example"


class ProviderBase(DeclarativeBase):
    """The provider's own base: its migration provider targets this metadata."""

    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


class OneMinuteIndexValues(IndexValuesInstance, ProviderBase):
    """`index_values_example__index_values__t_1m`."""

    __cadence__ = "1m"
    __metatable_namespace__ = PROVIDER_NAMESPACE
    __markets_storage_app__ = PROVIDER_STORAGE_APP


class DailyIndexValues(IndexValuesInstance, ProviderBase):
    """`index_values_example__index_values__t_1d`."""

    __cadence__ = "1d"
    __metatable_namespace__ = PROVIDER_NAMESPACE
    __markets_storage_app__ = PROVIDER_STORAGE_APP


FREQUENCY_STORAGE_MODELS = (OneMinuteIndexValues, DailyIndexValues)


def reconcile_and_list_dataset_states(index_uid: str):
    """Backfill and inspect population after storage registration and persistence."""

    from examples.msm.platform.bootstrap import use_local_runtime

    use_local_runtime()
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


class Swap10YOneMinuteUpdater(IndexValuesUpdater):
    """Publish the one-minute `USD_SWAP_10Y` dataset."""

    @classmethod
    def _required_output_table(cls) -> type[PlatformTimeIndexMetaTable]:
        return OneMinuteIndexValues


class Swap10YDailyUpdater(IndexValuesUpdater):
    """Publish the daily `USD_SWAP_10Y` dataset."""

    @classmethod
    def _required_output_table(cls) -> type[PlatformTimeIndexMetaTable]:
        return DailyIndexValues


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

    one_minute_values = Swap10YOneMinuteUpdater.validate_frame(intraday_source)
    daily_values = Swap10YDailyUpdater.validate_frame(daily_source)
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
                "updater": Swap10YOneMinuteUpdater,
                "output_table": OneMinuteIndexValues,
                "values": one_minute_values,
            },
            "1d": {
                "updater": Swap10YDailyUpdater,
                "output_table": DailyIndexValues,
                "values": daily_values,
            },
        },
        "calculation_identity": calculation_identity,
    }


if __name__ == "__main__":
    output = run()
    for frequency, dataset in output["frequency_datasets"].items():
        output_table = dataset["output_table"]
        print(f"{frequency}: {output_table.__table__.name}")
        print(dataset["values"])
    print(output["calculation_identity"])
