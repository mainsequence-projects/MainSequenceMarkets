"""``msm rename-preflight``: what a consumer changes and rotates for ADR 0048.

``scan`` finds pre-3.0 import paths, class names and UID field names in a source
tree, including ``getattr(obj, "<pre-3.0 field>", default)`` calls, which return
their default without an error since ms-markets 4.0 removed the pre-3.0 names.
``rotation`` reports which of a consumer's updaters got a new MetaTables
``update_hash`` and the pre-3.0 hash that names their old ``TimeIndexTableUpdate``.
``account-uids`` classifies the UIDs stored on accounts and account holdings sets
as storage tables or table updates.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

PRE_3_0_FIELD_NAMES = {
    "holdings_data_node_uid": "holdings_storage_table_uid",
    "source_data_node_uid": "source_storage_table_uid",
    "portfolio_weights_data_node_uid": "portfolio_weights_table_update_uid",
    "signal_weights_data_node_uid": "signal_weights_table_update_uid",
    "portfolio_data_node_uid": "portfolio_table_update_uid",
    "data_node_uids": "storage_table_uids",
    "data_node_uid": "storage_table_uid",
    "resolve_data_node_uid": "resolve_storage_table_uid",
    "direct_data_node_uid_for": "direct_storage_table_uid_for",
    "markets_data_node_identifier": "markets_identifier",
}
"""Pre-3.0 field, method and helper names and their 3.0 names."""

SCANNED_SUFFIXES = (".py", ".pyi", ".md")
SKIPPED_DIRECTORIES = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "site-packages", "build", "dist",
}


@dataclass(frozen=True)
class Finding:
    """One pre-3.0 name in a consumer source file."""

    path: str
    line: int
    kind: str
    old: str
    new: str


def scan(paths: Iterable[Path]) -> list[Finding]:
    """Return every pre-3.0 import path, class name and UID field name under ``paths``."""

    rules = _scan_rules()
    findings = []
    for path in _source_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern, replace in rules:
                for match in pattern.finditer(line):
                    findings.append(
                        Finding(str(path), number, kind, match.group(0), replace(match))
                    )
    return findings


def rotation(objects: Iterable[Any]) -> list[dict[str, Any]]:
    """Report the current and pre-3.0 ``update_hash`` of every updater reachable from objects."""

    from msm.identity import pre_rename_update_hash, reachable_updaters

    report = []
    for updater in reachable_updaters(objects):
        current = getattr(updater, "update_hash", None)
        if not current:
            continue
        previous = pre_rename_update_hash(updater)
        report.append(
            {
                "updater": f"{type(updater).__module__}:{type(updater).__qualname__}",
                "update_hash": current,
                "pre_3_0_update_hash": previous,
                "rotated": previous != current,
            }
        )
    return sorted(report, key=lambda item: (item["updater"], item["update_hash"]))


def load_objects(reference: str) -> list[Any]:
    """Call ``module:callable`` and return the objects it produces as a list."""

    module_name, _, attribute = reference.partition(":")
    if not module_name or not attribute:
        raise ValueError("Pass the objects as module:callable.")
    produced = getattr(importlib.import_module(module_name), attribute)()
    if isinstance(produced, (list, tuple, set, frozenset)):
        return list(produced)
    return [produced]


def classify_uid(uid: str) -> str:
    """Return whether ``uid`` names a TimeIndexMetaTable, a TimeIndexTableUpdate, or neither."""

    from metatables import TimeIndexMetaTable, TimeIndexTableUpdate

    if TimeIndexMetaTable.get_or_none(uid=uid) is not None:
        return "TimeIndexMetaTable"
    if TimeIndexTableUpdate.get_or_none(uid=uid) is not None:
        return "TimeIndexTableUpdate"
    return "unknown"


def account_uids(
    *,
    limit: int = 10_000,
    load_rows: Callable[[int], Iterable[tuple[str, str, Any]]] | None = None,
    classify: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Classify each stored account holdings and holdings-set source UID.

    Returns one entry per ``(table, column, classification)`` with its count and up
    to five example UIDs. ``load_rows`` yields ``(table, column, uid)`` and
    defaults to reading the attached Markets runtime; ``classify`` defaults to
    :func:`classify_uid`.
    """

    rows = (load_rows or _account_uid_rows)(limit)
    classify = classify or classify_uid
    classified: dict[str, str] = {}
    groups: dict[tuple[str, str, str], list[str]] = {}
    for table, column, uid in rows:
        if uid in (None, ""):
            continue
        uid = str(uid)
        if uid not in classified:
            classified[uid] = classify(uid)
        groups.setdefault((table, column, classified[uid]), []).append(uid)
    return [
        {
            "table": table,
            "column": column,
            "classification": classification,
            "count": len(uids),
            "examples": sorted(set(uids))[:5],
        }
        for (table, column, classification), uids in sorted(groups.items())
    ]


def as_dicts(findings: Iterable[Finding]) -> list[dict[str, Any]]:
    return [asdict(finding) for finding in findings]


def _scan_rules() -> list[tuple[str, re.Pattern[str], Callable[[re.Match[str]], str]]]:
    from msm.identity import PRE_RENAME_CLASS_NAMES, PRE_RENAME_MODULES

    rules: list[tuple[str, re.Pattern[str], Callable[[re.Match[str]], str]]] = []
    for current, previous in PRE_RENAME_MODULES:
        rules.append(
            (
                "import path",
                re.compile(rf"(?<![\w.]){re.escape(previous)}(?:\.\w+)*(?!\w)"),
                lambda match, current=current, previous=previous: current
                + match.group(0)[len(previous) :],
            )
        )
    for current, previous in sorted(PRE_RENAME_CLASS_NAMES.items(), key=lambda item: item[1]):
        rules.append(("class name", re.compile(rf"\b{previous}\b"), lambda _m, c=current: c))
    for previous, current in PRE_3_0_FIELD_NAMES.items():
        rules.append(
            (
                "silent default",
                re.compile(rf"""getattr\([^,()]+,\s*["']{previous}["']\s*,"""),
                lambda _m, c=current: f'getattr(..., "{c}") without a default',
            )
        )
        rules.append(("field name", re.compile(rf"\b{previous}\b"), lambda _m, c=current: c))
    # Keyword arguments carry no spaces around "="; an assignment to a data_node variable does.
    rules.append(("keyword", re.compile(r"\bdata_node=(?!=)"), lambda _m: "updater="))
    return rules


def _source_files(paths: Iterable[Path]) -> Iterator[Path]:
    for root in paths:
        root = Path(root)
        if root.is_file():
            if root.suffix in SCANNED_SUFFIXES:
                yield root
            continue
        for path in sorted(root.rglob("*")):
            if SKIPPED_DIRECTORIES.isdisjoint(path.parts) and path.suffix in SCANNED_SUFFIXES:
                if path.is_file():
                    yield path


def _account_uid_rows(limit: int) -> Iterator[tuple[str, str, Any]]:
    import msm
    from msm.api.accounts import Account, AccountHoldingsSet

    msm.start_engine(models=["Account", "AccountHoldingsSet"])
    for row in Account.filter(limit=limit):
        yield "Account", "holdings_storage_table_uid", row.holdings_storage_table_uid
    for row in AccountHoldingsSet.filter(limit=limit):
        yield "AccountHoldingsSet", "source_storage_table_uid", row.source_storage_table_uid
