"""Verify distribution identity, version, and complete current package sources.

The expected contents come from the hatch build configuration in pyproject.toml:
the wheel must hold exactly the files of the declared packages plus the
force-included skills, byte for byte, and the sdist must hold every declared
include path.
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename
from packaging.version import Version

PROJECT = Path(__file__).resolve().parents[1]
# Build caches are ignored by hatchling through .gitignore; they are not sources.
_IGNORED_NAMES = {"__pycache__", ".DS_Store"}
_IGNORED_SUFFIXES = {".pyc", ".pyo", ".pyd"}


def _tree(project: Path, relative: str) -> dict[str, bytes]:
    """Map each source file at a project path to its bytes, keyed by project-relative path."""
    root = project / relative
    paths = [root] if root.is_file() else sorted(root.rglob("*"))
    return {
        path.relative_to(project).as_posix(): path.read_bytes()
        for path in paths
        if path.is_file()
        and _IGNORED_NAMES.isdisjoint(path.relative_to(project).parts)
        and path.suffix not in _IGNORED_SUFFIXES
    }


def check(
    project: Path = PROJECT, *, dist: Path | None = None, expected_version: str | None = None
) -> list[str]:
    dist = dist or project / "dist"
    pyproject = tomllib.loads((project / "pyproject.toml").read_text())
    metadata = pyproject["project"]
    targets = pyproject["tool"]["hatch"]["build"]["targets"]
    packages = targets["wheel"]["packages"]
    force_include = targets["wheel"].get("force-include", {})
    sdist_include = [entry.lstrip("/") for entry in targets["sdist"]["include"]]
    expected_name = canonicalize_name(metadata["name"])
    expected_version = expected_version or metadata["version"]
    license_name = metadata["license"]["file"]
    license_text = (project / license_name).read_bytes()
    wheels = sorted(dist.glob("*.whl"))
    sources = sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        return ["Build exactly one wheel and one sdist before checking package sources."]

    errors = []
    for init in sorted((project / "src").glob("*/__init__.py")):
        package = f"src/{init.parent.name}"
        if package not in packages:
            errors.append(f"pyproject.toml does not ship the package {package}")

    for path, parser in ((wheels[0], parse_wheel_filename), (sources[0], parse_sdist_filename)):
        try:
            name, version, *_ = parser(path.name)
            if name != expected_name or version != Version(expected_version):
                errors.append(f"{path.name}: filename does not identify {expected_name} {expected_version}")
        except ValueError as exc:
            errors.append(f"{path.name}: invalid distribution filename: {exc}")

    def check_metadata(kind: str, payload: bytes) -> None:
        headers = BytesParser().parsebytes(payload)
        if canonicalize_name(headers.get("Name", "")) != expected_name:
            errors.append(f"{kind}: metadata has an unexpected distribution name")
        try:
            if Version(headers.get("Version", "")) != Version(expected_version):
                errors.append(f"{kind}: metadata does not declare expected version {expected_version}")
        except ValueError:
            errors.append(f"{kind}: metadata has no valid version")

    wheel_expected = {}
    for package in packages:
        parent = PurePosixPath(package).parent
        for name, payload in _tree(project, package).items():
            wheel_expected[PurePosixPath(name).relative_to(parent).as_posix()] = payload
    for source, target in force_include.items():
        for name, payload in _tree(project, source).items():
            wheel_expected[target + name.removeprefix(source)] = payload

    with ZipFile(wheels[0]) as archive:
        wheel_files = {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}
    dist_infos = {name.split("/", 1)[0] for name in wheel_files if name.split("/", 1)[0].endswith(".dist-info")}
    if len(dist_infos) == 1:
        info = dist_infos.pop()
        if f"{info}/METADATA" in wheel_files:
            check_metadata("wheel", wheel_files[f"{info}/METADATA"])
        else:
            errors.append("wheel omits its METADATA file")
        if wheel_files.get(f"{info}/licenses/{license_name}") != license_text:
            errors.append(f"wheel omits or changes the license file: {license_name}")
        entry_points = wheel_files.get(f"{info}/entry_points.txt", b"").decode()
        for script, target in metadata.get("scripts", {}).items():
            if f"{script} = {target}" not in entry_points:
                errors.append(f"wheel omits the console script: {script} = {target}")
    else:
        errors.append("wheel must contain exactly one .dist-info directory")
    installed = {
        name: payload
        for name, payload in wheel_files.items()
        if not name.split("/", 1)[0].endswith(".dist-info")
    }
    for name in sorted(installed.keys() - wheel_expected.keys()):
        errors.append(f"wheel contains a file with no current source: {name}")
    for name in sorted(wheel_expected.keys() - installed.keys()):
        errors.append(f"wheel omits {name}")
    for name in sorted(installed.keys() & wheel_expected.keys()):
        if installed[name] != wheel_expected[name]:
            errors.append(f"wheel changes {name}")

    sdist_expected = {}
    for entry in sdist_include:
        sdist_expected.update(_tree(project, entry))
    with tarfile.open(sources[0], "r:gz") as archive:
        members = {
            member.name.split("/", 1)[1]: member
            for member in archive.getmembers()
            if member.isfile() and "/" in member.name
        }

        def read(name: str) -> bytes:
            stream = archive.extractfile(members[name])
            return b"" if stream is None else stream.read()

        if "PKG-INFO" in members:
            check_metadata("sdist", read("PKG-INFO"))
        else:
            errors.append("sdist must contain a top-level PKG-INFO file")
        for name in sorted(sdist_expected.keys() - members.keys()):
            errors.append(f"sdist omits {name}")
        for name in sorted(sdist_expected.keys() & members.keys()):
            if read(name) != sdist_expected[name]:
                errors.append(f"sdist changes {name}")
        source_roots = tuple(f"{package}/" for package in packages)
        for name in sorted(members):
            if name.startswith(source_roots) and name not in sdist_expected:
                errors.append(f"sdist contains a file with no current source: {name}")
    return errors


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist-dir", type=Path, help="Distribution directory; defaults to dist/.")
    parser.add_argument("--expected-version", help="Version computed by the publishing workflow.")
    args = parser.parse_args()
    problems = check(dist=args.dist_dir, expected_version=args.expected_version)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        raise SystemExit(1)
    print("Wheel and sdist names, versions, resources, and sources passed.")
