"""An owner's instances of Markets time-index storages, declared as classes (ADR 0047, 0066).

``factory_tables.json`` is what the instance factories built at 48dda3dc, before ADR
0066 removed them: for each table its name, MetaTable identifiers, ``info``, contract
attributes, MetaTables' contract hash, the SHA-256 of its registration request (without
``authoring.table_model``, the class's import address, which is what changes) and its
PostgreSQL and SQLite DDL. The factory made a generic instance's foreign keys in the
order of a set, which differed between processes, so the pinned DDL lists a table's
constraint clauses sorted; their names and clauses are the ones it built.

The SQLite DDL is rendered with MetaTables' SQLite rules (``metatables.migrations.sqlite``,
``JSONB`` as ``JSON`` and ``UUID`` as ``CHAR(32)``), which every migration in the process
registers. They are registered here, so the DDL doesn't depend on whether a migration ran
first.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.schema import CreateIndex, CreateTable

import metatables.migrations.sqlite  # noqa: F401  (MetaTables' SQLite DDL rules)
from metatables import (
    PlatformTimeIndexMetaTable,
    sqlalchemy_naming_convention,
    time_indexed_registration_request_from_sqlalchemy_model,
)
from metatables.models.sqlalchemy_contracts import compute_metatable_contract_hash
from msm.storage_instances import TimeIndexInstance
from msm.time_index.execution.storage import TradesInstance
from msm.time_index.indices.storage import IndexValues1d, IndexValues1h, IndexValues1m
from msm.time_index.utils.storage_schema import (
    storage_column_dtypes_map,
    storage_column_nullable_map,
    storage_index_names,
    storage_time_index_name,
)
from msm_portfolios.time_index.contract_instances import (
    PortfolioEventLedgerInstance,
    PortfolioRebalanceStateInstance,
)
from msm_portfolios.time_index.prices.storage import (
    ExternalPricesInstance,
    InterpolatedPricesInstance,
)
from msm_pricing.time_index.curves.storage import DiscountCurvesInstance, DiscountCurvesStorage
from tests.support import instance_tables
from tests.support.instance_tables import DECLARED_TABLES

FACTORY_TABLES = json.loads((Path(__file__).parent / "factory_tables.json").read_text())

# Markets' own Index-value tables (ADR 0066, decision 6), declared in Markets' module.
CHECKED_TABLES: dict[str, Any] = {
    **DECLARED_TABLES,
    "markets_index_values_1m": IndexValues1m,
    "markets_index_values_1h": IndexValues1h,
    "markets_index_values_1d": IndexValues1d,
}


def _ddl(table: Any, dialect: Any) -> list[str]:
    head = str(CreateTable(table).compile(dialect=dialect)).strip().split("\n")
    body = [line.strip().rstrip(",").strip() for line in head[1:-1]]
    columns = [line for line in body if not line.startswith("CONSTRAINT")]
    constraints = sorted(line for line in body if line.startswith("CONSTRAINT"))
    indexes = [
        str(CreateIndex(index).compile(dialect=dialect)).strip()
        for index in sorted(table.indexes, key=lambda item: item.name)
    ]
    return [head[0].strip(), *columns, *constraints, *indexes]


def _record(model: type) -> dict[str, Any]:
    request = time_indexed_registration_request_from_sqlalchemy_model(
        model, data_source_uid="00000000-0000-0000-0000-000000000000"
    ).model_dump(mode="json")
    request["table_contract"]["authoring"].pop("table_model", None)
    return {
        "table_name": model.__table__.name,
        "metatable_identifier": model.__metatable_identifier__,
        "authored_identifier": getattr(model, "__markets_authored_identifier__", None),
        "info": dict(model.__table__.info),
        "namespace": model.__metatable_namespace__,
        "storage_app": getattr(model, "__markets_storage_app__", None),
        "cadence": getattr(model, "__cadence__", None),
        "time_index_name": model.__time_index_name__,
        "index_names": list(model.__index_names__),
        "extra_hash_components": dict(model.__metatable_extra_hash_components__),
        "description": model.__metatable_description__,
        "storage_layout": getattr(model, "__storage_layout__", None),
        "contract_hash": compute_metatable_contract_hash(model),
        "registration_request_sha256": hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "ddl_postgresql": _ddl(model.__table__, postgresql.dialect()),
        "ddl_sqlite": _ddl(model.__table__, sqlite.dialect()),
    }


def test_every_pinned_table_is_checked() -> None:
    assert sorted(CHECKED_TABLES) == sorted(FACTORY_TABLES)


@pytest.mark.parametrize("name", sorted(FACTORY_TABLES))
def test_a_class_statement_builds_the_table_its_factory_built(name: str) -> None:
    """Same name, identifiers and DDL, so no migration changes for an existing table."""

    model = CHECKED_TABLES[name]
    model = model if isinstance(model, type) else model()

    assert _record(model) == FACTORY_TABLES[name]


@pytest.mark.parametrize("name", sorted(DECLARED_TABLES))
def test_a_declared_class_imports_back_by_its_address(name: str) -> None:
    model = DECLARED_TABLES[name]
    module = importlib.import_module(model.__module__)

    assert model.__module__ == instance_tables.__name__
    assert getattr(module, model.__qualname__) is model


def test_a_new_process_imports_the_same_tables() -> None:
    """A node Job run imports its table class by ``module:qualname`` (MetaTables ADR 0032)."""

    addresses = [f"{model.__module__}:{model.__qualname__}" for model in DECLARED_TABLES.values()]
    script = (
        "import importlib, json, sys\n"
        "found = {}\n"
        "for address in json.loads(sys.argv[1]):\n"
        "    module, _, qualname = address.partition(':')\n"
        "    model = getattr(importlib.import_module(module), qualname)\n"
        "    found[address] = [model.__table__.name, model.__metatable_identifier__]\n"
        "print(json.dumps(found))\n"
    )
    root = Path(__file__).resolve().parents[2]
    completed = subprocess.run(
        [sys.executable, "-c", script, json.dumps(addresses)],
        capture_output=True,
        check=True,
        cwd=root,
        env={**os.environ, "PYTHONPATH": f"{root / 'src'}{os.pathsep}{root}"},
        text=True,
    )

    assert json.loads(completed.stdout.strip().splitlines()[-1]) == {
        f"{model.__module__}:{model.__qualname__}": [
            model.__table__.name,
            model.__metatable_identifier__,
        ]
        for model in DECLARED_TABLES.values()
    }


@pytest.mark.parametrize(
    "model",
    [
        instance_tables.ProviderDiscountCurves,
        instance_tables.ProviderIndexFixings,
        instance_tables.ProviderAssetPricingDetails,
        instance_tables.AppTrades,
    ],
)
def test_instances_keep_the_core_schema_in_the_owners_namespace(model) -> None:
    core = model.__core_storage__

    assert issubclass(model, PlatformTimeIndexMetaTable)
    assert storage_column_dtypes_map(model) == storage_column_dtypes_map(core)
    assert storage_column_nullable_map(model) == storage_column_nullable_map(core)
    assert storage_time_index_name(model) == storage_time_index_name(core)
    assert storage_index_names(model) == storage_index_names(core)
    foreign_keys = sorted((fk.parent.name, fk.target_fullname) for fk in model.__table__.foreign_keys)
    assert foreign_keys == sorted((fk.parent.name, fk.target_fullname) for fk in core.__table__.foreign_keys)
    # The keys are Markets' own columns; no Markets table is copied into the owner's metadata.
    assert sorted((fk.parent.name, id(fk.column)) for fk in model.__table__.foreign_keys) == sorted(
        (fk.parent.name, id(fk.column)) for fk in core.__table__.foreign_keys
    )
    owner_tables = model.__table__.metadata.tables
    assert not any(fk.column.table.key in owner_tables for fk in model.__table__.foreign_keys)


def test_instances_on_an_owners_base_key_to_markets_tables_and_attach() -> None:
    """Several Asset foreign keys on one base resolve to Markets' table and attach it."""

    from msm.api.remote import use_remote_backend, use_runtime_backend
    from msm.models import AssetTable
    from msm.models.registration import resolve_markets_meta_table_models

    trades = instance_tables.AppTrades

    assert trades.__table__.metadata is instance_tables.AppOwnerBase.metadata
    assert AssetTable.__table__.fullname not in instance_tables.AppOwnerBase.metadata.tables
    resolved = resolve_markets_meta_table_models([trades])
    assert resolved[-1] is trades and AssetTable in resolved

    class _Backend:
        def call(self, resource, operation, arguments):  # pragma: no cover - never called
            raise AssertionError("attachment must not call the API")

    use_remote_backend(_Backend())
    try:
        assert resolve_markets_meta_table_models([trades]) == [trades]
    finally:
        use_runtime_backend()


def test_an_owners_base_holds_only_the_owners_tables() -> None:
    """The keys to Markets copy no table, and the owner's metadata still sorts on its own."""

    assert sorted(table.name for table in instance_tables.AppOwnerBase.metadata.sorted_tables) == [
        "my_app__accountholdingsts__main",
        "my_app__ordereventsts__main",
        "my_app__ordersts__main",
        "my_app__targetpositionsts__main",
        "my_app__tradests__main",
        "my_app__virtualfundholdingsts__main",
    ]


def _owner_base() -> type[DeclarativeBase]:
    class OwnerBase(DeclarativeBase):
        metadata = MetaData(naming_convention=sqlalchemy_naming_convention())

    return OwnerBase


@pytest.mark.parametrize("contract", [DiscountCurvesInstance, PortfolioRebalanceStateInstance])
@pytest.mark.parametrize(
    ("attribute", "empty"),
    [
        ("__metatable_namespace__", None),
        ("__metatable_namespace__", "  "),
        ("__markets_storage_app__", None),
        ("__markets_storage_app__", ""),
    ],
)
def test_an_instance_states_its_owners_namespace_and_app(contract, attribute, empty) -> None:
    """None of them falls back to Markets' own (#95)."""

    base = _owner_base()
    owner = {
        "__instance_key__": "owned",
        "__metatable_namespace__": "owner",
        "__markets_storage_app__": "owner",
    }
    if empty is None:
        del owner[attribute]
    else:
        owner[attribute] = empty

    with pytest.raises(ValueError, match=f"must declare {attribute}"):
        type("Owned", (contract, base), dict(owner))
    assert not base.metadata.tables


def test_an_instance_inherits_its_owners_declarative_base() -> None:
    with pytest.raises(TypeError, match="owner's declarative base"):

        class Unbased(TradesInstance):
            __instance_key__ = "main"
            __metatable_namespace__ = "owner"
            __markets_storage_app__ = "owner"


def test_an_instance_inherits_a_contracts_base() -> None:
    base = _owner_base()
    with pytest.raises(TypeError, match="contract's instance base"):

        class NoContract(TimeIndexInstance, base):
            __instance_key__ = "main"
            __metatable_namespace__ = "owner"
            __markets_storage_app__ = "owner"


@pytest.mark.parametrize("key", [None, "", "Bad Key!", "_leading", "x" * 64])
def test_an_instance_key_is_validated(key) -> None:
    base = _owner_base()
    attributes = {"__metatable_namespace__": "owner", "__markets_storage_app__": "owner"}
    if key is not None:
        attributes["__instance_key__"] = key

    with pytest.raises(ValueError, match="__instance_key__"):
        type("Keyed", (TradesInstance, base), attributes)


def test_an_instance_key_is_normalized() -> None:
    class Normalized(TradesInstance, _owner_base()):
        __instance_key__ = " Main "
        __metatable_namespace__ = "owner"
        __markets_storage_app__ = "owner"

    assert Normalized.__table__.name == "owner__tradests__main"


@pytest.mark.parametrize("stated", ["__metatable_identifier__", "__index_names__", "__tablename__"])
def test_an_instance_leaves_the_contracts_attributes_to_it(stated) -> None:
    base = _owner_base()
    with pytest.raises(TypeError, match="which its contract gives"):
        type(
            "Stated",
            (TradesInstance, base),
            {
                "__instance_key__": "main",
                "__metatable_namespace__": "owner",
                "__markets_storage_app__": "owner",
                stated: "mine",
            },
        )


def test_an_instance_takes_a_cadence_where_its_core_declares_none() -> None:
    """Interpolated prices: each instance's cadence is its upsample frequency (#95)."""

    base = _owner_base()

    class Daily(InterpolatedPricesInstance, base):
        __instance_key__ = "daily"
        __metatable_namespace__ = "ns-cadence"
        __markets_storage_app__ = "ns_cadence"
        __cadence__ = " 1D "

    assert Daily.__cadence__ == "1d"
    request = time_indexed_registration_request_from_sqlalchemy_model(
        Daily, data_source_uid="00000000-0000-0000-0000-000000000000"
    ).model_dump(mode="json")
    assert request["table_contract"]["authoring"]["time_indexed"]["cadence"] == "1d"

    # A cadence the core declares is the contract's, which its instances keep.
    class Kept(ExternalPricesInstance, base):
        __instance_key__ = "kept"
        __metatable_namespace__ = "ns-cadence"
        __markets_storage_app__ = "ns_cadence"

    assert Kept.__cadence__ == "1d"
    with pytest.raises(ValueError, match="declares cadence"):

        class Other(ExternalPricesInstance, base):
            __instance_key__ = "other"
            __metatable_namespace__ = "ns-cadence"
            __markets_storage_app__ = "ns_cadence"
            __cadence__ = "5m"

    with pytest.raises(ValueError, match="cadence"):

        class Empty(InterpolatedPricesInstance, base):
            __instance_key__ = "empty"
            __metatable_namespace__ = "ns-cadence"
            __markets_storage_app__ = "ns_cadence"
            __cadence__ = " "


def test_one_table_has_one_declaration() -> None:
    base = _owner_base()
    owner = {"__metatable_namespace__": "ns-once", "__markets_storage_app__": "ns_once"}

    type("First", (PortfolioEventLedgerInstance, base), {"__instance_key__": "main", **owner})

    with pytest.raises(ValueError, match="already declared"):
        type("Second", (PortfolioEventLedgerInstance, base), {"__instance_key__": "main", **owner})


def test_an_owners_mixin_states_the_owner_wherever_it_comes() -> None:
    """``instance_tables.Provider`` comes after the contract's base, whose own bases carry
    Markets' defaults; the owner's values win."""

    model = instance_tables.ProviderDiscountCurves

    assert model.__metatable_namespace__ == "my-provider"
    assert model.__table__.name == "my_provider__discountcurvests__main"
    assert model.__core_storage__ is DiscountCurvesStorage
