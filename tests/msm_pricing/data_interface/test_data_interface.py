from __future__ import annotations

import datetime as dt
import os
import uuid

import pandas as pd
import pytest

# Prevent SDK import-time project resolution from reading the local .env.
os.environ["MAIN_SEQUENCE_PROJECT_UID"] = " "
os.environ["MAIN_SEQUENCE_PROJECT_ID"] = " "
os.environ.setdefault("MAINSEQUENCE_ACCESS_TOKEN", "unit-test")
os.environ.setdefault("MAINSEQUENCE_REFRESH_TOKEN", "unit-test")

from msm.settings import INDEX_IDENTIFIER_DIMENSION
from msm_pricing.data_interface.data_interface import (
    MSDataInterface,
    dimension_range_for_identity,
)
from msm_pricing.data_nodes.curves import CURVE_IDENTIFIER
from msm_pricing.data_nodes.curves.key_nodes import compress_key_nodes_to_string
from msm_pricing.config import reset_pricing_market_data_configuration
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
)


@pytest.fixture(autouse=True)
def reset_pricing_market_data(monkeypatch) -> None:
    reset_pricing_market_data_configuration()
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)
    monkeypatch.delenv("USE_LAST_OBSERVATION_MS_INSTRUMENT", raising=False)
    yield
    reset_pricing_market_data_configuration()


def test_dimension_range_for_identity_builds_generic_dimension_range_map() -> None:
    start_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    assert dimension_range_for_identity(
        identity_dimension=INDEX_IDENTIFIER_DIMENSION,
        identity="SOFR",
        date_info={
            "start_date": start_date,
            "start_date_operand": ">=",
        },
    ) == [
        {
            "coordinate": {"index_identifier": "SOFR"},
            "start_date": start_date,
            "start_date_operand": ">=",
        }
    ]


def test_get_historical_fixings_reads_index_stamped_data(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    calls = []
    fixings_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000101")

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            assert table_uid == str(fixings_data_node_uid)
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(dimension_range_map)
            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 26, tzinfo=dt.UTC),
                        "index_identifier": "SOFR",
                        "rate": 0.0525,
                    }
                ]
            ).set_index(["time_index", "index_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)

    interface = MSDataInterface(
        market_data_configuration={
            "data_node_uids": {
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_data_node_uid,
            },
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
                "coordinate": {INDEX_IDENTIFIER_DIMENSION: "SOFR"},
                "start_date": dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
                "start_date_operand": ">=",
                "end_date": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                "end_date_operand": "<=",
            }
        ]
    ]


def test_get_historical_fixings_uses_persisted_pricing_market_data_binding(
    monkeypatch,
) -> None:
    MSDataInterface.clear_caches()
    calls = []
    data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000102")

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            calls.append(("table_uid", table_uid))
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(("range", dimension_range_map))
            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 26, tzinfo=dt.UTC),
                        "index_identifier": "SOFR",
                        "rate": 0.0525,
                    }
                ]
            ).set_index(["time_index", "index_identifier"])

    import mainsequence.meta_tables as meta_tables
    from msm_pricing.api.market_data_bindings import PricingMarketDataSetBinding

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    monkeypatch.setattr(
        PricingMarketDataSetBinding,
        "resolve_data_node_uid",
        staticmethod(
            lambda *, market_data_set, concept_key: (
                data_node_uid
                if concept_key == PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS
                else None
            )
        ),
    )

    interface = MSDataInterface()

    fixings = interface.get_historical_fixings(
        "SOFR",
        dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert fixings == {dt.date(2026, 5, 26): 0.0525}
    assert calls[0] == ("table_uid", str(data_node_uid))


def test_get_historical_discount_curve_reads_curve_stamped_data(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    calls = []
    curves_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000201")

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            assert table_uid == str(curves_data_node_uid)
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(dimension_range_map)
            from msm_pricing.data_nodes.curve_codec import compress_curve_to_string

            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_identifier": "mxn_tiie_discount",
                        "curve": compress_curve_to_string({28: 0.11, 91: 0.105}),
                        "key_nodes": compress_key_nodes_to_string(
                            [
                                {
                                    "maturity_date": "2026-06-24",
                                    "asset_identifier": "MXN_TIIE_SWAP_28D",
                                    "quote": 0.11,
                                }
                            ]
                        ),
                        "metadata_json": {"source_snapshot": "mock-2026-05-27"},
                    }
                ]
            ).set_index(["time_index", "curve_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)

    interface = MSDataInterface(
        market_data_configuration={
            "data_node_uids": {
                PRICING_CONCEPT_DISCOUNT_CURVES: curves_data_node_uid,
            },
        }
    )

    nodes, target_date = interface.get_historical_discount_curve(
        "mxn_tiie_discount",
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )
    cached_nodes, cached_target_date = interface.get_historical_discount_curve(
        "mxn_tiie_discount",
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert target_date == dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    assert nodes == [
        {"days_to_maturity": 28, "zero": 0.11},
        {"days_to_maturity": 91, "zero": 0.105},
    ]
    assert cached_target_date == target_date
    assert cached_nodes == nodes
    observation, observation_target_date = interface.get_historical_discount_curve_observation(
        "mxn_tiie_discount",
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set=None,
    )
    assert observation_target_date == target_date
    assert observation == {
        "curve_identifier": "mxn_tiie_discount",
        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        "nodes": nodes,
        "key_nodes": [
            {
                "maturity_date": "2026-06-24",
                "asset_identifier": "MXN_TIIE_SWAP_28D",
                "quote": 0.11,
            }
        ],
        "metadata_json": {"source_snapshot": "mock-2026-05-27"},
    }
    assert calls == [
        [
            {
                "coordinate": {CURVE_IDENTIFIER: "mxn_tiie_discount"},
                "start_date": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                "start_date_operand": ">=",
                "end_date": dt.datetime(2026, 5, 28, tzinfo=dt.UTC),
                "end_date_operand": "<",
            }
        ]
    ]
    assert interface.cache_info()["discount_curve_cache"]["size"] == 1
    assert interface.cache_info()["discount_curve_observation_cache"]["size"] == 1


def test_get_historical_discount_curve_uses_persisted_pricing_market_data_binding(
    monkeypatch,
) -> None:
    MSDataInterface.clear_caches()
    calls = []
    data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000202")

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            calls.append(("table_uid", table_uid))
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(("range", dimension_range_map))
            from msm_pricing.data_nodes.curve_codec import compress_curve_to_string

            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                        "curve_identifier": "mxn_tiie_discount",
                        "curve": compress_curve_to_string({28: 0.11}),
                    }
                ]
            ).set_index(["time_index", "curve_identifier"])

    import mainsequence.meta_tables as meta_tables
    from msm_pricing.api.market_data_bindings import PricingMarketDataSetBinding

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    monkeypatch.setattr(
        PricingMarketDataSetBinding,
        "resolve_data_node_uid",
        staticmethod(
            lambda *, market_data_set, concept_key: (
                data_node_uid if concept_key == PRICING_CONCEPT_DISCOUNT_CURVES else None
            )
        ),
    )

    interface = MSDataInterface()

    nodes, _target_date = interface.get_historical_discount_curve(
        "mxn_tiie_discount",
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert nodes == [{"days_to_maturity": 28, "zero": 0.11}]
    assert calls[0] == ("table_uid", str(data_node_uid))


def test_get_historical_discount_curve_observations_reads_many_curves_once(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    calls = []
    curves_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000205")
    target_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)
    older_date = dt.datetime(2026, 5, 26, tzinfo=dt.UTC)

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            calls.append(("table_uid", table_uid))
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(("range", dimension_range_map))
            from msm_pricing.data_nodes.curve_codec import compress_curve_to_string

            return pd.DataFrame(
                [
                    {
                        "time_index": older_date,
                        "curve_identifier": "USD-SOFR",
                        "curve": compress_curve_to_string({365: 0.045}),
                    },
                    {
                        "time_index": target_date,
                        "curve_identifier": "USD-SOFR",
                        "curve": compress_curve_to_string({365: 0.05}),
                    },
                    {
                        "time_index": target_date,
                        "curve_identifier": "MXN-TIIE",
                        "curve": compress_curve_to_string({365: 0.095}),
                    },
                ]
            ).set_index(["time_index", "curve_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    interface = MSDataInterface(
        market_data_configuration={
            "data_node_uids": {PRICING_CONCEPT_DISCOUNT_CURVES: curves_data_node_uid}
        }
    )

    observations = interface.get_historical_discount_curve_observations(
        ("USD-SOFR", "MXN-TIIE"),
        target_date,
    )

    assert observations["USD-SOFR"][0]["nodes"] == [{"days_to_maturity": 365, "zero": 0.05}]
    assert observations["USD-SOFR"][1] == target_date
    assert observations["MXN-TIIE"][0]["nodes"] == [{"days_to_maturity": 365, "zero": 0.095}]
    assert calls == [
        ("table_uid", str(curves_data_node_uid)),
        (
            "range",
            [
                {
                    "coordinate": {CURVE_IDENTIFIER: "USD-SOFR"},
                    "start_date": dt.datetime(1900, 1, 1, tzinfo=dt.UTC),
                    "start_date_operand": ">=",
                    "end_date": target_date,
                    "end_date_operand": "<=",
                },
                {
                    "coordinate": {CURVE_IDENTIFIER: "MXN-TIIE"},
                    "start_date": dt.datetime(1900, 1, 1, tzinfo=dt.UTC),
                    "start_date_operand": ">=",
                    "end_date": target_date,
                    "end_date_operand": "<=",
                },
            ],
        ),
    ]


def test_get_historical_fixings_for_identifiers_reads_many_indexes_once(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    calls = []
    fixings_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000206")
    start_date = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    end_date = dt.datetime(2026, 5, 27, tzinfo=dt.UTC)

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            calls.append(("table_uid", table_uid))
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(("range", dimension_range_map))
            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 26, tzinfo=dt.UTC),
                        "index_identifier": "USD-SOFR",
                        "rate": 0.0525,
                    },
                    {
                        "time_index": dt.datetime(2026, 5, 26, tzinfo=dt.UTC),
                        "index_identifier": "MXN-TIIE",
                        "rate": 0.1125,
                    },
                ]
            ).set_index(["time_index", "index_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    interface = MSDataInterface(
        market_data_configuration={
            "data_node_uids": {
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_data_node_uid
            }
        }
    )

    fixings = interface.get_historical_fixings_for_identifiers(
        ("USD-SOFR", "MXN-TIIE"),
        start_date,
        end_date,
    )

    assert fixings == {
        "USD-SOFR": {dt.date(2026, 5, 26): 0.0525},
        "MXN-TIIE": {dt.date(2026, 5, 26): 0.1125},
    }
    assert calls == [
        ("table_uid", str(fixings_data_node_uid)),
        (
            "range",
            [
                {
                    "coordinate": {INDEX_IDENTIFIER_DIMENSION: "USD-SOFR"},
                    "start_date": start_date,
                    "start_date_operand": ">=",
                    "end_date": end_date,
                    "end_date_operand": "<=",
                },
                {
                    "coordinate": {INDEX_IDENTIFIER_DIMENSION: "MXN-TIIE"},
                    "start_date": start_date,
                    "start_date_operand": ">=",
                    "end_date": end_date,
                    "end_date_operand": "<=",
                },
            ],
        ),
    ]


def test_get_latest_discount_curve_uses_last_update_for_curve_identity(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    calls = []
    curves_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000203")
    latest_date = dt.datetime(2026, 5, 28, tzinfo=dt.UTC)

    class FakeUpdateStatistics:
        def get_last_update_for_identity(self, identity):
            calls.append(("latest", identity))
            return latest_date

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            calls.append(("table_uid", table_uid))
            return cls()

        def get_update_statistics(self):
            calls.append(("stats",))
            return FakeUpdateStatistics()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(("range", dimension_range_map))
            from msm_pricing.data_nodes.curve_codec import compress_curve_to_string

            return pd.DataFrame(
                [
                    {
                        "time_index": latest_date,
                        "curve_identifier": "mxn_tiie_discount",
                        "curve": compress_curve_to_string({28: 0.11, 91: 0.105}),
                        "key_nodes": compress_key_nodes_to_string(
                            [{"maturity_date": "2026-06-24", "quote": 0.11}]
                        ),
                        "metadata_json": {"source_snapshot": "mock-latest"},
                    }
                ]
            ).set_index(["time_index", "curve_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)

    interface = MSDataInterface(
        market_data_configuration={
            "data_node_uids": {
                PRICING_CONCEPT_DISCOUNT_CURVES: curves_data_node_uid,
            },
        }
    )

    nodes, effective_date = interface.get_latest_discount_curve("mxn_tiie_discount")

    assert effective_date == latest_date
    assert nodes == [
        {"days_to_maturity": 28, "zero": 0.11},
        {"days_to_maturity": 91, "zero": 0.105},
    ]
    observation, observation_effective_date = interface.get_latest_discount_curve_observation(
        "mxn_tiie_discount"
    )
    assert observation_effective_date == latest_date
    assert observation["key_nodes"] == [{"maturity_date": "2026-06-24", "quote": 0.11}]
    assert observation["metadata_json"] == {"source_snapshot": "mock-latest"}
    assert calls == [
        ("table_uid", str(curves_data_node_uid)),
        ("stats",),
        ("latest", "mxn_tiie_discount"),
        (
            "range",
            [
                {
                    "coordinate": {CURVE_IDENTIFIER: "mxn_tiie_discount"},
                    "start_date": latest_date,
                    "start_date_operand": ">=",
                    "end_date": latest_date + dt.timedelta(days=1),
                    "end_date_operand": "<",
                }
            ],
        ),
        ("table_uid", str(curves_data_node_uid)),
        ("stats",),
        ("latest", "mxn_tiie_discount"),
        (
            "range",
            [
                {
                    "coordinate": {CURVE_IDENTIFIER: "mxn_tiie_discount"},
                    "start_date": latest_date,
                    "start_date_operand": ">=",
                    "end_date": latest_date + dt.timedelta(days=1),
                    "end_date_operand": "<",
                }
            ],
        ),
    ]


def test_get_latest_discount_curve_requires_latest_curve_observation(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    curves_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000204")

    class FakeUpdateStatistics:
        def get_last_update_for_identity(self, identity):
            assert identity == "missing_curve"
            return None

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            assert table_uid == str(curves_data_node_uid)
            return cls()

        def get_update_statistics(self):
            return FakeUpdateStatistics()

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)

    interface = MSDataInterface(
        market_data_configuration={
            "data_node_uids": {
                PRICING_CONCEPT_DISCOUNT_CURVES: curves_data_node_uid,
            },
        }
    )

    with pytest.raises(LookupError, match="No latest discount curve observation"):
        interface.get_latest_discount_curve("missing_curve")


def test_ms_data_interface_exposes_pricing_named_configuration_path() -> None:
    interface = MSDataInterface()
    curves_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000301")
    fixings_data_node_uid = uuid.UUID("00000000-0000-0000-0000-000000000302")

    interface.set_market_data_configuration(
        {
            "market_data_set": "eod",
            "data_node_uids": {
                PRICING_CONCEPT_DISCOUNT_CURVES: curves_data_node_uid,
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_data_node_uid,
            },
        }
    )

    configuration = interface._get_market_data_configuration()
    assert configuration.market_data_set == "eod"
    assert configuration.data_node_uids == {
        PRICING_CONCEPT_DISCOUNT_CURVES: curves_data_node_uid,
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: fixings_data_node_uid,
    }


def test_get_historical_fixings_uses_persisted_binding_before_static_default(
    monkeypatch,
) -> None:
    MSDataInterface.clear_caches()
    calls = []
    persisted_uid = uuid.UUID("00000000-0000-0000-0000-000000000401")
    direct_uid = uuid.UUID("00000000-0000-0000-0000-000000000402")

    class FakeAPIDataNode:
        @classmethod
        def build_from_table_uid(cls, table_uid):
            calls.append(("table_uid", table_uid))
            return cls()

        def get_df_between_dates(self, *, dimension_range_map):
            calls.append(("range", dimension_range_map))
            return pd.DataFrame(
                [
                    {
                        "time_index": dt.datetime(2026, 5, 26, tzinfo=dt.UTC),
                        "index_identifier": "SOFR",
                        "rate": 0.0525,
                    }
                ]
            ).set_index(["time_index", "index_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    monkeypatch.setattr(
        "msm_pricing.api.market_data_bindings.PricingMarketDataSetBinding.resolve_data_node_uid",
        lambda *, market_data_set, concept_key: (
            persisted_uid
            if (
                market_data_set == "eod"
                and concept_key == PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS
            )
            else None
        ),
    )

    interface = MSDataInterface(
        market_data_configuration={
            "market_data_set": "default",
            "data_node_uids": {
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: direct_uid,
            },
        }
    )

    interface.get_historical_fixings(
        "SOFR",
        dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
        market_data_set="eod",
    )

    assert calls[0] == ("table_uid", str(persisted_uid))
