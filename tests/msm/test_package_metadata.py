from pathlib import Path
import tomllib

from packaging.requirements import Requirement
from packaging.version import Version


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_package_metadata_enforces_sdk_8_hard_cut_without_exact_patch_pin() -> None:
    project = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())["project"]
    requirement = next(
        Requirement(value)
        for value in project["dependencies"]
        if Requirement(value).name == "mainsequence"
    )

    assert Version(project["version"]).major >= 1
    assert Version("6.0.53") not in requirement.specifier
    assert Version("7.99.0") not in requirement.specifier
    assert Version("8.0.3") not in requirement.specifier
    assert Version("8.0.4") in requirement.specifier
    assert Version("8.99.0") in requirement.specifier
    assert Version("9.0.0") in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)
