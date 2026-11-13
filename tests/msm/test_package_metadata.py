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
    assert Version("9.0.19") not in requirement.specifier
    # 9.0.25/26 raise on `team_uids`, 9.0.29 brought access policies, and MetaTables
    # 0.1.60 and later need 9.0.31, the first SDK whose `Agent` parses platform Agent reads.
    assert Version("9.0.25") not in requirement.specifier
    assert Version("9.0.26") not in requirement.specifier
    assert Version("9.0.28") not in requirement.specifier
    assert Version("9.0.29") not in requirement.specifier
    assert Version("9.0.30") not in requirement.specifier
    assert Version("9.0.31") in requirement.specifier
    assert Version("9.99.0") in requirement.specifier
    assert Version("10.0.0") not in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)


def test_package_metadata_requires_extracted_metatables_client() -> None:
    requirement = _requirement("mainsequence-metatable")

    assert Version("0.1.30") not in requirement.specifier
    assert Version("0.1.31") not in requirement.specifier
    assert Version("0.1.32") not in requirement.specifier
    assert Version("0.1.33") not in requirement.specifier
    assert Version("0.1.34") not in requirement.specifier
    assert Version("0.1.35") not in requirement.specifier
    # 0.1.46 brought roles, 0.1.47's client is broken, 0.1.20-0.1.50 break on SDK 9.0.30,
    # 0.1.57 is the first release that hashes updater configurations holding dates and times,
    # 0.1.60 runs statement lists in one transaction, 0.1.61 binds UUIDs on SQLite inside
    # `IN` lists and as text, which the snapshot writes need on a SQLite DataSource, and
    # 0.1.64 waits out a MetaTables API rollout during discovery (MetaTables#108), which the
    # migration Job needs when it overlaps one.
    assert Version("0.1.47") not in requirement.specifier
    assert Version("0.1.50") not in requirement.specifier
    assert Version("0.1.56") not in requirement.specifier
    assert Version("0.1.57") not in requirement.specifier
    assert Version("0.1.60") not in requirement.specifier
    assert Version("0.1.63") not in requirement.specifier
    assert Version("0.1.64") in requirement.specifier
    assert Version("0.1.99") in requirement.specifier
    assert Version("0.2.0") not in requirement.specifier
    assert all(specifier.operator != "==" for specifier in requirement.specifier)
    assert not any(Requirement(value).name == "metatables" for value in _project()["dependencies"])
