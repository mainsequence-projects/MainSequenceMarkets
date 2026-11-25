"""The equal-weight example declares and migrates its own tables: its interpolated prices
(#95) and its computed signal's table (2026-11-24)."""

from __future__ import annotations

import importlib

import pytest
from alembic import command
from sqlalchemy import text

from examples.msm.platform import bootstrap as example_runtime
from examples.msm_portfolios import portfolio_equal_weights_config as config
from examples.msm_portfolios import portfolio_equal_weights_example as example
from metatables import TimeIndexMetaTable, TimeIndexTableRef
from metatables.migrations import alembic_config_for_provider
from msm.base import MarketsBase
from msm_portfolios.time_index.prices.storage import (
    ExternalPricesStorage,
    interpolated_prices_instance_key,
)
from tests.support.pinned_identities import DATA_SOURCE_UID, PRICES_TABLE_UID, _bound

MIGRATIONS = "examples.msm_portfolios.portfolio_equal_weights_migrations"


@pytest.fixture
def provider(monkeypatch):
    # Loading the example's provider selects the local runtime; the test stands in for it.
    monkeypatch.setattr(example_runtime, "use_local_runtime", lambda: None)
    return importlib.import_module(MIGRATIONS).migration


def _schema(connection) -> dict[str, str | None]:
    return dict(connection.execute(text("SELECT name, sql FROM sqlite_master")).all())


def test_static_runtime_models_exclude_configured_interpolation_storage() -> None:
    assert "ExternalPricesStorage" in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS
    assert "PortfolioCalendarEventsStorage" in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS
    assert "PortfolioRebalanceStateStorage" in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS
    assert all(isinstance(model, str) for model in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS)
    assert "InterpolatedPricesStorage" not in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS


def test_the_example_declares_its_tables_on_its_own_base() -> None:
    table = config.EqualWeightInterpolatedPrices
    signals = config.EqualWeightSignalWeights
    key = interpolated_prices_instance_key(
        source_table_name=ExternalPricesStorage.__table__.name,
        source_cadence=ExternalPricesStorage.__cadence__,
        upsample_frequency_id=config.PRICE_UPSAMPLE_FREQUENCY_ID,
        intraday_bar_interpolation_rule=config.PRICE_INTERPOLATION_RULE,
    )

    assert list(config.ProviderBase.metadata.tables) == [
        table.__table__.name,
        signals.__table__.name,
    ]
    assert not issubclass(table, MarketsBase) and not issubclass(signals, MarketsBase)
    assert signals.__table__.name == f"{config.PROVIDER_STORAGE_APP}__signalweightsts__signals"
    assert signals.__metatable_identifier__ == (
        f"{config.PROVIDER_NAMESPACE}.SignalWeightsTS.signals"
    )
    assert table.__metatable_identifier__ == (
        f"{config.PROVIDER_NAMESPACE}.InterpolatedPricesTS.{key}"
    )
    assert table.__table__.name.startswith(
        f"{config.PROVIDER_STORAGE_APP}__interpolatedpricests__"
    )
    assert table.__cadence__ == config.PRICE_UPSAMPLE_FREQUENCY_ID


def test_the_examples_tables_import_back_by_their_address() -> None:
    """What a node Job run imports (MetaTables ADR 0032): ``module:qualname``."""

    for table in (config.EqualWeightInterpolatedPrices, config.EqualWeightSignalWeights):
        module = importlib.import_module(table.__module__)

        assert table.__module__ == "examples.msm_portfolios.portfolio_equal_weights_config"
        assert getattr(module, table.__qualname__) is table


def test_the_provider_registers_and_targets_only_the_examples_tables(provider) -> None:
    # Alembic alone would create the tables; MetaTables registers what this list holds.
    assert list(provider.metatable_models) == [
        config.EqualWeightInterpolatedPrices,
        config.EqualWeightSignalWeights,
    ]
    assert provider.target_metadata is config.ProviderBase.metadata


def test_the_committed_revisions_create_the_tables_in_each_catalog(
    provider, tmp_path, sqlite_revisions
) -> None:
    tables_created = {
        config.EqualWeightInterpolatedPrices.__table__.name,
        config.EqualWeightSignalWeights.__table__.name,
    }
    for environment in ("development", "production"):
        engine = sqlite_revisions.engine(tmp_path / f"{environment}.sqlite", "head")
        with engine.connect() as connection:
            before = _schema(connection)
            settings = alembic_config_for_provider(provider, sqlalchemy_url=str(engine.url))
            settings.attributes["connection"] = connection

            command.upgrade(settings, "head")
            connection.commit()
            # A second autogenerate of the example's provider is empty.
            command.check(settings)

            after = _schema(connection)
            tables = set(
                connection.execute(
                    text("SELECT name FROM sqlite_master WHERE type = 'table'")
                ).scalars()
            )
        engine.dispose()

        assert {name: after.get(name) for name in before} == before
        assert tables - set(before) == {*tables_created, provider.version_table}


def test_the_example_binds_interpolation_to_that_table() -> None:
    source = TimeIndexTableRef(
        output_table=TimeIndexMetaTable.model_construct(
            uid="d0000000-0000-4000-8000-000000000002",
            data_source_uid=DATA_SOURCE_UID,
            physical_table_name=ExternalPricesStorage.__table__.name,
            time_indexed_profile=None,
            cadence=ExternalPricesStorage.__cadence__,
        )
    )
    with _bound(
        config.EqualWeightInterpolatedPrices,
        PRICES_TABLE_UID,
        cadence=config.EqualWeightInterpolatedPrices.__cadence__,
    ):
        prices = example.build_interpolated_prices_node(source)

    assert prices.output_table is config.EqualWeightInterpolatedPrices


def test_the_example_binds_its_signal_to_its_signal_table() -> None:
    with _bound(config.EqualWeightSignalWeights, "d0000000-0000-4000-8000-000000000003"):
        signal = example.build_signal_weights_node()

    assert signal.output_table is config.EqualWeightSignalWeights


def test_the_example_names_its_migration_when_a_table_is_missing(monkeypatch) -> None:
    monkeypatch.setattr(TimeIndexMetaTable, "filter_by_body", classmethod(lambda cls, **_: []))

    with pytest.raises(RuntimeError, match=f"migrations upgrade --provider {MIGRATIONS}:migration"):
        example.assert_interpolated_prices_storage_registered()
    with pytest.raises(RuntimeError, match="signal table is missing"):
        example.assert_signal_weights_storage_registered()


def test_example_daily_bars_declares_no_dependencies() -> None:
    node = object.__new__(example.ExampleDailyBars)

    assert node.dependencies() == {}
