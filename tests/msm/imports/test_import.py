from importlib.metadata import version
from importlib.util import find_spec


def test_import_msm() -> None:
    import msm

    assert msm.__version__ == version("ms-markets")


def test_pricing_uses_separate_import_root() -> None:
    assert find_spec(".".join(("msm", "pricing"))) is None

    import msm_pricing

    assert "FixedRateBond" in msm_pricing.__all__
