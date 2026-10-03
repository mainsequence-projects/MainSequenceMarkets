from __future__ import annotations

from pathlib import Path

from msm.data_nodes.indices import IndexValuesStorage
from msm.models import (
    IndexFormulaDefinitionTable,
    IndexFormulaInputTable,
    IndexTable,
    markets_sqlalchemy_models,
)


ROOT = Path(__file__).resolve().parents[3]
REVISION = ROOT / "src/msm_migrations/versions/mainsequence_markets/0001_initial_schema.py"


def test_index_model_owns_calculation_and_display_format() -> None:
    columns = IndexTable.__table__.columns
    assert {"calculation_method", "value_format", "value_suffix"}.issubset(columns.keys())
    checks = {str(item.sqltext) for item in IndexTable.__table__.constraints if hasattr(item, "sqltext")}
    assert "calculation_method IN ('formula', 'custom')" in checks
    assert "value_format IN ('decimal', 'percent')" in checks


def test_formula_input_is_relational_and_exact() -> None:
    columns = IndexFormulaInputTable.__table__.columns
    assert set(columns.keys()) == {
        "uid",
        "definition_uid",
        "asset_uid",
        "component_index_uid",
        "meta_table_uid",
        "observable",
    }
    assert columns.meta_table_uid.foreign_keys == set()
    assert len(columns.asset_uid.foreign_keys) == 1
    assert len(columns.component_index_uid.foreign_keys) == 1


def test_index_values_are_unit_free_and_reference_formula_definitions() -> None:
    columns = IndexValuesStorage.__table__.columns
    assert "unit" not in columns
    target = next(iter(columns.definition_uid.foreign_keys)).column.table
    assert target is IndexFormulaDefinitionTable.__table__


def test_model_registry_has_no_legacy_index_models() -> None:
    names = {model.__name__ for model in markets_sqlalchemy_models()}
    assert {"IndexFormulaDefinitionTable", "IndexFormulaInputTable"}.issubset(names)
    assert "IndexCalculationDefinitionTable" not in names
    assert "IndexCalculationLegTable" not in names
    assert "IndexResolvedLegsStorage" not in names


def test_initial_schema_creates_formula_index_tables_without_units() -> None:
    source = REVISION.read_text()
    assert "revision: str = '0001'" in source
    assert "op.create_table('ms_markets__indexformuladefinition'" in source
    assert "op.create_table('ms_markets__indexformulainput'" in source
    values = source[source.index("op.create_table('ms_markets__indexvaluests'"):]
    assert "sa.Column('unit'" not in values[: values.index("    )\n")]
