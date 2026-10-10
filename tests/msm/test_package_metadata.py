from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _project() -> dict:
    return tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())["project"]


def _requirement(name: str) -> Requirement:
    return next(
        Requirement(value)
        for value in _project()["dependencies"]
        if Requirement(value).name == name
    )


def test_package_metadata_enforces_sdk_9_floor_without_exact_patch_pin() -> None:
    requirement = _requirement("mainsequence")

    assert Version(_project()["version"]).major >= 2
    assert Version("8.1.11") not in requirement.specifier
    assert Version("8.99.0") not in requirement.specifier
    assert Version("9.0.0") not in requirement.specifier
    assert Version("9.0.1") not in requirement.specifier
    assert Version("9.0.5") not in requirement.specifier
    assert Version("9.0.18") not in requirement.specifier
    assert Version("9.0.19") in requirement.specifier
    assert Version("9.99.0") in requirement.specifier
    assert Version("10.0.0") not in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)


def test_package_metadata_requires_extracted_metatables_client() -> None:
    requirement = _requirement("mainsequence-metatable")

    assert Version("0.1.30") not in requirement.specifier
    assert Version("0.1.31") in requirement.specifier
    assert Version("0.1.99") in requirement.specifier
    assert Version("0.2.0") not in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)
    assert not any(Requirement(value).name == "metatables" for value in _project()["dependencies"])
