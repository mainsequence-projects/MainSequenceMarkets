from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint

from migrations.registry import metatable_provider_models
from msm import INDEX_TYPE_DERIVED, INDEX_TYPE_DERIVED_DEFINITION
from msm.data_nodes.indices import IndexResolvedLegsStorage, IndexValuesStorage
from msm.models import (
    IndexCalculationDefinitionTable,
    IndexCalculationLegTable,
    IndexTable,
    IndexTypeTable,
    markets_sqlalchemy_models,
)


def _model_positions() -> dict[type, int]:
    return {model: position for position, model in enumerate(markets_sqlalchemy_models())}


def test_derived_index_type_is_a_public_builtin() -> None:
    assert INDEX_TYPE_DERIVED == "derived"
    assert INDEX_TYPE_DERIVED_DEFINITION.index_type == "derived"
    assert INDEX_TYPE_DERIVED_DEFINITION.as_payload()["display_name"] == "Derived"


def test_derived_index_models_are_registered_in_dependency_order() -> None:
    positions = _model_positions()

    assert positions[IndexTypeTable] < positions[IndexTable]
    assert positions[IndexTable] < positions[IndexCalculationDefinitionTable]
    assert positions[IndexCalculationDefinitionTable] < positions[IndexCalculationLegTable]
    assert positions[IndexCalculationDefinitionTable] < positions[IndexValuesStorage]
    assert positions[IndexCalculationDefinitionTable] < positions[IndexResolvedLegsStorage]
    assert {
        IndexCalculationDefinitionTable,
        IndexCalculationLegTable,
        IndexValuesStorage,
        IndexResolvedLegsStorage,
    }.issubset(set(metatable_provider_models()))


def test_definition_constraints_and_indexes_cover_versioned_effective_semantics() -> None:
    table = IndexCalculationDefinitionTable.__table__
    checks = {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {tuple(column.name for column in index.columns): index for index in table.indexes}

    assert "definition_version > 0" in checks
    assert "effective_to IS NULL OR effective_to > effective_from" in checks
    assert "status IN ('draft', 'active', 'retired')" in checks
    assert indexes[("index_uid", "definition_version")].unique is True
    assert indexes[("index_uid", "definition_hash")].unique is True
    assert ("status",) in indexes
    assert ("effective_from",) in indexes
    assert ("calculation_family",) in indexes
    index_fk = next(iter(table.c.index_uid.foreign_keys))
    assert index_fk.column is IndexTable.__table__.c.uid
    assert index_fk.ondelete == "CASCADE"


def test_leg_constraints_foreign_keys_and_ordering_are_relational() -> None:
    table = IndexCalculationLegTable.__table__
    checks = {
        str(constraint.sqltext)
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    indexes = {tuple(column.name for column in index.columns): index for index in table.indexes}

    assert any("asset_uid IS NOT NULL" in expression for expression in checks)
    assert any("coefficient_method = 'fixed'" in expression for expression in checks)
    assert indexes[("definition_uid", "leg_key")].unique is True
    assert indexes[("definition_uid", "leg_order")].unique is True
    assert next(iter(table.c.definition_uid.foreign_keys)).ondelete == "CASCADE"
    assert next(iter(table.c.component_index_uid.foreign_keys)).ondelete == "RESTRICT"
    assert next(iter(table.c.asset_uid.foreign_keys)).ondelete == "RESTRICT"


def test_index_storage_contracts_have_canonical_grains_and_foreign_keys() -> None:
    assert IndexValuesStorage.__index_names__ == ["time_index", "index_identifier"]
    assert IndexResolvedLegsStorage.__index_names__ == [
        "time_index",
        "index_identifier",
        "leg_key",
        "resolved_component_key",
    ]
    for storage in (IndexValuesStorage, IndexResolvedLegsStorage):
        index_fk = next(iter(storage.__table__.c.index_identifier.foreign_keys))
        definition_fk = next(iter(storage.__table__.c.definition_uid.foreign_keys))
        assert index_fk.column is IndexTable.__table__.c.unique_identifier
        assert index_fk.ondelete == "RESTRICT"
        assert definition_fk.column is IndexCalculationDefinitionTable.__table__.c.uid
        assert definition_fk.ondelete == "RESTRICT"


def test_0011_revision_contains_exact_derived_index_model_set() -> None:
    revision = Path(
        "src/migrations/versions/mainsequence_markets/0011_derived_index_framework.py"
    ).read_text(encoding="utf-8")

    assert 'revision: str = "0011"' in revision
    assert 'down_revision: Union[str, Sequence[str], None] = "0010"' in revision
    assert revision.count("op.create_table(") == 4
    for table in (
        IndexCalculationDefinitionTable,
        IndexCalculationLegTable,
        IndexValuesStorage,
        IndexResolvedLegsStorage,
    ):
        assert f'op.create_table(\n        "{table.__table__.name}"' in revision
        assert f'op.drop_table("{table.__table__.name}")' in revision
