"""The equal-weight example's dynamic migration provider, built from its source environment.

Loading the provider selects the local runtime, so the test stands in for that selection.
"""

from __future__ import annotations

import importlib
import sys

from examples.msm.platform import bootstrap as example_runtime
from examples.msm_portfolios import portfolio_equal_weights_config as config


def test_dynamic_migration_provider_imports_with_source_env(monkeypatch) -> None:
    selected: list[bool] = []
    monkeypatch.setattr(example_runtime, "use_local_runtime", lambda: selected.append(True))
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
    assert selected == [True]
