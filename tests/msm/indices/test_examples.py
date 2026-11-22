from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(_PROJECT_ROOT)]

from examples.msm.indices import (  # noqa: E402
    delta_hedged_option_index,
    extension_owned_index_storage,
    formula_index,
    plain_index_values,
)
from examples.msm.platform import bootstrap as example_runtime  # noqa: E402


def test_formula_example_mixes_index_and_asset_sources() -> None:
    output = formula_index.run()

    assert output["formula"].formula == formula_index.FORMULA
    assert {item.source_reference.type for item in output["formula"].inputs} == {
        "asset",
        "index",
    }
    assert output["values"]["value"].tolist() == pytest.approx([0.617, 0.621])
    assert output["values"].columns.tolist() == ["value", "source_as_of"]


def test_delta_hedged_performance_is_custom_after_portfolio_calculation() -> None:
    output = delta_hedged_option_index.run()

    assert output["calculation_method"] == "custom"
    assert output["index_values"]["value"].tolist() == pytest.approx([100.0, 100.7, 100.2])
    assert output["index_values"]["definition_uid"].isna().all()


def test_plain_index_values_share_identity_across_frequencies() -> None:
    output = plain_index_values.run()
    one_minute = output["frequency_datasets"]["1m"]
    daily = output["frequency_datasets"]["1d"]

    assert output["index_identifier"] == "USD_SWAP_10Y"
    assert one_minute["output_table"].__cadence__ == "1m"
    assert daily["output_table"].__cadence__ == "1d"
    assert "unit" not in one_minute["values"].columns
    assert output["calculation_identity"]["coexisting_methods"] == (
        "USD_SWAP_10Y_METHOD_A",
        "USD_SWAP_10Y_METHOD_B",
    )


def test_frequency_example_migrates_its_tables_with_its_own_provider(monkeypatch) -> None:
    # Loading the provider selects the local runtime.
    monkeypatch.setattr(example_runtime, "use_local_runtime", lambda: None)
    provider = importlib.import_module("examples.msm.indices.index_values_frequency_migration")
    models = plain_index_values.FREQUENCY_STORAGE_MODELS
    migration = provider.migration

    assert list(migration.metatable_models) == list(models)
    assert [model.__cadence__ for model in models] == ["1m", "1d"]
    assert migration.target_metadata is plain_index_values.ProviderBase.metadata
    assert set(migration.target_metadata.tables) == {model.__table__.key for model in models}
    assert migration.package != "msm"
    assert not migration.script_location.startswith("msm_migrations")
    assert not migration.version_table.startswith("ms_markets__")


def test_extension_metadata_holds_only_the_extensions_table() -> None:
    storage = extension_owned_index_storage.ExtensionIndexObservationsStorage

    assert set(extension_owned_index_storage.ExtensionBase.metadata.tables) == {
        storage.__table__.key
    }
    (key,) = storage.__table__.foreign_keys
    assert key.target_fullname == "ms_markets__index.unique_identifier"


def test_extension_can_publish_a_unit_free_canonical_projection() -> None:
    output = extension_owned_index_storage.run()
    canonical = output["canonical_values"].reset_index()

    assert canonical.loc[0, "value"] == pytest.approx(0.04192)
    assert "unit" not in canonical.columns
