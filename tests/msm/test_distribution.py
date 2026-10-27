"""ms-markets must know its version when Main Sequence runs it without installing it."""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import PackageNotFoundError
from pathlib import Path

import pytest

from msm import distribution

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DECLARED_VERSION = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
    "project"
]["version"]


def _not_installed(name: str) -> str:
    raise PackageNotFoundError(name)


def test_installed_metadata_is_preferred(monkeypatch):
    monkeypatch.setattr(distribution, "version", lambda name: "9.9.9")

    assert distribution.package_version() == "9.9.9"


def test_source_checkout_declares_the_version_when_not_installed(monkeypatch):
    # Main Sequence images run /workspace via PYTHONPATH without installing it (ADR-080).
    monkeypatch.setattr(distribution, "version", _not_installed)

    assert distribution.package_version() == DECLARED_VERSION


def test_missing_checkout_and_metadata_fail_clearly(monkeypatch, tmp_path):
    monkeypatch.setattr(distribution, "version", _not_installed)
    monkeypatch.setattr(distribution, "SOURCE_CHECKOUT_ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="metadata is unavailable"):
        distribution.package_version()


def test_another_projects_pyproject_is_not_read_as_ms_markets(monkeypatch, tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "other"\nversion = "1.0.0"\n', encoding="utf-8")
    monkeypatch.setattr(distribution, "version", _not_installed)
    monkeypatch.setattr(distribution, "SOURCE_CHECKOUT_ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="version is unavailable"):
        distribution.package_version()


def test_only_the_distribution_module_reads_ms_markets_metadata():
    lookup = re.compile(r"""(version|distribution|metadata)\(\s*["']ms-markets["']""")
    offenders = [
        str(path.relative_to(REPOSITORY_ROOT))
        for root in ("src", "apps", "jobs")
        for path in (REPOSITORY_ROOT / root).rglob("*.py")
        if lookup.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
