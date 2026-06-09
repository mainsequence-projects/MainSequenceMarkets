from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest
from mainsequence.meta_tables.migrations import metadata_for_models

from examples.msm_portfolios import portfolio_equal_weights_config as config
from examples.msm_portfolios import portfolio_equal_weights_example as example
from examples.msm_portfolios import portfolio_equal_weights_prepare_schema as prep


def _configured_dynamic_table_name() -> str:
    return config.configured_equal_weight_interpolated_prices_storage(
        source_time_index_meta_table_uid="source-storage-uid",
        source_cadence="1d",
    ).__table__.name


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
        uid="source-storage-uid",
        time_indexed_profile=SimpleNamespace(cadence="5m"),
    )

    storage = example.build_example_interpolated_prices_storage(source_meta_table)
    expected = config.configured_equal_weight_interpolated_prices_storage(
        source_time_index_meta_table_uid="source-storage-uid",
        source_cadence="5m",
    )

    assert storage is expected
    assert storage.__table__.name == expected.__table__.name
    assert storage.__metatable_extra_hash_components__[
        "source_time_index_meta_table_uid"
    ] == (
        "source-storage-uid"
    )
    assert storage.__metatable_extra_hash_components__["source_cadence"] == "5m"


def test_source_cadence_reads_top_level_registered_metadata() -> None:
    source_meta_table = SimpleNamespace(
        time_indexed_profile=None,
        cadence="1D",
    )

    assert config.source_cadence_from_meta_table(source_meta_table) == "1d"


def test_source_cadence_does_not_fallback_to_model_constant() -> None:
    source_meta_table = SimpleNamespace(
        uid="source-uid",
        physical_table_name="ms_markets__externalpricests__mainsequence_examples",
        time_indexed_profile=None,
        cadence=None,
    )

    with pytest.raises(RuntimeError, match="missing backend cadence metadata"):
        config.source_cadence_from_meta_table(source_meta_table)


def test_repair_source_cadence_metadata_patches_stale_table() -> None:
    class StaleSource:
        uid = "source-uid"
        physical_table_name = "ms_markets__externalpricests__mainsequence_examples"
        time_indexed_profile = None
        cadence = None

        def patch(self, **kwargs):
            assert kwargs == {"cadence": "1d"}
            return SimpleNamespace(
                uid=self.uid,
                physical_table_name=self.physical_table_name,
                time_indexed_profile=None,
                cadence="1d",
            )

    repaired, cadence, changed = config.repair_source_cadence_metadata(
        StaleSource(),
        expected_cadence="1d",
    )

    assert cadence == "1d"
    assert changed is True
    assert repaired.cadence == "1d"


def test_example_daily_bars_declares_no_dependencies() -> None:
    node = object.__new__(example.ExampleDailyBars)

    assert node.dependencies() == {}


def test_dynamic_provider_storage_requires_explicit_source_env(monkeypatch) -> None:
    monkeypatch.delenv(
        config.DYNAMIC_SOURCE_TIME_INDEX_META_TABLE_UID_ENV,
        raising=False,
    )
    monkeypatch.delenv(config.DYNAMIC_SOURCE_CADENCE_ENV, raising=False)

    with pytest.raises(RuntimeError, match="requires"):
        config.dynamic_storage_from_env()

    env = config.dynamic_provider_env(
        source_time_index_meta_table_uid="source-storage-uid",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    storage = config.dynamic_storage_from_env()

    assert storage.__table__.name == (
        config.configured_equal_weight_interpolated_prices_storage(
            source_time_index_meta_table_uid="source-storage-uid",
            source_cadence="1d",
        ).__table__.name
    )


def test_dynamic_migration_metadata_contains_only_configured_table(monkeypatch) -> None:
    env = config.dynamic_provider_env(
        source_time_index_meta_table_uid="source-storage-uid",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    storage = config.dynamic_storage_from_env()
    metadata = metadata_for_models([storage])

    assert list(metadata.tables) == [storage.__table__.name]


def test_dynamic_migration_provider_imports_with_source_env(monkeypatch) -> None:
    env = config.dynamic_provider_env(
        source_time_index_meta_table_uid="source-storage-uid",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    module_name = "examples.msm_portfolios.portfolio_equal_weights_dynamic_migration"
    sys.modules.pop(module_name, None)
    module = importlib.import_module(module_name)

    assert module.DYNAMIC_INTERPOLATED_PRICES_STORAGE.__table__.name == (
        config.configured_equal_weight_interpolated_prices_storage(
            source_time_index_meta_table_uid="source-storage-uid",
            source_cadence="1d",
        ).__table__.name
    )
    assert module.migration.metatable_models == [module.DYNAMIC_INTERPOLATED_PRICES_STORAGE]


def test_dynamic_revision_message_uses_configured_table_suffix() -> None:
    table_name = _configured_dynamic_table_name()
    table_suffix = table_name.rsplit("_", 1)[-1]

    assert prep._dynamic_revision_message(table_name, revision_message=None) == (
        f"portfolio_equal_weights_dynamic_interpolated_prices_{table_suffix}"
    )
    assert (
        prep._dynamic_revision_message(
            table_name,
            revision_message="custom revision",
        )
        == "custom revision"
    )


def test_find_dynamic_revision_file_detects_existing_create_table(
    monkeypatch,
    tmp_path,
) -> None:
    revisions_root = tmp_path / "versions" / "mainsequence_examples"
    revisions_root.mkdir(parents=True)
    table_name = _configured_dynamic_table_name()
    revision_file = revisions_root / "0009_dynamic.py"
    revision_file.write_text(
        f"from alembic import op\ndef upgrade():\n    op.create_table('{table_name}')\n",
        encoding="utf-8",
    )
    (revisions_root / "0010_other.py").write_text(
        "from alembic import op\ndef upgrade():\n    op.create_table('other_table')\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(prep, "_active_version_directory", lambda: revisions_root)

    assert prep._find_dynamic_revision_file(table_name) == revision_file
    assert prep._find_dynamic_revision_file("missing_table") is None


def test_prepare_schema_runs_upgrade_when_metadata_already_exists(
    monkeypatch,
    tmp_path,
) -> None:
    source_meta_table = SimpleNamespace(
        uid="source-storage-uid",
        time_indexed_profile=SimpleNamespace(cadence="1d"),
    )
    existing_dynamic_table = SimpleNamespace(uid="dynamic-storage-uid")
    runtime = SimpleNamespace(table=lambda _model: SimpleNamespace(meta_table=source_meta_table))
    table_name = _configured_dynamic_table_name()
    revision_file = tmp_path / "0009_dynamic.py"
    commands = []

    monkeypatch.setattr(
        prep,
        "start_portfolio_example_runtime",
        lambda models: runtime,
    )
    monkeypatch.setattr(
        prep,
        "_find_dynamic_revision_file",
        lambda requested_table_name: revision_file if requested_table_name == table_name else None,
    )
    monkeypatch.setattr(
        prep,
        "_find_time_index_meta_table",
        lambda requested_table_name: (
            existing_dynamic_table if requested_table_name == table_name else None
        ),
    )
    monkeypatch.setattr(
        prep,
        "_run_mainsequence",
        lambda args, *, env, allow_failure=False: commands.append((args, env)),
    )

    result = prep.prepare_equal_weight_portfolio_schema()

    assert result["configured_storage_table"] == table_name
    assert result["configured_storage_uid"] == existing_dynamic_table.uid
    assert len(commands) == 1
    assert commands[0][0] == [
        "migrations",
        "upgrade",
        "--provider",
        config.DYNAMIC_MIGRATION_PROVIDER,
        "head",
    ]
