"""A renamed, stale, or incomplete build must never pass the upload gate."""

import io
import tarfile
from zipfile import ZipFile

import pytest

from scripts.check_distribution_sources import check

PYPROJECT = """\
[project]
name = "ms-markets"
version = "0.1.0"
license = { file = "LICENSE" }

[project.scripts]
msm = "msm_cli.main:main"

[tool.hatch.build.targets.wheel]
packages = ["src/msm", "src/msm_cli"]

[tool.hatch.build.targets.wheel.force-include]
".agents/skills/ms_markets" = "msm_cli/_skills/ms_markets"

[tool.hatch.build.targets.sdist]
include = ["/.agents/skills/ms_markets", "/LICENSE", "/pyproject.toml", "/src", "/tests"]
"""
SOURCES = {
    "src/msm/__init__.py": "",
    "src/msm/py.typed": "",
    "src/msm/services/open_figi_lists/market_sector.json": "[]",
    "src/msm_cli/__init__.py": "",
    "src/msm_cli/main.py": "def main(): ...",
    ".agents/skills/ms_markets/accounts/SKILL.md": "Account workflow.",
    "tests/test_example.py": "",
    "LICENSE": "License terms",
}
DIST_INFO = "ms_markets-0.1.0.dist-info"


def _distributions(project, *, name="ms-markets", version="0.1.0", omit=(), extra=None, changed=None):
    (project / "pyproject.toml").write_text(PYPROJECT)
    for path, text in SOURCES.items():
        (project / path).parent.mkdir(parents=True, exist_ok=True)
        (project / path).write_text(text)
    cache = project / "src/msm/__pycache__/__init__.cpython-313.pyc"
    cache.parent.mkdir()
    cache.write_bytes(b"cache")
    wheel_files = {
        path.removeprefix("src/"): text for path, text in SOURCES.items() if path.startswith("src/")
    }
    wheel_files.update({
        "msm_cli/_skills/ms_markets/accounts/SKILL.md": SOURCES[".agents/skills/ms_markets/accounts/SKILL.md"],
        f"{DIST_INFO}/METADATA": f"Name: {name}\nVersion: {version}\n",
        f"{DIST_INFO}/entry_points.txt": "[console_scripts]\nmsm = msm_cli.main:main\n",
        f"{DIST_INFO}/licenses/LICENSE": SOURCES["LICENSE"],
    })
    sdist_files = {**SOURCES, "pyproject.toml": PYPROJECT, "PKG-INFO": f"Name: {name}\nVersion: {version}\n"}
    for files in (wheel_files, sdist_files):
        files.update(extra or {})
        files.update(changed or {})
        for path in omit:
            files.pop(path, None)
    dist = project / "dist"
    dist.mkdir()
    with ZipFile(dist / "ms_markets-0.1.0-py3-none-any.whl", "w") as archive:
        for path, text in wheel_files.items():
            archive.writestr(path, text)
    with tarfile.open(dist / "ms_markets-0.1.0.tar.gz", "w:gz") as archive:
        for path, text in sdist_files.items():
            payload = text.encode()
            member = tarfile.TarInfo(f"ms_markets-0.1.0/{path}")
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    return dist


def test_complete_distributions_pass_and_build_caches_are_not_sources(tmp_path):
    _distributions(tmp_path)
    assert check(tmp_path) == []


@pytest.mark.parametrize("override", [{"name": "msm"}, {"version": "0.0.9"}])
def test_wrong_metadata_is_refused_in_both_artifacts(tmp_path, override):
    _distributions(tmp_path, **override)
    errors = check(tmp_path)
    assert any(error.startswith("wheel: metadata") for error in errors)
    assert any(error.startswith("sdist: metadata") for error in errors)


def test_expected_development_version_checks_names_and_metadata(tmp_path):
    _distributions(tmp_path)
    errors = check(tmp_path, expected_version="0.1.0.dev8")
    assert any("filename does not identify ms-markets 0.1.0.dev8" in error for error in errors)
    assert any(error.startswith("wheel: metadata") for error in errors)
    assert any(error.startswith("sdist: metadata") for error in errors)


@pytest.mark.parametrize("path", [
    "msm/__init__.py",
    "msm/services/open_figi_lists/market_sector.json",
    "msm_cli/_skills/ms_markets/accounts/SKILL.md",
])
def test_missing_wheel_sources_and_resources_are_refused(tmp_path, path):
    _distributions(tmp_path, omit=[path])
    assert f"wheel omits {path}" in check(tmp_path)


@pytest.mark.parametrize("path", ["src/msm/py.typed", "tests/test_example.py", "LICENSE"])
def test_missing_sdist_sources_are_refused(tmp_path, path):
    _distributions(tmp_path, omit=[path])
    assert f"sdist omits {path}" in check(tmp_path)


def test_deleted_modules_are_refused_in_both_artifacts(tmp_path):
    _distributions(tmp_path, extra={"msm/deleted.py": "", "src/msm/deleted.py": ""})
    errors = check(tmp_path)
    assert "wheel contains a file with no current source: msm/deleted.py" in errors
    assert "sdist contains a file with no current source: src/msm/deleted.py" in errors


def test_changed_skill_resource_is_refused(tmp_path):
    _distributions(tmp_path, changed={"msm_cli/_skills/ms_markets/accounts/SKILL.md": "stale"})
    assert "wheel changes msm_cli/_skills/ms_markets/accounts/SKILL.md" in check(tmp_path)


def test_unlisted_package_is_refused(tmp_path):
    _distributions(tmp_path)
    (tmp_path / "src/msm_new").mkdir()
    (tmp_path / "src/msm_new/__init__.py").write_text("")
    assert "pyproject.toml does not ship the package src/msm_new" in check(tmp_path)


@pytest.mark.parametrize("path, error", [
    (f"{DIST_INFO}/licenses/LICENSE", "wheel omits or changes the license file: LICENSE"),
    (f"{DIST_INFO}/entry_points.txt", "wheel omits the console script: msm = msm_cli.main:main"),
])
def test_wheel_metadata_resources_are_required(tmp_path, path, error):
    _distributions(tmp_path, omit=[path])
    assert error in check(tmp_path)


def test_extra_distributions_are_refused(tmp_path):
    dist = _distributions(tmp_path)
    (dist / "ms_markets-0.0.9-py3-none-any.whl").write_bytes(b"")
    assert check(tmp_path) == ["Build exactly one wheel and one sdist before checking package sources."]
