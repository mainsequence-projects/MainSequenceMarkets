"""A provider-owned discount-curve storage bound to a pricing market-data set (ADR 0047).

Shared by the curve-delete tests of the row API and of the FastAPI route. Only
the MetaTables boundary is faked: the Markets core ``DiscountCurvesStorage``
table, the provider's instance of it and the market-data-set bindings that name
them. Scope resolution, ownership checks, row counts and value cleanup run the
real curve-delete code.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from metatables import TimeIndexMetaTable, sqlalchemy_naming_convention
from msm.storage_instances import configured_time_index_instance
from msm_pricing.api.market_data_bindings import PricingMarketDataSetBinding
from msm_pricing.settings import PRICING_CONCEPT_DISCOUNT_CURVES
from msm_pricing.time_index.curves.storage import DiscountCurvesStorage

CURVE_IDENTIFIER = "USD-SOFR-DISCOUNT"
CORE_TABLE_UID = "4e4e4e4e-0000-4000-8000-000000000005"
PROVIDER_TABLE_UID = "5f5f5f5f-0000-4000-8000-000000000006"


class ProviderBase(DeclarativeBase):
    metadata = MetaData(naming_convention=sqlalchemy_naming_convention())


PROVIDER_DISCOUNT_CURVES = configured_time_index_instance(
    DiscountCurvesStorage,
    instance_key="main",
    namespace="example-provider",
    storage_app="example_provider",
    base=ProviderBase,
)

_COUNT_SQL = re.compile(
    r"SELECT COUNT\(\*\) AS count FROM (?P<table>.+) "
    r"WHERE \"curve_identifier\" = '(?P<value>(?:[^']|'')*)'"
)


class StorageTable:
    """The MetaTables ``TimeIndexMetaTable`` of one storage class, holding rows in memory.

    Every statement sent to the table is recorded in ``statements``.
    """

    def __init__(self, storage: type[Any], *, uid: str, curve_identifiers: Iterable[str]) -> None:
        table = storage.__table__
        self.uid = uuid.UUID(uid)
        self.identifier = storage.metatable_identifier()
        self.physical_schema = table.schema
        self.physical_table_name = table.name
        self.columns = [SimpleNamespace(name=column.name) for column in table.columns]
        self.table_index_names = list(storage.__index_names__)
        self.rows = [{"curve_identifier": value} for value in curve_identifiers]
        self.statements: list[tuple[Any, ...]] = []

    def run_query(self, sql: str, *, timeout: int | None = None) -> dict[str, Any]:
        self.statements.append(("run_query", sql))
        match = _COUNT_SQL.fullmatch(sql)
        assert match is not None, f"unexpected statement: {sql}"
        assert match["table"] == f'"{self.physical_table_name}"', sql
        curve_identifier = match["value"].replace("''", "'")
        count = sum(1 for row in self.rows if row["curve_identifier"] == curve_identifier)
        return {"rows": [{"count": count}]}

    def delete_after_date(
        self,
        after_date: Any,
        *,
        dimension_filters: dict[str, list[Any]],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        self.statements.append(("delete_after_date", after_date, dimension_filters))
        removed = set(dimension_filters["curve_identifier"])
        kept = [row for row in self.rows if row["curve_identifier"] not in removed]
        deleted_count = len(self.rows) - len(kept)
        self.rows = kept
        return {"deleted_count": deleted_count, "table_empty": not kept}

    def writes(self) -> list[tuple[Any, ...]]:
        """Recorded statements other than ``run_query``, which accepts only the row count."""

        return [statement for statement in self.statements if statement[0] != "run_query"]


def bind_discount_curve_storages(
    monkeypatch,
    *,
    core_curve_identifiers: Iterable[str],
    provider_curve_identifiers: Iterable[str],
) -> SimpleNamespace:
    """Attach the core storage and bind it and a provider instance to two market-data sets."""

    core = StorageTable(
        DiscountCurvesStorage,
        uid=CORE_TABLE_UID,
        curve_identifiers=core_curve_identifiers,
    )
    provider = StorageTable(
        PROVIDER_DISCOUNT_CURVES,
        uid=PROVIDER_TABLE_UID,
        curve_identifiers=provider_curve_identifiers,
    )
    bindings = [
        PricingMarketDataSetBinding(
            uid=uuid.uuid4(),
            market_data_set_uid=uuid.uuid4(),
            concept_key=PRICING_CONCEPT_DISCOUNT_CURVES,
            storage_table_uid=uuid.UUID(table_uid),
            storage_table_identifier=identifier,
        )
        for table_uid, identifier in (
            (CORE_TABLE_UID, core.identifier),
            (PROVIDER_TABLE_UID, provider.identifier),
        )
    ]

    def filter_bindings(cls, *, limit: int = 500, **filters: Any):
        assert filters == {"concept_key": PRICING_CONCEPT_DISCOUNT_CURVES}
        return bindings

    def get_by_uid(cls, uid: str, timeout: int | None = None, **filters: Any):
        tables = {PROVIDER_TABLE_UID: provider}
        if str(uid) not in tables:
            raise LookupError(f"No TimeIndexMetaTable with uid={uid}.")
        return tables[str(uid)]

    monkeypatch.setattr(
        DiscountCurvesStorage,
        "get_time_index_meta_table",
        classmethod(lambda cls: core),
    )
    monkeypatch.setattr(PricingMarketDataSetBinding, "filter", classmethod(filter_bindings))
    monkeypatch.setattr(TimeIndexMetaTable, "get_by_uid", classmethod(get_by_uid))
    return SimpleNamespace(core=core, provider=provider, bindings=bindings)
