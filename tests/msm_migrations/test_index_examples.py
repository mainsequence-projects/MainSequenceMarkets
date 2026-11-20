"""The index-values frequency example builds its storage models before its migration provider.

Split from ``tests/msm/indices/test_examples.py``: this example builds a migration provider
on ``msm_migrations``.
"""

from __future__ import annotations

from examples.msm.indices import index_values_frequency_migration


def test_frequency_storage_models_are_built_before_migration_provider() -> None:
    models = index_values_frequency_migration.FREQUENCY_STORAGE_MODELS

    assert list(index_values_frequency_migration.migration.metatable_models) == list(models)
    assert [model.__cadence__ for model in models] == ["1m", "1d"]
