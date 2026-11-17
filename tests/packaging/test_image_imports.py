"""The API image installs requirements.txt only, so everything it can import must be there.

CI installs every extra, so a route that imports an extra's package passes every test and
fails only in the image (issue 81). This walks the first-party modules the API and the
migration Job can reach from their entrypoints, following imports inside functions too, and
checks that every third-party package they import is pinned in requirements.txt.
"""

from __future__ import annotations

import ast
import importlib.metadata
import re
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = (REPOSITORY_ROOT / "src", REPOSITORY_ROOT)
ENTRYPOINTS = ("api.main", "jobs.migrate_markets")
FIRST_PARTY = frozenset(
    {"api", "apps", "jobs", "msm", "msm_cli", "msm_migrations", "msm_portfolios", "msm_pricing"}
)
PIN = re.compile(r"^([A-Za-z0-9_.-]+)==")


def _canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _module_path(module: str) -> Path | None:
    parts = module.split(".")
    for root in SOURCE_ROOTS:
        package = root.joinpath(*parts, "__init__.py")
        if package.is_file():
            return package
        source = root.joinpath(*parts).with_suffix(".py")
        if source.is_file():
            return source
    return None


def _is_type_checking(node: ast.If) -> bool:
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _imports(module: str, path: Path) -> set[str]:
    """Every module ``module`` imports, at any depth, outside ``if TYPE_CHECKING:``."""

    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.If) and _is_type_checking(node):
            for child in node.orelse:
                visit(child)
            return
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - node.level + 1]
                target = ".".join([*base, node.module] if node.module else base)
            else:
                target = node.module or ""
            found.add(target)
            # ``from package import submodule`` imports the submodule.
            found.update(f"{target}.{alias.name}" for alias in node.names)
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    return found


def _reachable_third_party_imports() -> dict[str, set[str]]:
    """Third-party top-level names imported by reachable first-party modules, by module."""

    pending = list(ENTRYPOINTS)
    seen: set[str] = set()
    third_party: dict[str, set[str]] = {}
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        path = _module_path(module)
        if path is None:
            continue
        for imported in _imports(module, path):
            top = imported.split(".")[0]
            if top in FIRST_PARTY:
                parts = imported.split(".")
                # Importing a module imports every package above it.
                pending.extend(".".join(parts[:depth]) for depth in range(1, len(parts) + 1))
            elif top and top not in sys.stdlib_module_names and top != "__future__":
                third_party.setdefault(top, set()).add(module)
    assert "msm.api.calendars.core" in seen, "the walk no longer reaches the calendar routes"
    return third_party


def test_every_package_the_image_can_import_is_in_requirements():
    pinned = {
        _canonical(match[1])
        for line in (REPOSITORY_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if (match := PIN.match(line))
    }
    distributions = importlib.metadata.packages_distributions()

    missing = {}
    for name, modules in sorted(_reachable_third_party_imports().items()):
        provided_by = {_canonical(dist) for dist in distributions.get(name, [])}
        if not provided_by & pinned:
            missing[name] = sorted(modules)

    assert missing == {}
