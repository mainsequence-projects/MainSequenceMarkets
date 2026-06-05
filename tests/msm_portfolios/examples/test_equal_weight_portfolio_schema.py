from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from examples.msm_portfolios import portfolio_equal_weights_config as config
from examples.msm_portfolios import portfolio_equal_weights_example as example
from examples.msm_portfolios import portfolio_equal_weights_prepare_schema as prep


def test_static_runtime_models_exclude_configured_interpolation_storage() -> None:
    assert "ExternalPricesStorage" in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS
    assert all(isinstance(model, str) for model in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS)
    assert "InterpolatedPricesStorage" not in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS
    assert not any(
        getattr(model, "__name__", "").startswith("InterpolatedPricesStorage_")
        for model in config.PORTFOLIO_EXAMPLE_RUNTIME_MODELS
    )


def test_runtime_derives_configured_storage_from_registered_source_metadata() -> None:
    source_meta_table = SimpleNamespace(
        storage_hash="registered-external-prices-hash",
        time_indexed_profile=SimpleNamespace(cadence="5m"),
    )

    storage = example.build_example_interpolated_prices_storage(source_meta_table)
    expected = config.configured_equal_weight_interpolated_prices_storage(
        source_storage_hash="registered-external-prices-hash",
        source_cadence="5m",
    )

    assert storage is expected
    assert storage.__table__.name == expected.__table__.name
    assert storage.__metatable_extra_hash_components__["source_storage_hash"] == (
        "registered-external-prices-hash"
    )
    assert storage.__metatable_extra_hash_components__["source_cadence"] == "5m"


def test_example_daily_bars_declares_no_dependencies() -> None:
    node = example.ExampleDailyBars(
        asset_identifiers=config.ASSET_UNIQUE_IDENTIFIERS,
        namespace=config.NAMESPACE,
    )

    assert node.dependencies() == {}


def test_dynamic_provider_storage_requires_explicit_source_env(monkeypatch) -> None:
    monkeypatch.delenv(config.DYNAMIC_SOURCE_STORAGE_HASH_ENV, raising=False)
    monkeypatch.delenv(config.DYNAMIC_SOURCE_CADENCE_ENV, raising=False)

    with pytest.raises(RuntimeError, match="requires"):
        config.dynamic_storage_from_env()

    env = config.dynamic_provider_env(
        source_storage_hash="registered-external-prices-hash",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    storage = config.dynamic_storage_from_env()

    assert storage.__table__.name == (
        config.configured_equal_weight_interpolated_prices_storage(
            source_storage_hash="registered-external-prices-hash",
            source_cadence="1d",
        ).__table__.name
    )


def test_dynamic_migration_metadata_contains_only_configured_table(monkeypatch) -> None:
    env = config.dynamic_provider_env(
        source_storage_hash="registered-external-prices-hash",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    storage = config.dynamic_storage_from_env()
    metadata = config.metadata_for_storage_model(storage)

    assert list(metadata.tables) == [storage.__table__.name]


def test_dynamic_migration_provider_imports_with_source_env(monkeypatch) -> None:
    env = config.dynamic_provider_env(
        source_storage_hash="registered-external-prices-hash",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    module_name = "examples.msm_portfolios.portfolio_equal_weights_dynamic_migration"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)

    assert module.DYNAMIC_INTERPOLATED_PRICES_STORAGE.__table__.name == (
        config.configured_equal_weight_interpolated_prices_storage(
            source_storage_hash="registered-external-prices-hash",
            source_cadence="1d",
        ).__table__.name
    )
    assert module.migration.metatable_models == [
        module.DYNAMIC_INTERPOLATED_PRICES_STORAGE
    ]


def test_dynamic_revision_message_uses_configured_table_suffix() -> None:
    table_name = "mt_mainsequence_examples_2418c22d8df4a6ff3c7cf0778f11ed49"

    assert prep._dynamic_revision_message(table_name, revision_message=None) == (
        "portfolio_equal_weights_dynamic_interpolated_prices_"
        "2418c22d8df4a6ff3c7cf0778f11ed49"
    )
    assert prep._dynamic_revision_message(
        table_name,
        revision_message="custom revision",
    ) == "custom revision"


def test_find_dynamic_revision_file_detects_existing_create_table(
    monkeypatch,
    tmp_path,
) -> None:
    revisions_root = tmp_path / "src" / "migrations" / "versions" / "mainsequence_examples"
    revisions_root.mkdir(parents=True)
    table_name = "mt_mainsequence_examples_2418c22d8df4a6ff3c7cf0778f11ed49"
    revision_file = revisions_root / "0009_dynamic.py"
    revision_file.write_text(
        "from alembic import op\n"
        "def upgrade():\n"
        f"    op.create_table('{table_name}')\n",
        encoding="utf-8",
    )
    (revisions_root / "0010_other.py").write_text(
        "from alembic import op\n"
        "def upgrade():\n"
        "    op.create_table('other_table')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prep, "_PROJECT_ROOT", tmp_path)

    assert prep._find_dynamic_revision_file(table_name) == revision_file
    assert prep._find_dynamic_revision_file("missing_table") is None
