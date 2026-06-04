from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import msm_pricing.bootstrap as pricing_bootstrap
from msm_pricing.config import (
    PricingMarketDataConfiguration,
    get_pricing_market_data_configuration,
    reset_pricing_market_data_configuration,
)
from msm_pricing.models import PricingMarketDataBindingTable
from msm_pricing.settings import (
    PRICING_CONCEPT_DISCOUNT_CURVES,
    PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    PRICING_CONTEXT_DEFAULT,
)


@pytest.fixture(autouse=True)
def reset_pricing_runtime(monkeypatch) -> None:
    monkeypatch.setattr(pricing_bootstrap, "_PRICING_RUNTIME", None)
    monkeypatch.setattr(pricing_bootstrap, "_CREATE_PRICING_SCHEMAS_CONFIG", None)
    monkeypatch.setattr(pricing_bootstrap, "_PRICING_RUNTIME_BY_CONFIG", {})
    reset_pricing_market_data_configuration()
    monkeypatch.delenv("MSM_AUTO_REGISTER_NAMESPACE", raising=False)
    yield
    reset_pricing_market_data_configuration()


def install_fake_pricing_bootstrap(monkeypatch):
    attach_calls = []

    class FakeMarketsRepositoryContext:
        def __init__(
            self,
            timeout=None,
            namespace=None,
        ) -> None:
            self.timeout = timeout
            self.namespace = namespace

    def fake_resolve_pricing_meta_table_models(models=None):
        resolved = []
        for model in list(models or ["CurveTable"]):
            if model == "PricingMarketDataBindingTable":
                resolved.append(PricingMarketDataBindingTable)
            else:
                resolved.append(model)
        return resolved

    def fake_pricing_meta_table_identifier(model):
        model_name = str(getattr(model, "__name__", model))
        return {
            "CurveTable": "Curve",
            "IndexConventionDetailsTable": "IndexConventionDetails",
            "PricingMarketDataBindingTable": "PricingMarketDataBinding",
        }.get(model_name, model_name)

    def fake_resolve_registered_markets_meta_tables(**kwargs):
        attach_calls.append(kwargs)
        return SimpleNamespace(
            meta_tables=["curve-meta-table"],
            models=kwargs["models"],
        )

    monkeypatch.setattr(
        pricing_bootstrap,
        "MarketsRepositoryContext",
        FakeMarketsRepositoryContext,
    )
    monkeypatch.setattr(
        pricing_bootstrap,
        "resolve_pricing_meta_table_models",
        fake_resolve_pricing_meta_table_models,
    )
    monkeypatch.setattr(
        pricing_bootstrap,
        "pricing_meta_table_identifier",
        fake_pricing_meta_table_identifier,
    )
    monkeypatch.setattr(
        "msm.models.registration.resolve_registered_markets_meta_tables",
        fake_resolve_registered_markets_meta_tables,
    )
    return attach_calls


def test_create_pricing_schemas_returns_cached_runtime_for_same_config(monkeypatch) -> None:
    attach_calls = install_fake_pricing_bootstrap(monkeypatch)

    first_runtime = pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )
    second_runtime = pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )

    assert second_runtime is first_runtime
    assert first_runtime.namespace == "mainsequence.examples"
    assert first_runtime.context.namespace == "mainsequence.examples"
    assert len(attach_calls) == 1


def test_create_pricing_schemas_signature_excludes_migration_setup_arguments() -> None:
    parameters = inspect.signature(pricing_bootstrap.create_pricing_schemas).parameters

    assert "data_source_uid" not in parameters
    assert "open_for_everyone" not in parameters
    assert "protect_from_deletion" not in parameters
    assert "introspect" not in parameters


def test_create_pricing_schemas_installs_market_data_configuration_override(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)

    pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
        market_data_configuration={
            "context_key": "eod",
            "data_node_identifiers": {
                PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
                PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: ("vendor.interest_rate_index_fixings"),
            },
        },
    )

    configuration = get_pricing_market_data_configuration()
    assert configuration == PricingMarketDataConfiguration(
        context_key="eod",
        data_node_identifiers={
            PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
            PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS: ("vendor.interest_rate_index_fixings"),
        },
    )


def test_create_pricing_schemas_without_market_data_override_leaves_defaults(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")

    pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )

    configuration = get_pricing_market_data_configuration()
    assert configuration == PricingMarketDataConfiguration()


def test_create_pricing_schemas_rejects_second_process_config_change(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)

    pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )

    with pytest.raises(RuntimeError, match="already initialized"):
        pricing_bootstrap.create_pricing_schemas(
            namespace="mainsequence.other",
            models=["CurveTable"],
        )


def test_create_pricing_schemas_does_not_install_market_data_override_on_schema_error(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)

    pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )

    with pytest.raises(RuntimeError, match="already initialized"):
        pricing_bootstrap.create_pricing_schemas(
            namespace="mainsequence.other",
            models=["CurveTable"],
            market_data_configuration={
                "context_key": "eod",
                "data_node_identifiers": {
                    PRICING_CONCEPT_DISCOUNT_CURVES: "vendor.discount_curves",
                },
            },
        )

    configuration = get_pricing_market_data_configuration()
    assert configuration == PricingMarketDataConfiguration()


def test_create_pricing_schemas_seeds_default_market_data_bindings(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)
    calls = []

    def fake_search_model(context, *, model, filters, limit):
        calls.append(("search", context, model, filters, limit))
        return {"rows": []}

    def fake_create_model(context, *, model, values):
        calls.append(("create", context, model, values))
        return {"row": {"uid": "binding-uid", **values}}

    monkeypatch.setattr(pricing_bootstrap, "search_model", fake_search_model)
    monkeypatch.setattr(pricing_bootstrap, "create_model", fake_create_model)

    pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["PricingMarketDataBindingTable"],
    )

    create_values = [call[3] for call in calls if call[0] == "create"]
    assert create_values == [
        {
            "context_key": PRICING_CONTEXT_DEFAULT,
            "concept_key": PRICING_CONCEPT_DISCOUNT_CURVES,
            "data_node_identifier": "mainsequence.examples.DiscountCurvesTS",
            "source": "msm_pricing.bootstrap",
            "metadata_json": {"seeded_default": True},
        },
        {
            "context_key": PRICING_CONTEXT_DEFAULT,
            "concept_key": PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
            "data_node_identifier": "mainsequence.examples.IndexFixingsTS",
            "source": "msm_pricing.bootstrap",
            "metadata_json": {"seeded_default": True},
        },
    ]


def test_default_market_data_binding_seeding_does_not_overwrite_existing_rows(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)
    calls = []

    def fake_search_model(context, *, model, filters, limit):
        calls.append(("search", context, model, filters, limit))
        return {
            "rows": [
                {
                    "uid": "existing-binding-uid",
                    **filters,
                    "data_node_identifier": "existing.identifier",
                }
            ]
        }

    def fake_create_model(*_args, **_kwargs):
        raise AssertionError("create_model should not overwrite existing bindings")

    monkeypatch.setattr(pricing_bootstrap, "search_model", fake_search_model)
    monkeypatch.setattr(pricing_bootstrap, "create_model", fake_create_model)

    runtime = pricing_bootstrap.create_pricing_schemas(
        models=["PricingMarketDataBindingTable"],
    )

    rows = pricing_bootstrap.seed_default_pricing_market_data_bindings(runtime)

    assert len(rows) == 2
    assert all(row["data_node_identifier"] == "existing.identifier" for row in rows)


def test_default_market_data_binding_seeding_replaces_when_requested(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)
    calls = []

    def fake_upsert_model(context, *, model, values, conflict_columns):
        calls.append((context, model, values, conflict_columns))
        return {"row": {"uid": "binding-uid", **values}}

    monkeypatch.setattr(pricing_bootstrap, "upsert_model", fake_upsert_model)

    runtime = pricing_bootstrap.create_pricing_schemas(
        models=["PricingMarketDataBindingTable"],
        replace_default_market_data_bindings=True,
    )

    assert runtime.meta_table_models == [PricingMarketDataBindingTable]
    assert [call[2]["concept_key"] for call in calls] == [
        PRICING_CONCEPT_DISCOUNT_CURVES,
        PRICING_CONCEPT_INTEREST_RATE_INDEX_FIXINGS,
    ]
    assert {call[3] for call in calls} == {("context_key", "concept_key")}


def test_resolve_pricing_runtime_requires_initialized_runtime(monkeypatch) -> None:
    attach_calls = install_fake_pricing_bootstrap(monkeypatch)
    monkeypatch.setenv("MSM_AUTO_REGISTER_NAMESPACE", "mainsequence.examples")

    with pytest.raises(RuntimeError, match="initialized pricing runtime"):
        pricing_bootstrap.resolve_pricing_runtime(
            models=["CurveTable"],
            row_model_name="Curve",
        )

    assert attach_calls == []


def test_resolve_pricing_runtime_returns_active_runtime(monkeypatch) -> None:
    attach_calls = install_fake_pricing_bootstrap(monkeypatch)

    runtime = pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )

    assert (
        pricing_bootstrap.resolve_pricing_runtime(
            models=["CurveTable"],
            row_model_name="Curve",
        )
        is runtime
    )
    assert len(attach_calls) == 1


def test_resolve_pricing_runtime_uses_identifier_after_physical_binding(
    monkeypatch,
) -> None:
    from msm.repositories.base import MarketsRepositoryContext
    from msm_pricing.meta_tables import pricing_meta_table_identifier
    from msm_pricing.models import CurveTable

    identifier = pricing_meta_table_identifier(CurveTable)
    registration = SimpleNamespace(
        meta_tables=["curve-meta-table"],
        models=[CurveTable],
    )
    runtime = pricing_bootstrap.PricingRuntime(
        registration=registration,
        context=MarketsRepositoryContext(),
    )
    monkeypatch.setattr(pricing_bootstrap, "_PRICING_RUNTIME", runtime)
    monkeypatch.setitem(CurveTable.__table__.info, "identifier", identifier)
    monkeypatch.setattr(CurveTable, "__metatable_uid__", "curve-meta-table-uid", raising=False)
    monkeypatch.setattr(CurveTable.__table__, "name", "backend_physical_curve")
    monkeypatch.setattr(
        CurveTable.__table__,
        "fullname",
        "public.backend_physical_curve",
        raising=False,
    )

    assert (
        pricing_bootstrap.resolve_pricing_runtime(
            models=[CurveTable],
            row_model_name="Curve",
        )
        is runtime
    )


def test_resolve_pricing_runtime_missing_tables_error_names_declarations(
    monkeypatch,
) -> None:
    install_fake_pricing_bootstrap(monkeypatch)

    pricing_bootstrap.create_pricing_schemas(
        namespace="mainsequence.examples",
        models=["CurveTable"],
    )

    with pytest.raises(RuntimeError, match="IndexConventionDetailsTable") as exc_info:
        pricing_bootstrap.resolve_pricing_runtime(
            models=["IndexConventionDetailsTable"],
            row_model_name="IndexConventionDetails",
        )

    assert "Initialized tables: CurveTable" in str(exc_info.value)
