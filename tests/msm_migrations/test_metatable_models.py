"""The migration provider's models: every package's MetaTables, as the registry collects them.

Split from ``tests/msm/models/test_metatable_models.py``.
"""

from __future__ import annotations

from metatables import PlatformManagedMetaTable, PlatformTimeIndexMetaTable
from msm.time_index.accounts.storage import AccountHoldingsStorage
from msm_migrations.registry import metatable_provider_models
from msm.models import markets_sqlalchemy_models
from msm_portfolios.time_index.portfolios.storage import PortfolioEventLedgerStorage
from msm_pricing.meta_tables import pricing_sqlalchemy_models


def test_time_index_provider_models_have_valid_storage_layouts() -> None:
    # Run the API's own layout check: without __storage_layout__, MetaTables
    # derives the lookup index name from the identity dimensions and rejects
    # it when it exceeds PostgreSQL's 63-character limit.
    from metatables.api.backend.contracts.storage_layouts import parse_storage_layout

    time_index_models = [
        model
        for model in metatable_provider_models()
        if issubclass(model, PlatformTimeIndexMetaTable)
    ]
    assert PortfolioEventLedgerStorage in time_index_models

    for model in time_index_models:
        layout = parse_storage_layout(
            getattr(model, "__storage_layout__", None),
            time_index_name=model.__time_index_name__,
            index_names=model.__index_names__,
            columns_by_name={column.name: column for column in model.__table__.columns},
        )
        for secondary_index in layout.secondary_indexes:
            # The physical index is "<name>_idx" and must not be truncated.
            assert len(f"{secondary_index.name}_idx") <= 63, model.__name__


def test_built_in_metatables_declare_column_descriptions() -> None:
    seen: set[type] = set()
    models = []
    for model in [
        *markets_sqlalchemy_models(),
        *pricing_sqlalchemy_models(),
    ]:
        if model in seen:
            continue
        seen.add(model)
        models.append(model)

    for model in models:
        for column in model.__table__.columns:
            description = column.info.get("description")

            assert isinstance(description, str), f"{model.__name__}.{column.name}"
            assert description.strip() == description, f"{model.__name__}.{column.name}"
            assert len(description.split()) >= 5, f"{model.__name__}.{column.name}"


def test_migration_registry_models_use_sdk_base_metatable_classes() -> None:
    registry = metatable_provider_models()
    assert registry
    assert AccountHoldingsStorage in registry
    assert all(issubclass(model, PlatformManagedMetaTable) for model in registry)
    assert issubclass(AccountHoldingsStorage, PlatformTimeIndexMetaTable)
