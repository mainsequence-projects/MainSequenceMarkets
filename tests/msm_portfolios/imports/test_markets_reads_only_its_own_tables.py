"""Markets reads and writes only its own tables (ADR 0060, decisions 1 and 11).

The Markets API (``apps/v1``) and the portfolio library's services, row classes,
repositories and recipes reach a table only through one of ms-markets' own model
classes, which compile SQL against the table its migrations create. None of them
resolves a MetaTable by a uid, identifier or catalog lookup, or runs a query on a table
it found that way. The engine nodes and the operator commands, which run in a producer
or with an operator's own access, are outside this rule; so are the Index dataset,
formula-source, pricing market-data and related-table reads that ADR 0060 leaves
undecided, which live in other packages.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CHECKED = (
    ROOT / "apps" / "v1",
    ROOT / "src" / "msm_portfolios" / "services",
    ROOT / "src" / "msm_portfolios" / "api",
    ROOT / "src" / "msm_portfolios" / "repositories",
    ROOT / "src" / "msm_portfolios" / "recipes.py",
)
TABLE_HANDLES = {"MetaTable", "TimeIndexMetaTable", "TimeIndexTableRef"}
RESOLVERS = {
    "get_by_uid",
    "get_by_identifier",
    "filter",
    "filter_by_body",
    "from_uid",
    "from_meta_table",
}
QUERIES = {"run_query"}


def _python_files() -> list[Path]:
    files: list[Path] = []
    for path in CHECKED:
        files.extend([path] if path.is_file() else sorted(path.rglob("*.py")))
    return files


def _violations(path: Path) -> list[str]:
    found: list[str] = []
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attribute = node.func.attr
        owner = node.func.value
        owner_name = owner.id if isinstance(owner, ast.Name) else None
        if attribute in RESOLVERS and owner_name in TABLE_HANDLES:
            found.append(f"{path.relative_to(ROOT)}:{node.lineno} {owner_name}.{attribute}")
        elif attribute in QUERIES:
            found.append(f"{path.relative_to(ROOT)}:{node.lineno} .{attribute}")
    return found


def test_the_checked_code_exists() -> None:
    assert all(path.exists() for path in CHECKED)
    assert len(_python_files()) > 50


def test_no_api_or_library_service_resolves_a_table_by_uid_name_or_catalog() -> None:
    violations = [item for path in _python_files() for item in _violations(path)]

    assert violations == [], (
        "Markets reads and writes only its own tables (ADR 0060): resolve a table through "
        "one of ms-markets' own model classes, never by a uid, name or catalog lookup. "
        + "; ".join(violations)
    )


def test_the_check_finds_a_table_resolved_by_uid(tmp_path) -> None:
    sample = tmp_path / "sample.py"
    sample.write_text(
        "from metatables import TimeIndexTableRef\n"
        "def read(uid):\n"
        "    return TimeIndexTableRef.from_uid(uid).get_df_between_dates()\n"
    )
    global ROOT
    original = ROOT
    try:
        ROOT = tmp_path
        assert _violations(sample) == ["sample.py:3 TimeIndexTableRef.from_uid"]
    finally:
        ROOT = original
