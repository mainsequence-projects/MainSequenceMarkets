"""Each package imports only the packages it depends on, and so do its tests (ADR 0019).

``DEPENDS_ON`` is the package map. Core ``msm`` depends on nothing first-party;
``msm_portfolios`` and ``msm_pricing`` depend on ``msm`` and not on each other; the
migrations collect every package's models; the API serves all three. A test lives
under the package it exercises: ``tests/<package>/`` may import only what
``<package>`` depends on, so a change in a package needs only its own tests and those
of the packages that depend on it (see ``docs/testing.md``).

Imports are read from the source, at any depth, including ``importlib.import_module``
with a literal name. A test's imports include those of the ``tests.support`` modules
and ``examples`` it imports. ``tests.support.migrations`` builds databases with the
shared migration chain, which every database test needs, so it counts as no package.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]

DEPENDS_ON: dict[str, frozenset[str]] = {
    "msm": frozenset({"msm"}),
    "msm_portfolios": frozenset({"msm", "msm_portfolios"}),
    "msm_pricing": frozenset({"msm", "msm_pricing"}),
    "msm_migrations": frozenset({"msm", "msm_portfolios", "msm_pricing", "msm_migrations"}),
    # `msm series publish` and `msm registry assign-manager` run msm_portfolios (ADR 0060).
    "msm_cli": frozenset({"msm", "msm_portfolios", "msm_cli"}),
    "apps": frozenset({"msm", "msm_portfolios", "msm_pricing", "apps"}),
}
SOURCES = {
    "msm": "src/msm",
    "msm_portfolios": "src/msm_portfolios",
    "msm_pricing": "src/msm_pricing",
    "msm_migrations": "src/msm_migrations",
    "msm_cli": "src/msm_cli",
    "apps": "apps",
}
# Test directories that are not a package's own: identities and renames across packages,
# and the distribution checks.
TEST_DIRECTORIES: dict[str, frozenset[str]] = {
    **{package: DEPENDS_ON[package] for package in SOURCES},
    "identity": frozenset({"msm", "msm_portfolios", "msm_pricing", "msm_migrations", "msm_cli"}),
}
FIRST_PARTY = frozenset({*SOURCES, "jobs", "examples", "scripts"})
# The compatibility alias `msm.migrations:migration` re-exports the provider.
SOURCE_EXCEPTIONS = {"src/msm/migrations/__init__.py": frozenset({"msm_migrations"})}
INFRASTRUCTURE = frozenset({"tests.support.migrations"})


def _imported_modules(path: Path) -> Iterator[str]:
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module
            for alias in node.names:
                yield f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and getattr(node.func, "attr", getattr(node.func, "id", None)) == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            yield node.args[0].value


def _module_file(module: str) -> Path | None:
    base = REPOSITORY.joinpath(*module.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _packages(path: Path, seen: set[Path] | None = None) -> set[str]:
    """First-party packages ``path`` imports, following tests.support and examples."""

    seen = set() if seen is None else seen
    if path in seen:
        return set()
    seen.add(path)
    packages: set[str] = set()
    for module in _imported_modules(path):
        head = module.split(".")[0]
        if module in INFRASTRUCTURE or head not in (*FIRST_PARTY, "tests"):
            continue
        if head in ("examples", "tests"):
            if module.startswith("tests.") and not module.startswith("tests.support"):
                packages.add(module)  # another test module: never allowed
                continue
            target = _module_file(module)
            if target is not None:
                packages |= _packages(target, seen)
            continue
        packages.add(head)
    return packages


def test_each_package_imports_only_the_packages_it_depends_on() -> None:
    offenders = []
    for package, root in SOURCES.items():
        for path in sorted((REPOSITORY / root).rglob("*.py")):
            relative = str(path.relative_to(REPOSITORY))
            allowed = DEPENDS_ON[package] | SOURCE_EXCEPTIONS.get(relative, frozenset())
            imported = {
                module.split(".")[0]
                for module in _imported_modules(path)
                if module.split(".")[0] in SOURCES
            }
            if imported - allowed:
                offenders.append(f"{relative}: {sorted(imported - allowed)}")

    assert offenders == []


def test_each_test_imports_only_what_its_package_depends_on() -> None:
    offenders = []
    for directory, allowed in TEST_DIRECTORIES.items():
        for path in sorted((REPOSITORY / "tests" / directory).rglob("*.py")):
            extra = _packages(path) - allowed - {"jobs"}
            if extra:
                offenders.append(f"{path.relative_to(REPOSITORY)}: {sorted(extra)}")

    assert offenders == []


def test_every_test_lives_under_a_known_directory() -> None:
    known = {*TEST_DIRECTORIES, "packaging", "support", "contracts"}
    directories = {
        path.relative_to(REPOSITORY / "tests").parts[0]
        for path in (REPOSITORY / "tests").rglob("test_*.py")
        if len(path.relative_to(REPOSITORY / "tests").parts) > 1
    }

    assert directories <= known
