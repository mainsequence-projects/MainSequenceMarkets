from importlib.metadata import version


def test_import_msm() -> None:
    import msm

    assert msm.__version__ == version("ms-markets")
