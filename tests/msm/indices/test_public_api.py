from __future__ import annotations

import msm.api as api
from msm.api import (
    FormulaIndex,
    Index,
    IndexFormula,
    IndexFormulaDefinition,
    IndexFormulaEvaluation,
    IndexFormulaInput,
    calculate_formula_index,
)


def test_formula_index_public_surface_is_explicit() -> None:
    assert FormulaIndex.__name__ == "FormulaIndex"
    assert Index.__name__ == "Index"
    assert IndexFormula.__name__ == "IndexFormula"
    assert IndexFormulaDefinition.__name__ == "IndexFormulaDefinition"
    assert IndexFormulaEvaluation.__name__ == "IndexFormulaEvaluation"
    assert IndexFormulaInput.__name__ == "IndexFormulaInput"
    assert callable(calculate_formula_index)


def test_legacy_derived_index_surface_is_not_exported() -> None:
    for name in (
        "DerivedIndex",
        "IndexCalculationDefinition",
        "IndexCalculationLeg",
        "calculate_index",
        "UNIT_REGISTRY",
    ):
        assert not hasattr(api, name)
