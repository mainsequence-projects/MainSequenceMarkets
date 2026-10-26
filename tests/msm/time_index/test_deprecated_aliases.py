"""The pre-3.0 import paths and class names stay usable through 3.x (ADR 0048)."""

from __future__ import annotations

import importlib
import pkgutil
import sys
import warnings
from collections.abc import Iterator

import pytest

import metatables.updaters.configuration as update_configuration
from msm._deprecated_imports import RENAMED_CLASS_NAMES
from msm.identity import PRE_RENAME_MODULES, pre_rename_class_path


def _module_pairs() -> Iterator[tuple[str, str]]:
    """Yield ``(pre-3.0 module, current module)`` for every moved module."""

    for current_root, previous_root in PRE_RENAME_MODULES:
        current = importlib.import_module(current_root)
        yield previous_root, current_root
        if hasattr(current, "__path__"):
            for module in pkgutil.walk_packages(current.__path__, prefix=f"{current_root}."):
                yield previous_root + module.name[len(current_root) :], module.name


MODULE_PAIRS = sorted(_module_pairs())


def _import_fresh(name: str):
    sys.modules.pop(name, None)
    return importlib.import_module(name)


def _quietly_import(name: str):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return importlib.import_module(name)


def _renamed_classes() -> Iterator[tuple[str, str, type]]:
    """Yield ``(pre-3.0 module, pre-3.0 name, current class)`` for every renamed class."""

    for _previous_root, current_root in MODULE_PAIRS:
        module = importlib.import_module(current_root)
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and value.__module__ == current_root
                and value.__qualname__ in RENAMED_CLASS_NAMES.values()
            ):
                previous_module, previous_name = pre_rename_class_path(
                    value.__module__, value.__qualname__
                )
                yield previous_module, previous_name, value


RENAMED_CLASSES = sorted(set(_renamed_classes()), key=lambda item: (item[0], item[1]))


def test_every_renamed_class_has_an_alias() -> None:
    assert sorted(name for _module, name, _cls in RENAMED_CLASSES) == sorted(RENAMED_CLASS_NAMES)


@pytest.mark.parametrize(("previous", "current"), MODULE_PAIRS)
def test_pre_3_0_module_path_aliases_its_replacement(previous: str, current: str) -> None:
    replacement = importlib.import_module(current)

    with pytest.warns(DeprecationWarning, match=f"{previous} is deprecated; use {current}"):
        alias = _import_fresh(previous)

    public_names = getattr(replacement, "__all__", [n for n in vars(replacement) if n[0] != "_"])
    for name in public_names:
        assert getattr(alias, name) is getattr(replacement, name)


@pytest.mark.parametrize(("module_name", "previous_name", "current"), RENAMED_CLASSES)
def test_pre_3_0_class_name_resolves_to_the_renamed_class(
    module_name: str, previous_name: str, current: type
) -> None:
    alias = _quietly_import(module_name)

    with pytest.warns(DeprecationWarning, match=f"{previous_name} is deprecated"):
        assert getattr(alias, previous_name) is current


def test_pre_3_0_top_level_portfolio_names_resolve() -> None:
    import msm_portfolios

    with pytest.warns(DeprecationWarning, match="msm_portfolios.PortfoliosDataNode"):
        assert msm_portfolios.PortfoliosDataNode is msm_portfolios.PortfoliosUpdater


def test_stored_pre_3_0_configuration_paths_rebuild() -> None:
    from msm_pricing.time_index import IndexFixingConfiguration

    serialized = update_configuration.serialize_argument(
        IndexFixingConfiguration(index_unique_identifiers=["PINNED_INDEX"])
    )
    serialized["pydantic_model_import_path"]["module"] = "msm_pricing.data_nodes.index_fixings"

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        rebuilt = update_configuration.ConfigRebuilder().rebuild(serialized)

    assert isinstance(rebuilt, IndexFixingConfiguration)
    assert rebuilt.index_unique_identifiers == ["PINNED_INDEX"]


def test_subclassing_a_pre_3_0_name_subclasses_the_renamed_class() -> None:
    from msm.time_index.assets import AssetIndexedUpdater

    previous = _quietly_import("msm.data_nodes.assets")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        base = previous.AssetIndexedDataNode

    class ApplicationUpdater(base):
        pass

    assert issubclass(ApplicationUpdater, AssetIndexedUpdater)


def test_star_import_from_a_pre_3_0_path_exports_the_current_names() -> None:
    namespace: dict[str, object] = {}

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        exec("from msm_pricing.data_nodes import *", namespace)

    from msm_pricing.time_index import DiscountCurvesUpdater

    assert namespace["DiscountCurvesUpdater"] is DiscountCurvesUpdater


@pytest.mark.parametrize(("previous", "current"), MODULE_PAIRS)
def test_from_import_of_a_name_through_a_pre_3_0_module_path(previous: str, current: str) -> None:
    """``from <pre-3.0 module> import <name>`` works for modules and packages alike.

    The import system probes ``__path__`` on the alias for every from-import; an
    alias of a plain module must answer AttributeError instead of treating the
    dunder as a submodule, which recursed forever before.
    """

    target = importlib.import_module(current)
    names = [name for name in getattr(target, "__all__", ()) if hasattr(target, name)]
    if not names:
        pytest.skip(f"{current} exports no names")
    namespace: dict[str, object] = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        exec(f"from {previous} import {names[0]}", namespace)
        alias = importlib.import_module(previous)
    assert namespace[names[0]] is getattr(target, names[0])
    assert hasattr(alias, "__path__") is hasattr(target, "__path__")
    with pytest.raises(AttributeError):
        getattr(alias, "__no_such_dunder__")
