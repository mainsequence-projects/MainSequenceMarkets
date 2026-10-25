"""Import paths and class names renamed by ADR 0048, kept through ms-markets 3.x.

Each module under ``msm.data_nodes``, ``msm_portfolios.data_nodes``,
``msm_pricing.data_nodes`` and ``msm_portfolios.contrib.prices.data_nodes`` is an
alias of the module that replaced it. It re-exports the same objects, so
``isinstance`` checks, SQLAlchemy registration and stored ``{module, qualname}``
references keep working, and it warns once on import. Pre-3.0 class names resolve
to the renamed classes with a warning. ms-markets 4.0 removes these aliases; the
identity mapping in :mod:`msm.identity` stays.
"""

from __future__ import annotations

import importlib
import os
import sys
import warnings
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from msm.identity import PRE_RENAME_CLASS_NAMES

RENAMED_CLASS_NAMES: Mapping[str, str] = {
    previous: current for current, previous in PRE_RENAME_CLASS_NAMES.items()
}
"""Pre-3.0 class name to current class name."""

REMOVAL_RELEASE = "4.0"

# Report each warning at the first frame outside ms-markets and the import machinery.
_PACKAGES_ROOT = Path(__file__).resolve().parents[1]
_SKIPPED_FRAME_PREFIXES = (
    *(f"{_PACKAGES_ROOT / name}{os.sep}" for name in ("msm", "msm_portfolios", "msm_pricing")),
    "<frozen importlib",
)


def warn_renamed(old: str, new: str) -> None:
    """Warn that ``old`` was renamed to ``new`` and is removed in ms-markets 4.0."""

    warnings.warn(
        f"{old} is deprecated; use {new}. It is removed in ms-markets {REMOVAL_RELEASE} "
        "(ADR 0048).",
        DeprecationWarning,
        skip_file_prefixes=_SKIPPED_FRAME_PREFIXES,
    )


def alias_module(
    name: str,
    target: str,
) -> tuple[Callable[[str], Any], Callable[[], list[str]]]:
    """Make module ``name`` an alias of ``target`` and return its ``__getattr__``/``__dir__``."""

    warn_renamed(name, target)
    module = importlib.import_module(target)
    alias = sys.modules[name]
    alias.__all__ = list(getattr(module, "__all__", _public_names(module)))

    def __getattr__(attribute: str) -> Any:
        current = RENAMED_CLASS_NAMES.get(attribute, attribute)
        try:
            value = getattr(module, current)
        except AttributeError:
            value = _submodule(name, attribute)
            if value is None:
                raise AttributeError(f"module {name!r} has no attribute {attribute!r}") from None
        if current != attribute:
            warn_renamed(f"{name}.{attribute}", f"{target}.{current}")
        return value

    def __dir__() -> list[str]:
        renamed = [old for old, new in RENAMED_CLASS_NAMES.items() if hasattr(module, new)]
        return sorted({*dir(module), *renamed})

    return __getattr__, __dir__


def _public_names(module: ModuleType) -> list[str]:
    return [name for name in vars(module) if not name.startswith("_")]


def _submodule(name: str, attribute: str) -> ModuleType | None:
    try:
        return importlib.import_module(f"{name}.{attribute}")
    except ModuleNotFoundError as exc:
        if exc.name == f"{name}.{attribute}":
            return None
        raise
