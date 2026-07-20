from __future__ import annotations

import datetime
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from msm.analytics.indices import IndexFormulaDefinition, IndexFormulaInput
from msm.api.formula_indices import FormulaIndex
from msm.api.indices import IndexCreate, IndexUpdate
from msm.api.indices import Index
from msm.api import formula_indices as formula_api


def test_formula_input_public_payload_has_only_requested_fields() -> None:
    payload = {
        "source_reference": {"type": "asset", "identifier": "BOND"},
        "meta_table_uid": uuid.uuid4(),
        "observable": "yield",
    }
    formula_input = IndexFormulaInput.model_validate(payload)

    assert formula_input.model_dump(mode="json") == {
        **payload,
        "meta_table_uid": str(payload["meta_table_uid"]),
    }
    for removed in ("key", "resolver", "identity_column", "value_column", "static_dimension_filters"):
        with pytest.raises(ValidationError):
            IndexFormulaInput.model_validate({**payload, removed: "not-supported"})


def test_index_create_requires_formula_or_custom_and_general_formatting() -> None:
    index = IndexCreate(
        unique_identifier="MIXED",
        index_type="market_observable",
        display_name="Mixed",
        calculation_method="formula",
        value_format="percent",
        value_suffix=" pa",
    )

    assert index.calculation_method == "formula"
    assert index.value_format == "percent"
    assert index.value_suffix == "pa"
    with pytest.raises(ValidationError):
        IndexCreate(
            unique_identifier="BAD",
            index_type="market_observable",
            display_name="Bad",
            calculation_method="weighted_sum",
            value_format="basis_points",
        )


def test_index_update_does_not_expose_removed_attributes() -> None:
    for field in ("provider", "methodology_owner", "result_unit", "effective_from"):
        with pytest.raises(ValidationError):
            IndexUpdate.model_validate({field: "removed"})


def test_formula_definition_uses_validity_not_effective_dates() -> None:
    definition = IndexFormulaDefinition(
        valid_from=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        formula='index["RATE"].price',
    )
    assert definition.valid_to is None
    with pytest.raises(ValidationError):
        IndexFormulaDefinition.model_validate(
            {
                "effective_from": datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
                "formula": 'index["RATE"].price',
            }
        )


def test_formula_index_exposes_activate_and_retire_lifecycle(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    definition_uid = uuid.uuid4()
    definition = IndexFormulaDefinition(
        uid=definition_uid,
        index_uid=index_uid,
        version=1,
        valid_from=datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
        formula='asset["BOND"].yield',
    )
    formula = FormulaIndex(
        index=Index(
            uid=index_uid,
            unique_identifier="FORMULA",
            index_type="interest_rate",
            display_name="Formula",
            calculation_method="formula",
            value_format="percent",
        ),
        definition=definition,
        inputs=(
            IndexFormulaInput(
                source_reference={"type": "asset", "identifier": "BOND"},
                meta_table_uid=uuid.uuid4(),
                observable="yield",
            ),
        ),
    )
    context = object()
    activated_definition = definition.model_copy(update={"status": "active"})
    retired_at = datetime.datetime(2027, 1, 1, tzinfo=datetime.UTC)
    retired_definition = activated_definition.model_copy(
        update={"status": "retired", "valid_to": retired_at}
    )
    monkeypatch.setattr(
        FormulaIndex,
        "_active_context",
        classmethod(lambda _cls: context),
    )
    monkeypatch.setattr(
        formula_api,
        "activate_formula_definition",
        lambda active_context, *, definition_uid: activated_definition,
    )
    monkeypatch.setattr(
        formula_api,
        "retire_formula_definition",
        lambda active_context, *, definition_uid, valid_to: retired_definition,
    )

    active = formula.activate()
    retired = active.retire(valid_to=retired_at)

    assert active.definition.status == "active"
    assert retired.definition.status == "retired"
    assert retired.definition.valid_to == retired_at


def test_formula_source_meta_table_rejects_additional_grain_dimension(monkeypatch) -> None:
    target_uid = uuid.uuid4()
    meta_table = SimpleNamespace(
        time_indexed=True,
        time_index_name="time_index",
        index_names=["time_index", "asset_identifier", "venue"],
        columns=[
            SimpleNamespace(name="time_index", data_type="datetime64[ns, UTC]"),
            SimpleNamespace(name="asset_identifier", data_type="string"),
            SimpleNamespace(name="yield", data_type="float64"),
            SimpleNamespace(name="venue", data_type="string"),
        ],
        foreign_keys=[
            SimpleNamespace(
                source_columns=["asset_identifier"],
                target_table_uid=target_uid,
                target_columns=["unique_identifier"],
            )
        ],
    )
    context = SimpleNamespace(meta_table_uid_for_model=lambda _model: target_uid)
    formula_input = IndexFormulaInput(
        source_reference={"type": "asset", "identifier": "BOND"},
        meta_table_uid=uuid.uuid4(),
        observable="yield",
    )
    monkeypatch.setattr(formula_api.MetaTable, "get_by_uid", lambda _uid: meta_table)

    with pytest.raises(ValueError, match="grain must be exactly"):
        formula_api._validate_source_meta_table(context, formula_input)
