from __future__ import annotations

import uuid

import pytest

from msm.api.indices import Index
from msm.services.indices import RelatedMetaTable
from msm.services.indices.delete_impact import _normalize_relationship, get_index_delete_impact


def _relationship(*, on_delete: str, count: int | None, authoritative: bool = True):
    return RelatedMetaTable(
        key="dependency",
        label="Dependency",
        owning_package="msm",
        storage_kind="related_reference_table",
        identifier="DependencyTable",
        relationship_type="direct" if authoritative else "registered_foreign_key",
        join_kind="uid",
        join_column="index_uid",
        on_delete=on_delete,
        authoritative=authoritative,
        discovery_source="core_model" if authoritative else "inferred",
        exploration_capability="count" if authoritative else "none",
        delete_capability="none",
        count=count,
    )


@pytest.mark.parametrize(
    ("on_delete", "count", "effect", "severity", "blocks"),
    [
        ("RESTRICT", 2, "blocks_delete", "blocking", True),
        ("RESTRICT", None, "blocks_delete", "warning", True),
        ("CASCADE", 2, "cascade_delete", "destructive", False),
        ("SET NULL", 2, "set_null", "mutating", False),
        ("UNKNOWN", 2, "informational", "warning", False),
        ("CASCADE", 0, "informational", "info", False),
    ],
)
def test_delete_impact_normalization(
    on_delete: str,
    count: int | None,
    effect: str,
    severity: str,
    blocks: bool,
) -> None:
    normalized = _normalize_relationship(_relationship(on_delete=on_delete, count=count))

    assert normalized.effect == effect
    assert normalized.severity == severity
    assert normalized.blocks_delete is blocks
    assert normalized.count is count
    assert normalized.count_accuracy == ("exact" if count is not None else "unavailable")


def test_inferred_relationship_is_normalized_to_supported_literals() -> None:
    normalized = _normalize_relationship(
        _relationship(on_delete="unknown", count=None, authoritative=False)
    )

    assert normalized.relationship_type == "indirect"
    assert normalized.on_delete == "UNKNOWN"
    assert normalized.effect == "informational"


def test_delete_impact_requests_unfiltered_relationships(monkeypatch) -> None:
    index = Index(
        uid=uuid.uuid4(),
        unique_identifier="MXN-TIIE-28D",
        index_type="interest_rate",
        display_name="MXN TIIE 28D",
        calculation_method="custom",
        value_format="decimal",
    )
    calls = []

    def fake_list_related_meta_tables(
        context,
        *,
        index,
        numeric,
        timestamped,
    ):
        calls.append((context, index.uid, numeric, timestamped))
        return ()

    monkeypatch.setattr(
        "msm.services.indices.delete_impact.list_related_meta_tables",
        fake_list_related_meta_tables,
    )
    context = object()

    impact = get_index_delete_impact(context, index=index)

    assert impact.can_delete is True
    assert calls == [(context, index.uid, False, False)]
