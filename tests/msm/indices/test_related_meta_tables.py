from __future__ import annotations

import uuid
from types import SimpleNamespace

from msm.services import related_meta_tables as service


def _column(name: str, data_type: str, *, primary_key: bool = False):
    return SimpleNamespace(name=name, data_type=data_type, primary_key=primary_key)


def test_related_meta_tables_require_authoritative_asset_foreign_key(monkeypatch) -> None:
    target_uid = uuid.uuid4()
    valid = SimpleNamespace(
        uid=uuid.uuid4(),
        identifier="BondYieldTS.1d",
        physical_table_name="bond_yield_t_1d",
        description="Bond yields",
        time_indexed=True,
        columns=[
            _column("time_index", "datetime64[ns, UTC]", primary_key=True),
            _column("asset_identifier", "string", primary_key=True),
            _column("yield", "float64"),
        ],
        foreign_keys=[
            SimpleNamespace(
                source_columns=["asset_identifier"],
                target_columns=["unique_identifier"],
                target_table_uid=target_uid,
                target_table_physical_table_name="ms_markets__asset",
                on_delete="RESTRICT",
            )
        ],
    )
    misleading = SimpleNamespace(
        uid=uuid.uuid4(),
        identifier="MisleadingTS.1d",
        physical_table_name="misleading_t_1d",
        description=None,
        time_indexed=True,
        columns=valid.columns,
        foreign_keys=[],
    )
    monkeypatch.setattr(service, "_all_meta_tables", lambda: (valid, misleading))
    monkeypatch.setattr(service, "_bound_uid", lambda _model: str(target_uid))

    result = service.list_reference_meta_tables(reference_type="asset")

    assert [item.identifier for item in result] == ["BondYieldTS.1d"]
    assert result[0].join_column == "asset_identifier"


def test_related_meta_table_catalog_is_paginated_without_truncation(monkeypatch) -> None:
    first_page = [SimpleNamespace(uid=uuid.uuid4()) for _ in range(500)]
    final_row = SimpleNamespace(uid=uuid.uuid4())
    calls = []

    def fake_filter_by_body(*, limit, offset):
        calls.append((limit, offset))
        return first_page if offset == 0 else [final_row]

    monkeypatch.setattr(service.MetaTable, "filter_by_body", fake_filter_by_body)

    result = service._all_meta_tables()

    assert len(result) == 501
    assert result[-1] is final_row
    assert calls == [(500, 0), (500, 500)]
