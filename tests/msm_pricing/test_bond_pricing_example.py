from __future__ import annotations

import ast
from pathlib import Path


def test_bond_pricing_example_replaces_default_market_data_bindings() -> None:
    example_path = (
        Path(__file__).parents[2] / "examples/msm_pricing/bond_pricing_example/main.py"
    )
    source = example_path.read_text()
    tree = ast.parse(source)

    attach_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "attach_pricing_schemas"
    ]

    assert any(
        _has_true_keyword(call, "seed_default_market_data_bindings")
        and _has_true_keyword(call, "replace_default_market_data_bindings")
        for call in attach_calls
    )
    assert "PRICING_CONTEXT_EOD" not in source
    assert "Upserted EOD pricing market-data context" not in source


def _has_true_keyword(call: ast.Call, keyword_name: str) -> bool:
    return any(
        keyword.arg == keyword_name
        and isinstance(keyword.value, ast.Constant)
        and keyword.value.value is True
        for keyword in call.keywords
    )
