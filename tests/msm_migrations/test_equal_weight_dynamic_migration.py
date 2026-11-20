"""The equal-weight example's dynamic migration provider, built from its source environment.

`msm_migrations` is imported when this module is collected, before the test sets the
example's namespace: the provider it defines is built once per process, and a first import
under the example namespace would migrate every later database in that process into it.
"""

from __future__ import annotations

import importlib
import sys

import msm_migrations  # noqa: F401
from examples.msm_portfolios import portfolio_equal_weights_config as config


def test_dynamic_migration_provider_imports_with_source_env(monkeypatch) -> None:
    env = config.dynamic_provider_env(
        source_time_index_meta_table_uid="source-storage-uid",
        source_cadence="1d",
    )
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    sys.modules.pop("examples.msm_portfolios.portfolio_equal_weights_dynamic_migration", None)
    module = importlib.import_module("examples.msm_portfolios.portfolio_equal_weights_dynamic_migration")

    assert module.DYNAMIC_INTERPOLATED_PRICES_STORAGE.__table__.name == (
        config.configured_equal_weight_interpolated_prices_storage(
            source_time_index_meta_table_uid="source-storage-uid",
            source_cadence="1d",
        ).__table__.name
    )
    assert module.migration.metatable_models == [module.DYNAMIC_INTERPOLATED_PRICES_STORAGE]
