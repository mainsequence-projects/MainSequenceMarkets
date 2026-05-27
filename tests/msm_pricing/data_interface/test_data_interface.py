from __future__ import annotations

import datetime as dt
import os

import pandas as pd

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.settings import INDEX_UNIQUE_IDENTIFIER_DIMENSION
from msm_pricing.data_interface.data_interface import (
    MSInterface,
    dimension_range_for_identity,
)
from msm_pricing.data_nodes.curves import CURVE_UNIQUE_IDENTIFIER_DIMENSION


def test_dimension_range_for_identity_builds_generic_dimension_range_map() -> None:
    start_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    assert dimension_range_for_identity(
        identity_dimension=INDEX_UNIQUE_IDENTIFIER_DIMENSION,
        identity="SOFR",
        date_info={
            "start_date": start_date,
            "start_date_operand": ">=",
        },
    ) == [
        {
            "coordinate": {"unique_identifier": "SOFR"},
            "start_date": start_date,
            "start_date_operand": ">=",
        }
    ]


def test_get_historical_fixings_reads_index_stamped_data(monkeypatch) -> None:
    MSInterface.clear_caches()
    calls = []

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_id(cls, table_id):
            assert table_id == "fixings-node"
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(dimension_range_map)
            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 26, tzinfo=dt.UTC),
                        "unique_identifier": "SOFR",
                        "rate": 0.0525,
                    }
                ]
            ).set_index(["time_index", "unique_identifier"])

    import mainsequence.tdag as tdag

    monkeypatch.setattr(tdag, "APIDataNode", FakeAPIDataNode)

    interface = MSInterface(
        instruments_configuration={
            "reference_rates_fixings_data_node_uid": "fixings-node",
        }
    )

    fixings = interface.get_historical_fixings(
        "SOFR",
        dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert fixings == {dt.date(2026, 5, 26): 0.0525}
    assert calls == [
        [
            {
                "coordinate": {INDEX_UNIQUE_IDENTIFIER_DIMENSION: "SOFR"},
                "start_date": dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
                "start_date_operand": ">=",
                "end_date": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                "end_date_operand": "<=",
            }
        ]
    ]


def test_get_historical_discount_curve_reads_curve_stamped_data(monkeypatch) -> None:
    MSInterface.clear_caches()
    calls = []

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_id(cls, table_id):
            assert table_id == "curves-node"
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(dimension_range_map)
            from msm_pricing.data_nodes.curve_codec import compress_curve_to_string

            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_unique_identifier": "mxn_tiie_discount",
                        "curve": compress_curve_to_string({28: 0.11, 91: 0.105}),
                    }
                ]
            ).set_index(["time_index", "curve_unique_identifier"])

    import mainsequence.tdag as tdag

    monkeypatch.setattr(tdag, "APIDataNode", FakeAPIDataNode)

    interface = MSInterface(
        instruments_configuration={
            "discount_curves_data_node_uid": "curves-node",
        }
    )

    nodes, target_date = interface.get_historical_discount_curve(
        "mxn_tiie_discount",
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert target_date == dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    assert nodes == [
        {"days_to_maturity": 28, "zero": 0.11},
        {"days_to_maturity": 91, "zero": 0.105},
    ]
    assert calls == [
        [
            {
                "coordinate": {CURVE_UNIQUE_IDENTIFIER_DIMENSION: "mxn_tiie_discount"},
                "start_date": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                "start_date_operand": ">=",
                "end_date": dt.datetime(2026, 5, 28, tzinfo=dt.UTC),
                "end_date_operand": "<",
            }
        ]
    ]
