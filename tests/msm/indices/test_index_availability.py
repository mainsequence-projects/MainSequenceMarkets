from __future__ import annotations

import datetime
import uuid

import pytest
from pydantic import ValidationError

from msm.analytics.indices import IndexFormulaDefinition
from msm.api.indices import Index
from msm.services.indices import (
    IndexDatasetAccess,
    IndexDatasetDescriptor,
    IndexListRequest,
)
from msm.services.indices import availability, catalog


def _index() -> Index:
    return Index(
        uid=uuid.uuid4(),
        unique_identifier="MX-TIIE",
        index_type="interest_rate",
        display_name="TIIE",
        calculation_method="custom",
        value_format="decimal",
    )


def _dataset(*, cadence: str = "1d") -> IndexDatasetDescriptor:
    return IndexDatasetDescriptor(
        meta_table_uid=str(uuid.uuid4()),
        identifier=f"IndexValuesTS.{cadence}",
        namespace="mainsequence.markets",
        cadence=cadence,
        physical_table_name=f"index_values_{cadence}",
        time_index_name="time_index",
        index_names=("time_index", "index_identifier"),
        columns=("time_index", "index_identifier", "value"),
        foreign_keys=(),
        storage_kind="canonical_index_values",
        discovery_source="core_model",
        access=IndexDatasetAccess(can_view=True, can_edit=False),
    )


def test_dataset_states_distinguish_populated_empty_and_unavailable(monkeypatch) -> None:
    index = _index()
    datasets = (_dataset(cadence="1d"), _dataset(cadence="1h"), _dataset(cadence="1m"))
    now = datetime.datetime.now(datetime.UTC)
    rows = [
        {
            "index_uid": index.uid,
            "meta_table_uid": datasets[0].meta_table_uid,
            "population_state": "populated",
            "row_count": 5,
            "earliest_time_index": now,
            "latest_time_index": now,
            "reconciled_at": now,
        },
        {
            "index_uid": index.uid,
            "meta_table_uid": datasets[1].meta_table_uid,
            "population_state": "compatible_empty",
            "row_count": 0,
            "earliest_time_index": None,
            "latest_time_index": None,
            "reconciled_at": now,
        },
        {
            "index_uid": index.uid,
            "meta_table_uid": datasets[2].meta_table_uid,
            "population_state": "unavailable",
            "row_count": None,
            "earliest_time_index": None,
            "latest_time_index": None,
            "reconciled_at": now,
            "error_code": "PermissionError",
            "error_message": "not visible",
        },
    ]
    monkeypatch.setattr(catalog, "discover_canonical_datasets", lambda **_kwargs: datasets)
    monkeypatch.setattr(availability, "search_model", lambda *_args, **_kwargs: rows)

    default = availability.list_dataset_states(object(), index=index)
    with_empty = availability.list_dataset_states(object(), index=index, include_empty=True)

    assert [item.population_state for item in default] == ["populated", "unavailable"]
    assert {item.population_state for item in with_empty} == {
        "populated",
        "compatible_empty",
        "unavailable",
    }
    assert next(item for item in default if item.population_state == "unavailable").error == (
        "PermissionError: not visible"
    )


def test_catalog_availability_filter_uses_exists_without_value_table_scan(monkeypatch) -> None:
    statements = []
    results = iter([[{"count": 0}], []])
    monkeypatch.setattr(
        catalog,
        "compile_markets_statement",
        lambda statement, **_kwargs: statements.append(statement) or statement,
    )
    monkeypatch.setattr(
        catalog,
        "execute_markets_operation",
        lambda _operation, **_kwargs: next(results),
    )

    catalog.list_indexes(
        object(),
        IndexListRequest(has_canonical_values=True, cadence="1d"),
    )

    sql = "\n".join(str(statement) for statement in statements)
    assert "ms_markets__indexdatasetavailability" in sql
    assert "EXISTS" in sql
    assert "population_state" in sql
    assert "DISTINCT" not in sql
    assert "100000" not in sql


def test_index_list_contract_rejects_removed_provider_filter_and_order() -> None:
    with pytest.raises(ValidationError, match="provider"):
        IndexListRequest(provider="example")

    with pytest.raises(ValidationError, match="order"):
        IndexListRequest(order="provider")


def test_reconciliation_writes_exact_population_state(monkeypatch) -> None:
    index = _index()
    dataset = _dataset()
    calls = iter(
        [
            [index.model_dump(mode="python")],
            [
                {
                    "index_identifier": index.unique_identifier,
                    "row_count": 2,
                    "earliest_time_index": datetime.datetime(2025, 1, 1, tzinfo=datetime.UTC),
                    "latest_time_index": datetime.datetime(2025, 1, 2, tzinfo=datetime.UTC),
                }
            ],
        ]
    )
    monkeypatch.setattr(catalog, "discover_canonical_datasets", lambda **_kwargs: (dataset,))
    monkeypatch.setattr(
        catalog,
        "_dataset_model_and_handle",
        lambda *_args, **_kwargs: (type("Model", (), {})(), object()),
    )
    model = type(
        "ValueModel",
        (),
        {
            "time_index": catalog.IndexTable.uid,
            "index_identifier": catalog.IndexTable.unique_identifier,
        },
    )
    monkeypatch.setattr(
        catalog,
        "_dataset_model_and_handle",
        lambda *_args, **_kwargs: (model, object()),
    )
    monkeypatch.setattr(
        availability, "compile_markets_statement", lambda statement, **_kwargs: statement
    )
    monkeypatch.setattr(
        availability,
        "execute_markets_operation",
        lambda _operation, **_kwargs: next(calls),
    )
    written = []
    monkeypatch.setattr(
        availability,
        "upsert_model",
        lambda _context, **kwargs: written.append(kwargs["values"]) or {"row": kwargs["values"]},
    )

    result = availability.reconcile_index_dataset_availability(object(), index_uids=(index.uid,))

    assert result.states[0].population_state == "populated"
    assert result.states[0].row_count == 2
    assert written[0]["meta_table_uid"] == dataset.meta_table_uid


def test_formula_listing_groups_input_counts_once(monkeypatch) -> None:
    index_uid = uuid.uuid4()
    definitions = [
        IndexFormulaDefinition(
            uid=uuid.uuid4(),
            index_uid=index_uid,
            version=version,
            status="draft",
            valid_from=datetime.datetime(2025, version, 1, tzinfo=datetime.UTC),
            formula='asset["BOND"].price',
            definition_hash=str(version) * 64,
        ).model_dump(mode="python")
        for version in (1, 2)
    ]
    monkeypatch.setattr(catalog, "search_model", lambda *_args, **_kwargs: definitions)
    compiled = []
    monkeypatch.setattr(
        catalog,
        "compile_markets_statement",
        lambda statement, **_kwargs: compiled.append(statement) or statement,
    )
    monkeypatch.setattr(
        catalog,
        "execute_markets_operation",
        lambda _operation, **_kwargs: [
            {"definition_uid": definitions[0]["uid"], "input_count": 2},
            {"definition_uid": definitions[1]["uid"], "input_count": 3},
        ],
    )

    summaries = catalog.list_formulas(object(), index_uid=index_uid)

    assert len(compiled) == 1
    assert [item.input_count for item in summaries] == [3, 2]


def test_index_type_ordering_is_part_of_the_paginated_query(monkeypatch) -> None:
    captured = []
    type_uid = uuid.uuid4()
    results = iter(
        [
            [{"count": 1}],
            [
                {
                    "uid": type_uid,
                    "index_type": "derived",
                    "display_name": "Derived",
                    "description": None,
                    "metadata_json": None,
                }
            ],
        ]
    )
    monkeypatch.setattr(
        catalog,
        "compile_markets_statement",
        lambda statement, **_kwargs: captured.append(statement) or statement,
    )
    monkeypatch.setattr(
        catalog,
        "execute_markets_operation",
        lambda _operation, **_kwargs: next(results),
    )

    count, rows = catalog.list_index_types(object(), limit=1, offset=0)

    page_sql = str(captured[1])
    assert count == 1
    assert rows[0].uid == type_uid
    assert "ORDER BY" in page_sql
    assert "LIMIT" in page_sql
    assert page_sql.index("ORDER BY") < page_sql.index("LIMIT")
