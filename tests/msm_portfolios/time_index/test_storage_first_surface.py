from __future__ import annotations

import pandas as pd
import pytest

from metatables import TimeIndexMetaTable, TimeIndexTableRef
from msm.time_index.utils.storage_schema import storage_column_dtypes_map
from msm.models.assets.core import AssetTable
from msm.models.portfolios import PortfolioTable
from msm.settings import ASSET_IDENTIFIER_DIMENSION
from msm_portfolios.asset_scope import ASSET_IDENTIFIER
from msm_portfolios.contrib.prices.updaters import (
    InterpolatedPrices,
    _asset_schedule_map,
    _normalize_time_indexed_frame_ns_utc,
    _source_time_indexed_profile_cadence,
)
from msm_portfolios.time_index.portfolios.calendar_events import PortfolioCalendarEvents
from msm_portfolios.time_index.portfolios.rebalance import PortfolioRebalance
from msm_portfolios.time_index.portfolios.weights import PortfolioWeights
from msm_portfolios.time_index.portfolios import PortfolioValues
from msm_portfolios.time_index.portfolios.storage import (
    PortfolioCalendarEventsStorage,
    PortfolioRebalanceStateStorage,
    PortfolioWeightsStorage,
    PortfoliosStorage,
)
from msm_portfolios.time_index.prices.storage import (
    ExternalPricesStorage,
    InterpolatedPricesStorage,
)
from msm_portfolios.time_index.signals import SignalWeights
from msm_portfolios.time_index.signals.storage import (
    SignalWeightsStorage,
)
from msm_portfolios.models import portfolio_sqlalchemy_models


def test_portfolio_asset_scope_uses_markets_asset_dimension() -> None:
    assert ASSET_IDENTIFIER == ASSET_IDENTIFIER_DIMENSION


def test_portfolio_nodes_expose_storage_first_surface(monkeypatch) -> None:
    registered = set(portfolio_sqlalchemy_models())

    for node_cls in (PortfolioCalendarEvents, PortfolioRebalance):
        assert "__data_node_identifier__" not in node_cls.__dict__
        assert "_default_identifier" not in node_cls.__dict__
        assert "_default_description" not in node_cls.__dict__
        output_table = node_cls._required_output_table()
        registered_identifier = f"registered.{output_table.metatable_identifier()}"
        monkeypatch.setattr(
            output_table,
            "get_identifier",
            classmethod(lambda _cls, identifier=registered_identifier: identifier),
        )
        assert node_cls._default_identifier() == registered_identifier
        assert node_cls._default_description() == output_table.__metatable_description__
        assert output_table in registered
        assert not hasattr(node_cls, "_required_column_dtypes_map")
        assert not hasattr(node_cls, "_required_index_names")
        assert not hasattr(node_cls, "_required_time_index_name")
        assert node_cls._column_dtypes_map_for_storage(output_table) == storage_column_dtypes_map(
            output_table
        )
        assert not hasattr(node_cls, "build_mock_frame")
        assert not hasattr(node_cls, "build_schema_bootstrap_frame")
        assert not hasattr(node_cls, "build_initialization_frame")


def test_published_nodes_validate_against_their_markets_storage() -> None:
    """ADR 0060: the nodes of the three series publish; their storage is Markets' own."""

    registered = set(portfolio_sqlalchemy_models())
    for node_cls in (PortfolioWeights, PortfolioValues, SignalWeights):
        output_table = node_cls._required_output_table()
        assert output_table in registered
        assert node_cls._column_dtypes_map_for_storage() == storage_column_dtypes_map(output_table)
        assert not hasattr(node_cls, "_default_identifier")
        assert not hasattr(node_cls, "output_table")


def test_portfolio_storage_identifiers_use_camel_case_ts_suffix() -> None:
    assert PortfolioRebalanceStateStorage.metatable_identifier().endswith(
        "PortfolioRebalanceStateTS"
    )
    assert PortfolioCalendarEventsStorage.metatable_identifier().endswith(
        "PortfolioCalendarEventsTS"
    )
    assert PortfolioWeightsStorage.metatable_identifier().endswith("PortfolioWeightsTS")
    assert SignalWeightsStorage.metatable_identifier().endswith("SignalWeightsTS")
    assert PortfoliosStorage.metatable_identifier().endswith("PortfoliosTS")
    assert ExternalPricesStorage.metatable_identifier().endswith("ExternalPricesTS")
    assert InterpolatedPricesStorage.metatable_identifier().endswith("InterpolatedPricesTS")


def test_external_price_storage_is_registered_by_portfolio_provider() -> None:
    assert ExternalPricesStorage in set(portfolio_sqlalchemy_models())
    assert ExternalPricesStorage.__cadence__ == "1d"


def test_portfolio_price_storage_has_asset_identifier_foreign_key() -> None:
    expected_target = f"{AssetTable.__table__.fullname}.unique_identifier"

    for output_table in (ExternalPricesStorage, InterpolatedPricesStorage):
        foreign_keys = output_table.__table__.c.asset_identifier.foreign_keys
        assert len(foreign_keys) == 1
        assert next(iter(foreign_keys)).target_fullname == expected_target


def test_portfolio_values_storage_has_portfolio_identifier_foreign_key() -> None:
    foreign_keys = PortfoliosStorage.__table__.c.portfolio_identifier.foreign_keys

    assert len(foreign_keys) == 1
    foreign_key = next(iter(foreign_keys))
    assert foreign_key.column is PortfolioTable.__table__.c.unique_identifier
    assert foreign_key.ondelete == "RESTRICT"


def test_interpolated_prices_accepts_registered_top_level_source_cadence() -> None:
    source_price = TimeIndexTableRef(
        output_table=TimeIndexMetaTable.model_construct(
            uid="source-uid",
            data_source_uid="source-data-source",
            time_indexed_profile=None,
            cadence="1D",
        )
    )

    assert (
        _source_time_indexed_profile_cadence(
            source_price,
            source_time_index_meta_table_uid="source-uid",
        )
        == "1d"
    )


def test_interpolated_prices_mapping_scope_uses_canonical_asset_identifier(monkeypatch) -> None:
    asset_scope = [
        "example-asset-btc",
        {"asset_identifier": "example-asset-eth"},
        {"metadata": {"asset_identifier": "example-asset-sol"}},
    ]
    resolved: list[list[str]] = []

    def fake_resolve(identifiers):
        resolved.append(list(identifiers))
        return {identifier: "schedule" for identifier in resolved[-1]}

    monkeypatch.setattr(
        "msm_portfolios.contrib.prices.updaters.resolve_asset_schedules", fake_resolve
    )

    assert InterpolatedPrices.asset_unique_identifiers(asset_scope) == [
        "example-asset-btc",
        "example-asset-eth",
        "example-asset-sol",
    ]
    # The calendar of each asset comes from its stored link, by identifier (ADR 0056).
    assert _asset_schedule_map(asset_scope) == {
        "example-asset-btc": "schedule",
        "example-asset-eth": "schedule",
        "example-asset-sol": "schedule",
    }
    assert resolved == [["example-asset-btc", "example-asset-eth", "example-asset-sol"]]


@pytest.mark.parametrize(
    "asset_scope",
    [
        [{"asset_identifier": "example-asset-eth", "calendar": "NYSE"}],
        [{"asset_identifier": "example-asset-eth", "metadata": {"calendar": "NYSE"}}],
    ],
)
def test_interpolated_prices_scope_refuses_a_calendar_key(monkeypatch, asset_scope) -> None:
    monkeypatch.setattr(
        "msm_portfolios.contrib.prices.updaters.resolve_asset_schedules",
        lambda _identifiers: pytest.fail("a scope with a calendar key is refused before any read"),
    )

    with pytest.raises(TypeError, match="must not contain 'calendar'"):
        _asset_schedule_map(asset_scope)


@pytest.mark.parametrize(
    "asset_scope",
    [
        [{"unique_identifier": "example-asset-invalid"}],
        [
            {
                "asset_identifier": "example-asset-invalid",
                "unique_identifier": "legacy-example-asset-invalid",
            }
        ],
    ],
)
def test_interpolated_prices_mapping_scope_rejects_unique_identifier_key(
    asset_scope: list[dict[str, str]],
) -> None:

    with pytest.raises(TypeError, match="must not contain 'unique_identifier'"):
        InterpolatedPrices.asset_unique_identifiers(asset_scope)
    with pytest.raises(TypeError, match="must not contain 'unique_identifier'"):
        _asset_schedule_map(asset_scope)


def test_interpolated_prices_normalizes_time_index_output_to_ns_utc() -> None:
    time_values = pd.to_datetime(
        [
            "2026-05-23T00:00:00Z",
            "2026-05-24T00:00:00Z",
        ],
        utc=True,
    ).astype("datetime64[us, UTC]")
    frame = pd.DataFrame(
        {
            "time_index": time_values,
            ASSET_IDENTIFIER_DIMENSION: ["example-asset-btc", "example-asset-eth"],
            "open_time": time_values,
            "close": [100.0, 200.0],
        }
    ).set_index(["time_index", ASSET_IDENTIFIER_DIMENSION])

    normalized = _normalize_time_indexed_frame_ns_utc(frame)

    assert str(normalized.index.get_level_values("time_index").dtype) == "datetime64[ns, UTC]"
    assert str(normalized["open_time"].dtype) == "datetime64[ns, UTC]"
