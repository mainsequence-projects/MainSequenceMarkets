"""``msm_pricing`` is its own import root.

Split from ``tests/msm/imports/test_import.py``.
"""

from __future__ import annotations

from importlib.util import find_spec


def test_pricing_uses_separate_import_root() -> None:
    assert find_spec(".".join(("msm", "pricing"))) is None

    import msm_pricing

    assert "FixedRateBond" in msm_pricing.__all__
