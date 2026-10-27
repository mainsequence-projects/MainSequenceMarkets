"""The ms-markets version, whether installed or run from its source checkout."""

from __future__ import annotations

import tomllib
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DISTRIBUTION_NAME = "ms-markets"
SOURCE_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]


def package_version() -> str:
    """Return the installed ms-markets version, else the one its checkout declares.

    Main Sequence images run this repository from ``/workspace`` without
    installing it (platform ADR-080), so a Job or the Markets API has no package
    metadata for ``ms-markets``. Its ``pyproject.toml`` declares the version.
    """
    try:
        return version(DISTRIBUTION_NAME)
    except PackageNotFoundError:
        pyproject = SOURCE_CHECKOUT_ROOT / "pyproject.toml"
        if not pyproject.is_file():
            raise RuntimeError("ms-markets package metadata is unavailable.") from None
        project = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
        declared = project.get("version")
        if project.get("name") != DISTRIBUTION_NAME or not isinstance(declared, str) or not declared.strip():
            raise RuntimeError("ms-markets package version is unavailable.") from None
        return declared
