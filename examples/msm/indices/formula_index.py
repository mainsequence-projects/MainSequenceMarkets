"""Evaluate historical formula values from one component Index and one Asset."""

from __future__ import annotations

import uuid

import pandas as pd

from msm.api import Asset, Index, IndexFormula, IndexFormulaInput
from msm.services.indices import RelatedMetaTable


FORMULA = 'index["MXN-TIIE-28D"].price * 5 + asset["MX-GOVT-5Y"].yield'
RATE_VALUES_META_TABLE_UID = uuid.UUID("11111111-1111-1111-1111-111111111111")
BOND_VALUES_META_TABLE_UID = uuid.UUID("22222222-2222-2222-2222-222222222222")


def discover_source_tables(
    *,
    source_index_uid: uuid.UUID,
    source_asset_uid: uuid.UUID,
) -> dict[str, tuple[RelatedMetaTable, ...]]:
    """Return formula-compatible source candidates before choosing observables."""

    return {
        "index": Index.list_related_meta_tables(
            source_index_uid,
            numeric=True,
            timestamped=True,
        ),
        "asset": Asset.list_related_meta_tables(
            source_asset_uid,
            numeric=True,
            timestamped=True,
        ),
    }


def build_formula() -> IndexFormula:
    inputs = (
        IndexFormulaInput.model_validate(
            {
                "source_reference": {"type": "index", "identifier": "MXN-TIIE-28D"},
                "meta_table_uid": RATE_VALUES_META_TABLE_UID,
                "observable": "price",
            }
        ),
        IndexFormulaInput.model_validate(
            {
                "source_reference": {"type": "asset", "identifier": "MX-GOVT-5Y"},
                "meta_table_uid": BOND_VALUES_META_TABLE_UID,
                "observable": "yield",
            }
        ),
    )
    return IndexFormula(
        formula=FORMULA,
        inputs=inputs,
        alignment_policy="exact",
        missing_data_policy="fail",
    )


def run() -> dict[str, object]:
    formula = build_formula()
    times = pd.date_range("2026-01-01", periods=2, freq="D", tz="UTC")
    observations = {
        formula.inputs[0].reference: pd.Series([0.1050, 0.1060], index=times),
        formula.inputs[1].reference: pd.Series([0.0920, 0.0910], index=times),
    }
    values = formula.evaluate_historical(observations).values
    return {"formula": formula, "values": values}


if __name__ == "__main__":
    print(run()["values"])
