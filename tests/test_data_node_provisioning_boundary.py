from __future__ import annotations

from pathlib import Path


PROHIBITED_PROVISIONING_MARKERS = (
    "DataNodeStorage.initialize_account_holdings_source_table",
    "DataNodeStorage.initialize_virtual_fund_holdings_source_table",
    "DataNodeStorage.initialize_portfolio_storage_source_tables",
    "lookup_index",
    "lookup-index",
    "table_search_document",
    "search_document",
    "search-document",
    "refresh-table-search",
    "refresh_table_search",
)


def test_msm_has_no_domain_specific_datanode_provisioning_hooks() -> None:
    src_root = Path(__file__).resolve().parents[1] / "src" / "msm"
    offenders: list[str] = []

    for path in src_root.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text()
        for marker in PROHIBITED_PROVISIONING_MARKERS:
            if marker in text:
                offenders.append(f"{path.relative_to(src_root)}: {marker}")

    assert offenders == []
