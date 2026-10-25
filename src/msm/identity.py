"""Keep identities that ms-markets derives stable when updater classes move.

ms-markets derives three persisted identities from live updater and
configuration objects: ``signal_uid``, the portfolio configuration hash and the
rebalance strategy revision recorded on ledger events. Each hashes a serialized
payload that contains class import paths (``{"module": ..., "qualname": ...}``)
and, for nested updaters, their MetaTables ``update_hash``.

Moving or renaming a class changes both kinds of value. Before hashing, the
identity functions pass their payload through :func:`stable_identity_payload`.
It maps every moved class path back to the path it had before the move, and
replaces every nested updater's ``update_hash`` with the hash that updater had
under those paths. The mapping is permanent: removing an entry rotates every
identity that depends on it. MetaTables' own update records are not covered;
their ``update_hash`` follows the class.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Iterator, Mapping
from typing import Any

import metatables.updaters.configuration as update_configuration
from metatables import TimeIndexTableUpdater
from pydantic import BaseModel

PRE_RENAME_MODULES: tuple[tuple[str, str], ...] = (
    # ADR 0048: the DataNode packages moved to the time-index vocabulary in 3.0.0.
    ("msm_portfolios.contrib.prices.updaters", "msm_portfolios.contrib.prices.data_nodes"),
    ("msm_portfolios.time_index", "msm_portfolios.data_nodes"),
    ("msm_pricing.time_index", "msm_pricing.data_nodes"),
    ("msm.time_index", "msm.data_nodes"),
)
"""``(current module, pre-rename module)`` pairs; a pair also covers submodules."""

PRE_RENAME_CLASS_NAMES: Mapping[str, str] = {
    "AssetIndexedUpdater": "AssetIndexedDataNode",
    "AssetIndexedUpdaterConfiguration": "AssetIndexedDataNodeConfiguration",
    "AssetScopedPortfolioCanonicalUpdater": "AssetScopedPortfolioCanonicalDataNode",
    "AssetTimestampedUpdater": "AssetTimestampedDataNode",
    "AssetUpdaterConfiguration": "AssetDataNodeConfiguration",
    "CurveTimestampedUpdater": "CurveTimestampedDataNode",
    "CurveUpdaterConfiguration": "CurveDataNodeConfiguration",
    "DiscountCurvesUpdater": "DiscountCurvesNode",
    "ExecutionUpdater": "ExecutionDataNode",
    "ExecutionUpdaterConfiguration": "ExecutionDataNodeConfiguration",
    "FixingRatesUpdater": "FixingRatesNode",
    "FormulaIndexUpdater": "FormulaIndexDataNode",
    "FormulaIndexUpdaterConfiguration": "FormulaIndexDataNodeConfiguration",
    "HoldingsUpdater": "HoldingsDataNode",
    "HoldingsUpdaterConfiguration": "HoldingsDataNodeConfiguration",
    "IndexTimestampedUpdater": "IndexTimestampedDataNode",
    "IndexUpdaterConfiguration": "IndexDataNodeConfiguration",
    "IndexValuesUpdater": "IndexValuesDataNode",
    "PortfolioCanonicalUpdater": "PortfolioCanonicalDataNode",
    "PortfolioCanonicalUpdaterConfiguration": "PortfolioCanonicalDataNodeConfiguration",
    "PortfoliosUpdater": "PortfoliosDataNode",
    "StampedUpdater": "StampedDataNode",
    "StampedUpdaterConfiguration": "StampedDataNodeConfiguration",
    "TargetPositionsConfiguration": "TargetPositionsDataNodeConfiguration",
}
"""Pre-rename name of each class renamed inside a module of :data:`PRE_RENAME_MODULES`."""

_TABLE_UPDATE_KIND = "table_update"


def pre_rename_class_path(module: str, qualname: str) -> tuple[str, str]:
    """Return the ``(module, qualname)`` a class had before it moved or was renamed."""

    for current, previous in PRE_RENAME_MODULES:
        if module == current or module.startswith(f"{current}."):
            return (
                previous + module[len(current) :],
                PRE_RENAME_CLASS_NAMES.get(qualname, qualname),
            )
    return module, qualname


def pre_rename_update_hash(updater: TimeIndexTableUpdater) -> str:
    """Return the ``update_hash`` the updater had under its pre-rename class paths."""

    return _pre_rename_update_hash(updater, {})


def stable_identity_payload(payload: Any, *, sources: Iterable[Any] = ()) -> Any:
    """Return a copy of ``payload`` with pre-rename class paths and nested updater hashes.

    ``sources`` are the live objects the payload was serialized from. The
    updaters reachable from them supply the pre-rename ``update_hash`` of each
    nested updater that the payload references by hash; a referenced updater
    that is not reachable keeps its current hash.
    """

    memo: dict[int, str | None] = {}
    nested_hashes = {
        updater.update_hash: _pre_rename_update_hash(updater, memo)
        for updater in reachable_updaters(sources)
        if getattr(updater, "update_hash", None)
    }
    return _translate(payload, nested_hashes)


def _pre_rename_update_hash(updater: TimeIndexTableUpdater, memo: dict[int, str | None]) -> str:
    key = id(updater)
    if key in memo:
        # None marks an updater whose hash is being computed: a cycle keeps the current hash.
        return memo[key] or updater.update_hash
    memo[key] = None
    configuration = getattr(updater, "local_initial_configuration", None)
    if not isinstance(configuration, Mapping):
        memo[key] = updater.update_hash
        return updater.update_hash

    nested_hashes: dict[str, str] = {}
    for nested in reachable_updaters(vars(updater).values()):
        nested_hash = getattr(nested, "update_hash", None)
        if nested is not updater and nested_hash:
            nested_hashes[nested_hash] = _pre_rename_update_hash(nested, memo)
    translated = _translate(configuration, nested_hashes)
    if translated == configuration:
        result = updater.update_hash
    else:
        # MetaTables prefixes update_hash with the class name it hashed under.
        class_path = translated.get("table_updater_class_import_path") or {}
        qualname = class_path.get("qualname") or pre_rename_class_path(
            type(updater).__module__, type(updater).__qualname__
        )[1]
        result = update_configuration.create_config(
            updater_class_name=qualname.rsplit(".", 1)[-1],
            kwargs=copy.deepcopy(dict(translated)),
        ).update_hash
    memo[key] = result
    return result


def reachable_updaters(roots: Iterable[Any]) -> Iterator[TimeIndexTableUpdater]:
    """Yield every updater reachable from ``roots`` through attributes, fields and containers."""

    seen: set[int] = set()
    pending = list(roots)
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, TimeIndexTableUpdater):
            yield value
            pending.extend(vars(value).values())
        elif isinstance(value, BaseModel):
            pending.extend(vars(value).values())
        elif isinstance(value, Mapping):
            pending.extend(value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            pending.extend(value)


def _translate(value: Any, nested_hashes: Mapping[str, str]) -> Any:
    if isinstance(value, Mapping):
        translated = {key: _translate(item, nested_hashes) for key, item in value.items()}
        if isinstance(translated.get("module"), str) and isinstance(
            translated.get("qualname"), str
        ):
            translated["module"], translated["qualname"] = pre_rename_class_path(
                translated["module"], translated["qualname"]
            )
        if translated.get("kind") == _TABLE_UPDATE_KIND:
            update_hash = translated.get("update_hash")
            if update_hash in nested_hashes:
                translated["update_hash"] = nested_hashes[update_hash]
        return translated
    if isinstance(value, list):
        return [_translate(item, nested_hashes) for item in value]
    if isinstance(value, tuple):
        return tuple(_translate(item, nested_hashes) for item in value)
    return value


__all__ = [
    "PRE_RENAME_CLASS_NAMES",
    "PRE_RENAME_MODULES",
    "pre_rename_class_path",
    "pre_rename_update_hash",
    "reachable_updaters",
    "stable_identity_payload",
]
