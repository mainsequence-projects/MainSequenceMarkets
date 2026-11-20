"""Every table a row operation names resolves as a deployed runtime resolves it (#103).

``msm.bootstrap.resolve_runtime`` resolves the models a row operation names with
``resolve_markets_meta_table_models`` before it answers. A table class always resolves;
a name resolves only when it names one of ``msm``'s own tables. A row class in another
package that names its tables passes every test that stubs the runtime and fails in a
deployed API with "Unknown markets MetaTable model".

The tests' stand-in for the runtime (``tests/support/markets_runtime.py``) resolves with
the same resolver, but only for the operations a test reaches. This test resolves every
row class's ``__required_tables__`` in ``msm``, ``msm_portfolios`` and ``msm_pricing``,
and every ``resolve_runtime(models=...)`` in their source that names its models there.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

from msm.models.registration import resolve_markets_meta_table_models

SOURCE = Path(__file__).resolve().parents[2] / "src"
PACKAGES = ("msm", "msm_portfolios", "msm_pricing")
SERIES = {
    "msm_portfolios.api.series.SignalWeightsSeries",
    "msm_portfolios.api.series.PortfolioWeightsSeries",
    "msm_portfolios.api.series.PortfolioValuesSeries",
}


def _modules() -> Iterator[tuple[str, str, ast.Module]]:
    """``(module, package, tree)`` for each source file that names tables to resolve."""

    for package in PACKAGES:
        for path in sorted((SOURCE / package).rglob("*.py")):
            text = path.read_text()
            if "__required_tables__" not in text and "resolve_runtime(" not in text:
                continue
            parts = path.relative_to(SOURCE).with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
                parent = ".".join(parts)
            else:
                parent = ".".join(parts[:-1])
            yield ".".join(parts), parent, ast.parse(text, filename=str(path))


def _assigns_required_tables(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Assign):
        return any(
            isinstance(target, ast.Name) and target.id == "__required_tables__"
            for target in statement.targets
        )
    return (
        isinstance(statement, ast.AnnAssign)
        and statement.value is not None
        and isinstance(statement.target, ast.Name)
        and statement.target.id == "__required_tables__"
    )


def _row_classes(module: ModuleType, tree: ast.Module) -> Iterator[tuple[str, Any]]:
    """Each class, at any nesting, that assigns ``__required_tables__``, with its tables."""

    def visit(body: list[ast.stmt], owner: Any, prefix: str) -> Iterator[tuple[str, Any]]:
        for node in body:
            if not isinstance(node, ast.ClassDef):
                continue
            row_class = getattr(owner, node.name)
            if any(_assigns_required_tables(statement) for statement in node.body):
                yield f"{prefix}{node.name}", row_class.__required_tables__
            yield from visit(node.body, row_class, f"{prefix}{node.name}.")

    yield from visit(tree.body, module, f"{module.__name__}.")


def _imported_names(tree: ast.Module, package: str) -> dict[str, set[tuple[str, str]]]:
    """Every name a ``from ... import`` binds anywhere in the module, function bodies too."""

    names: dict[str, set[tuple[str, str]]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        source = node.module or ""
        if node.level:
            source = importlib.util.resolve_name("." * node.level + source, package)
        for alias in node.names:
            names.setdefault(alias.asname or alias.name, set()).add((source, alias.name))
    return names


def _named_value(name: str, module: ModuleType, imported: dict[str, set[tuple[str, str]]]):
    if hasattr(module, name):
        return getattr(module, name)
    (source, attribute), *others = sorted(imported.get(name, ()))
    assert not others, f"{module.__name__} imports {name!r} from more than one place."
    return getattr(importlib.import_module(source), attribute)


def _runtime_calls(module: ModuleType, tree: ast.Module, package: str):
    """Each ``resolve_runtime(models=...)`` whose models are written out or a module constant."""

    imported = _imported_names(tree, package)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", None)
        if name != "resolve_runtime":
            continue
        models = next((keyword.value for keyword in node.keywords if keyword.arg == "models"), None)
        label = f"{module.__name__}:{node.lineno}"
        if isinstance(models, ast.List | ast.Tuple):
            yield label, [
                element.value
                if isinstance(element, ast.Constant)
                else _named_value(element.id, module, imported)
                for element in models.elts
                if isinstance(element, ast.Constant | ast.Name)
            ]
        elif isinstance(models, ast.Name) and hasattr(module, models.id):
            yield label, getattr(module, models.id)


def test_every_table_a_row_operation_names_resolves() -> None:
    row_classes: dict[str, Any] = {}
    runtime_calls: dict[str, Any] = {}
    for module_name, package, tree in _modules():
        module = importlib.import_module(module_name)
        row_classes.update(_row_classes(module, tree))
        runtime_calls.update(_runtime_calls(module, tree, package))

    unresolved = []
    for label, models in {**row_classes, **runtime_calls}.items():
        try:
            resolve_markets_meta_table_models(models)
        except ValueError as error:
            unresolved.append(f"{label}: {error}")

    assert SERIES <= row_classes.keys()
    assert {label.split(".")[0] for label in row_classes} == set(PACKAGES)
    assert {label.split(".")[0] for label in runtime_calls} >= {"msm", "msm_portfolios"}
    assert unresolved == []
