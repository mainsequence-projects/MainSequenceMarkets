from __future__ import annotations

import ast
from pathlib import Path


def test_bond_pricing_example_creates_market_data_bindings_explicitly() -> None:
    example_path = Path(__file__).parents[2] / "examples/msm_pricing/bond_pricing_example/main.py"
    source = example_path.read_text()
    tree = ast.parse(source)

    attach_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "attach_pricing_schemas"
    ]

    assert any(
        _has_false_keyword(call, "seed_default_market_data_bindings") for call in attach_calls
    )
    assert '"DiscountCurvesStorage"' in source
    assert '"IndexFixingsStorage"' in source
    assert "PRICING_CONTEXT_EOD" not in source
    assert "PRICING_CONTEXT_DEFAULT" not in source
    assert "Upserted EOD pricing market-data context" not in source


def test_bond_pricing_example_uses_storage_uids_for_bindings() -> None:
    example_path = Path(__file__).parents[2] / "examples/msm_pricing/bond_pricing_example/main.py"
    source = example_path.read_text()

    assert "DiscountCurvesStorage.get_meta_table_uid()" in source
    assert "IndexFixingsStorage.get_meta_table_uid()" in source
    assert "DiscountCurvesStorage.get_identifier()" in source
    assert "IndexFixingsStorage.get_identifier()" in source
    assert "PricingMarketDataSet.upsert(" in source
    assert "PricingMarketDataSetBinding.upsert(" in source
    assert "CurveBuildingDetails.upsert(" in source
    assert "PricingMarketDataSetCurveBinding.upsert_index_curve_selection(" in source
    assert "data_node_uid=curve_data_node_uid" in source
    assert "data_node_uid=fixing_data_node_uid" in source
    assert 'role_key="projection"' in source
    assert "index_uid=index.uid" in source
    assert "quote_side=None" in source
    assert "curve_node._default_identifier()" not in source
    assert "fixing_node._default_identifier()" not in source


def test_bond_pricing_example_shows_valuation_position_usage() -> None:
    example_path = Path(__file__).parents[2] / "examples/msm_pricing/bond_pricing_example/main.py"
    source = example_path.read_text()

    assert "from msm_pricing.valuation import ValuationLine, ValuationPosition" in source
    assert "ValuationPosition(" in source
    assert "ValuationLine(" in source
    assert '"valuation_position_price"' in source
    assert '"valuation_position_breakdown"' in source


def test_mock_market_data_publishes_curve_key_nodes() -> None:
    example_path = Path(__file__).parents[2] / "examples/msm_pricing/utils/mock_market_data.py"
    source = example_path.read_text()

    assert "build_flat_forward_key_nodes(" in source
    assert '"key_nodes": key_nodes' in source
    assert '"metadata_json": {' in source
    assert "maturity_date=" in source
    assert "quote=" in source
    assert "quote_type=" in source
    assert "quote_unit=" in source
    assert "yield_value=" in source
    assert '"tenor"' not in source


def test_bond_pricing_example_reports_curve_key_node_count() -> None:
    example_path = Path(__file__).parents[2] / "examples/msm_pricing/bond_pricing_example/main.py"
    source = example_path.read_text()

    assert "_count_curve_key_nodes(" in source
    assert "key_nodes=_count_curve_key_nodes(curve_frame)" in source


def _has_false_keyword(call: ast.Call, keyword_name: str) -> bool:
    return any(
        keyword.arg == keyword_name
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is False
        for keyword in call.keywords
    )
