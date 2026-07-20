from __future__ import annotations

import datetime
import uuid

import pandas as pd
import pytest
from pydantic import ValidationError

from msm.analytics.indices import (
    FormulaSyntaxError,
    IncompleteFormulaObservationsError,
    IndexFormula,
    IndexFormulaDefinition,
    IndexFormulaError,
    IndexFormulaInput,
    calculate_formula_index,
    canonical_formula,
    compute_formula_definition_hash,
    formula_references,
    validate_formula_contract,
)


ASSET_TABLE_UID = uuid.UUID("11111111-1111-1111-1111-111111111111")
INDEX_TABLE_UID = uuid.UUID("22222222-2222-2222-2222-222222222222")
DEFINITION_UID = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _definition(**changes) -> IndexFormulaDefinition:
    values = {
        "uid": DEFINITION_UID,
        "index_uid": uuid.uuid4(),
        "version": 1,
        "status": "active",
        "valid_from": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        "formula": 'index["RATE"].price * 5 + asset["BOND"].yield',
        "alignment_policy": "exact",
        "missing_data_policy": "drop",
    }
    values.update(changes)
    return IndexFormulaDefinition.model_validate(values)


def _inputs() -> tuple[IndexFormulaInput, ...]:
    return (
        IndexFormulaInput.model_validate(
            {
                "source_reference": {"type": "index", "identifier": "RATE"},
                "meta_table_uid": INDEX_TABLE_UID,
                "observable": "price",
            }
        ),
        IndexFormulaInput.model_validate(
            {
                "source_reference": {"type": "asset", "identifier": "BOND"},
                "meta_table_uid": ASSET_TABLE_UID,
                "observable": "yield",
            }
        ),
    )


def _series(values: list[float], dates: list[str] | None = None) -> pd.Series:
    return pd.Series(
        values,
        index=pd.to_datetime(dates or ["2026-01-01", "2026-01-02"], utc=True),
    )


def test_formula_grammar_accepts_mixed_asset_index_and_keyword_observable() -> None:
    expression = 'index["RATE"].price * 5 + asset["BOND"].yield'

    assert canonical_formula(expression) == '((index["RATE"].price*5)+asset["BOND"].yield)'
    assert {item.expression for item in formula_references(expression)} == {
        'index["RATE"].price',
        'asset["BOND"].yield',
    }


@pytest.mark.parametrize(
    "expression",
    [
        'sum(asset["BOND"].price)',
        'asset["BOND"].price.__class__',
        'asset["BOND"].price if 1 else 0',
        'asset["BOND"].price[0]',
        "asset['BOND'].price",
    ],
)
def test_formula_grammar_rejects_non_arithmetic_syntax(expression: str) -> None:
    with pytest.raises((FormulaSyntaxError, ValidationError)):
        _definition(formula=expression)


def test_formula_inputs_must_exactly_match_references() -> None:
    with pytest.raises(ValueError, match="missing inputs"):
        validate_formula_contract(_definition(), _inputs()[:1])
    with pytest.raises(ValueError, match="duplicate"):
        validate_formula_contract(_definition(), (*_inputs(), _inputs()[0]))


def test_exact_formula_calculation_is_unit_free() -> None:
    definition = _definition()
    inputs = _inputs()
    result = calculate_formula_index(
        index_identifier="MIXED",
        definition=definition,
        inputs=inputs,
        observations={
            inputs[0].reference: _series([2.0, 3.0]),
            inputs[1].reference: _series([0.1, 0.2]),
        },
    ).values

    assert result["value"].tolist() == pytest.approx([10.1, 15.2])
    assert "unit" not in result.columns
    assert result["definition_uid"].tolist() == [DEFINITION_UID, DEFINITION_UID]


def test_pydantic_formula_evaluates_historical_without_persistence_identity() -> None:
    inputs = _inputs()
    formula = IndexFormula(
        formula='index["RATE"].price * 5 + asset["BOND"].yield',
        inputs=inputs,
        alignment_policy="exact",
        missing_data_policy="fail",
    )

    result = formula.evaluate_historical(
        {
            inputs[0].reference.expression: pd.DataFrame(
                {"price": [2.0, 3.0]},
                index=pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True),
            ),
            inputs[1].reference.expression: _series([0.1, 0.2]),
        }
    ).values

    assert result.index.name == "time_index"
    assert result.index.tolist() == list(
        pd.to_datetime(["2026-01-01", "2026-01-02"], utc=True)
    )
    assert result.columns.tolist() == ["value", "source_as_of"]
    assert result["value"].tolist() == pytest.approx([10.1, 15.2])
    assert result["source_as_of"].tolist() == result.index.tolist()


def test_pydantic_formula_validates_reference_input_equality() -> None:
    with pytest.raises(ValidationError, match="missing inputs"):
        IndexFormula(
            formula='index["RATE"].price * 5 + asset["BOND"].yield',
            inputs=_inputs()[:1],
        )


def test_pydantic_formula_builds_from_persisted_definition() -> None:
    definition = _definition(
        alignment_policy="asof",
        alignment_parameters_json={"max_staleness_seconds": 86_400},
    )

    formula = IndexFormula.from_definition(definition, _inputs())

    assert formula.formula == definition.formula
    assert formula.alignment_policy == "asof"
    assert formula.alignment_parameters_json == {"max_staleness_seconds": 86_400}
    assert "uid" not in formula.model_dump()


def test_asof_alignment_is_backward_and_bounded() -> None:
    definition = _definition(
        alignment_policy="asof",
        alignment_parameters_json={"max_staleness_seconds": 86_400},
    )
    inputs = _inputs()
    result = calculate_formula_index(
        index_identifier="MIXED",
        definition=definition,
        inputs=inputs,
        observations={
            inputs[0].reference: _series([2.0], ["2026-01-01"]),
            inputs[1].reference: _series([0.2], ["2026-01-02"]),
        },
    ).values

    assert result["time_index"].tolist() == [pd.Timestamp("2026-01-02", tz="UTC")]
    assert result["value"].tolist() == pytest.approx([10.2])


def test_missing_policy_fail_rejects_incomplete_values() -> None:
    definition = _definition(missing_data_policy="fail")
    inputs = _inputs()
    with pytest.raises(IncompleteFormulaObservationsError):
        calculate_formula_index(
            index_identifier="MIXED",
            definition=definition,
            inputs=inputs,
            observations={
                inputs[0].reference: _series([2.0, float("nan")]),
                inputs[1].reference: _series([0.1, 0.2]),
            },
        )


def test_formula_rejects_zero_denominator() -> None:
    definition = _definition(formula='asset["BOND"].yield / index["RATE"].price')
    inputs = _inputs()
    with pytest.raises(IndexFormulaError, match="denominator"):
        calculate_formula_index(
            index_identifier="MIXED",
            definition=definition,
            inputs=inputs,
            observations={
                inputs[0].reference: _series([0.0, 1.0]),
                inputs[1].reference: _series([0.1, 0.2]),
            },
        )


def test_formula_hash_is_stable_and_includes_exact_source_table() -> None:
    definition = _definition()
    inputs = _inputs()
    digest = compute_formula_definition_hash(definition, inputs)
    changed = inputs[0].model_copy(update={"meta_table_uid": uuid.uuid4()})

    assert digest == compute_formula_definition_hash(definition, tuple(reversed(inputs)))
    assert digest != compute_formula_definition_hash(definition, (changed, inputs[1]))
