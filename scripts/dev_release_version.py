"""Read, validate, and update the release version declared in pyproject.toml.

Development builds use X.Y.Z.devN; a merge into main releases X.Y.Z. PyPI is
consulted only to reject used versions, never to choose a different base.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"
_PROJECT_SECTION = re.compile(r"(^\[project\][^\n]*\n)(.*?)(?=^\[|\Z)", re.M | re.S)
_VERSION_ASSIGNMENT = re.compile(r"^version\s*=\s*(['\"])[^\n]*?\1[ \t]*(?:#.*)?$", re.M)


class DevVersionError(RuntimeError):
    """A release cannot safely be versioned or published."""


def declared_release(text: str) -> Version:
    raw = tomllib.loads(text).get("project", {}).get("version")
    if not isinstance(raw, str) or not re.fullmatch(r"\d+\.\d+\.\d+", raw):
        raise DevVersionError("pyproject.toml must declare a final X.Y.Z project version.")
    return Version(raw)


def apply_version(text: str, version: str) -> str:
    """Change only the version assignment inside [project]."""
    section = _PROJECT_SECTION.search(text)
    if section is None or len(_VERSION_ASSIGNMENT.findall(section[2])) != 1:
        raise DevVersionError("Expected exactly one version assignment in [project].")
    body = _VERSION_ASSIGNMENT.sub(f'version = "{version}"', section[2], count=1)
    result = text[:section.start()] + section[1] + body + text[section.end():]
    if tomllib.loads(result)["project"]["version"] != version:
        raise DevVersionError("Could not update the project version.")
    return result


def fetch_releases(package: str, timeout: float = 15.0) -> Mapping[str, Any]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {}  # A pending trusted publisher can create the first release.
        raise DevVersionError(f"Could not read PyPI releases: HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DevVersionError(f"Could not read PyPI releases: {exc}.") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("releases"), dict):
        raise DevVersionError("PyPI returned an invalid release index.")
    return payload["releases"]


def latest_final_version(releases: Mapping[str, Any]) -> Version | None:
    """Include yanked/deleted finals: their version numbers cannot be reused."""
    finals = []
    for raw in releases:
        try:
            version = Version(raw)
        except InvalidVersion:
            continue
        if not version.is_prerelease and not version.is_postrelease and version.local is None:
            finals.append(version)
    return max(finals, default=None)


def release_version(declared: Version, releases: Mapping[str, Any], run_number: int | None = None) -> str:
    latest = latest_final_version(releases)
    if latest is not None and declared <= latest:
        raise DevVersionError(f"{latest} is already released; pyproject.toml must declare the next release.")
    if run_number is not None and run_number < 1:
        raise DevVersionError("The development run number must be positive.")
    target = str(declared) if run_number is None else f"{declared}.dev{run_number}"
    for raw in releases:
        try:
            existing = Version(raw)
        except InvalidVersion:
            continue
        if existing == Version(target):
            raise DevVersionError(f"Version {target} already exists on PyPI.")
    return target


def next_patch(version: Version) -> str:
    return f"{version.major}.{version.minor}.{version.micro + 1}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run-number", type=int, help="GitHub development publisher run number.")
    mode.add_argument("--final", action="store_true", help="Validate and print the final release version.")
    mode.add_argument("--bump-patch", action="store_true", help="Write the next patch version after release.")
    parser.add_argument("--write", action="store_true", help="Write the development version for this build only.")
    args = parser.parse_args(argv)
    if args.write and args.run_number is None:
        parser.error("--write requires --run-number")

    text = PYPROJECT.read_text(encoding="utf-8")
    declared = declared_release(text)
    if args.bump_patch:
        target = next_patch(declared)
        PYPROJECT.write_text(apply_version(text, target), encoding="utf-8")
    else:
        package = tomllib.loads(text)["project"]["name"]
        releases = fetch_releases(package)
        target = release_version(declared, releases, args.run_number)
        print(f"Declared release: {declared}; PyPI latest final: {latest_final_version(releases) or 'none'}", file=sys.stderr)
        if args.write:
            PYPROJECT.write_text(apply_version(text, target), encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (DevVersionError, tomllib.TOMLDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
