from __future__ import annotations

import datetime as dt
import os

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
from msm_pricing.config import reset_pricing_market_data_configuration
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
)


@pytest.fixture(autouse=True)
def reset_pricing_market_data(monkeypatch) -> None:
    reset_pricing_market_data_configuration()
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)
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

    class FakeAPIDataNode:
        @classmethod
        def build_from_identifier(cls, identifier):
            assert identifier == "fixings-node"
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
            "data_node_identifiers": {
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: "fixings-node",
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

    class FakeAPIDataNode:
        @classmethod
        def build_from_identifier(cls, identifier):
            calls.append(("identifier", identifier))
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
    from msm_pricing.api.market_data_bindings import PricingMarketDataBinding

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    monkeypatch.setattr(
        PricingMarketDataBinding,
        "resolve_data_node_identifier",
        staticmethod(
            lambda *, context_key, concept_key: "registered.index_fixings"
            if concept_key == PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS
            else None
        ),
    )

    interface = MSDataInterface()

    fixings = interface.get_historical_fixings(
        "SOFR",
        dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert fixings == {dt.date(2026, 5, 26): 0.0525}
    assert calls[0] == ("identifier", "registered.index_fixings")


def test_get_historical_discount_curve_reads_curve_stamped_data(monkeypatch) -> None:
    MSDataInterface.clear_caches()
    calls = []

    class FakeAPIDataNode:
        @classmethod
        def build_from_identifier(cls, identifier):
            assert identifier == "curves-node"
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
                    }
                ]
            ).set_index(["time_index", "curve_identifier"])

    import mainsequence.meta_tables as meta_tables

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)

    interface = MSDataInterface(
        market_data_configuration={
            "data_node_identifiers": {
                PRICING_CONCEPT_DISCOUNT_CURVES: "curves-node",
            },
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
                "coordinate": {CURVE_IDENTIFIER: "mxn_tiie_discount"},
                "start_date": dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
                "start_date_operand": ">=",
                "end_date": dt.datetime(2026, 5, 28, tzinfo=dt.UTC),
                "end_date_operand": "<",
            }
        ]
    ]


def test_get_historical_discount_curve_uses_persisted_pricing_market_data_binding(
    monkeypatch,
) -> None:
    MSDataInterface.clear_caches()
    calls = []

    class FakeAPIDataNode:
        @classmethod
        def build_from_identifier(cls, identifier):
            calls.append(("identifier", identifier))
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
    from msm_pricing.api.market_data_bindings import PricingMarketDataBinding

    monkeypatch.setattr(meta_tables, "APIDataNode", FakeAPIDataNode)
    monkeypatch.setattr(
        PricingMarketDataBinding,
        "resolve_data_node_identifier",
        staticmethod(
            lambda *, context_key, concept_key: "registered.discount_curves"
            if concept_key == PRICING_CONCEPT_DISCOUNT_CURVES
            else None
        ),
    )

    interface = MSDataInterface()

    nodes, _target_date = interface.get_historical_discount_curve(
        "mxn_tiie_discount",
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert nodes == [{"days_to_maturity": 28, "zero": 0.11}]
    assert calls[0] == ("identifier", "registered.discount_curves")


def test_ms_data_interface_exposes_pricing_named_configuration_path() -> None:
    interface = MSDataInterface()

    interface.set_market_data_configuration(
        {
            "context_key": "eod",
            "data_node_identifiers": {
                PRICING_CONCEPT_DISCOUNT_CURVES: "curves-node",
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: "fixings-node",
            },
        }
    )

    configuration = interface._get_market_data_configuration()
    assert configuration.context_key == "eod"
    assert configuration.data_node_identifiers == {
        PRICING_CONCEPT_DISCOUNT_CURVES: "curves-node",
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: "fixings-node",
    }


def test_get_historical_fixings_uses_persisted_binding_before_static_default(
    monkeypatch,
) -> None:
    MSDataInterface.clear_caches()
    calls = []

    class FakeAPIDataNode:
        @classmethod
        def build_from_identifier(cls, identifier):
            calls.append(("identifier", identifier))
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
        "msm_pricing.api.market_data_bindings.PricingMarketDataBinding.resolve_data_node_identifier",
        lambda *, context_key, concept_key: (
            "persisted.fixings"
            if (context_key, concept_key) == ("eod", PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS)
            else None
        ),
    )

    interface = MSDataInterface(market_data_configuration={"context_key": "eod"})

    interface.get_historical_fixings(
        "SOFR",
        dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        dt.datetime(2026, 5, 27, tzinfo=dt.UTC),
    )

    assert calls[0] == ("identifier", "persisted.fixings")
