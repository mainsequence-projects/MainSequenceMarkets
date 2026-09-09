from __future__ import annotations

from pydantic import BaseModel

from apps.v1.schemas.resource_contracts import ResourceCollection as CompatibilityCollection
from msm.api.http import (
    InMemoryOperationStore,
    OperationError,
    OperationNotFoundError,
    ResourceCollection,
    api_http_error,
    build_resource_discovery_spec,
    resolve_resource_discovery,
    resource_column,
    resource_text_filter,
)


class ExampleRequest(BaseModel):
    symbols: list[str]


def test_apps_v1_resource_contract_is_a_public_package_compatibility_import() -> None:
    assert CompatibilityCollection is ResourceCollection


def test_discovery_builders_validate_semantic_query_scope() -> None:
    spec = build_resource_discovery_spec(
        resource_id="assets",
        label="Assets",
        item_label="assets",
        identity_fields=("uid",),
        columns=(resource_column("unique_identifier", "Identifier"),),
        search=True,
        filters=(resource_text_filter("asset_type", "Asset type"),),
    )

    response = resolve_resource_discovery(
        "assets",
        ["search", "asset_type"],
        specs={"assets": spec},
    )

    assert response.resource.id == "assets"
    assert response.list.controls.search is not None
    assert response.list.columns[0].value_path == "unique_identifier"


def test_discovery_rejects_presentation_query_keys() -> None:
    spec = build_resource_discovery_spec(
        resource_id="assets",
        label="Assets",
        item_label="assets",
        identity_fields=("uid",),
        columns=(resource_column("uid", "UID"),),
    )

    try:
        resolve_resource_discovery("assets", ["limit"], specs={"assets": spec})
    except ValueError as exc:
        assert "presentation query keys" in str(exc)
    else:
        raise AssertionError("Presentation query keys must not alter discovery metadata.")


def test_structured_errors_sanitize_unexpected_dependency_details() -> None:
    error = api_http_error(RuntimeError("SECRET provider details"))

    assert error.status_code == 503
    assert error.detail == {
        "code": "dependency_unavailable",
        "message": "The operation could not be completed by a required service.",
        "retryable": True,
    }
    assert "SECRET" not in str(error.detail)


def test_observable_operations_are_owner_scoped_and_follow_lifecycle() -> None:
    store = InMemoryOperationStore[ExampleRequest, dict[str, int]](poll_after_ms=250)
    created = store.create(
        action="register",
        request=ExampleRequest(symbols=["BTCUSDT"]),
        owner_uid="user-a",
        steps=[("prepare", "Prepare"), ("register", "Register")],
    )

    running = store.start(created.operation_uid, step_key="prepare")
    registering = store.advance(created.operation_uid, step_key="register")
    completed = store.succeed(created.operation_uid, result={"created": 1})

    assert running.status == "running"
    assert registering.current_step == "register"
    assert completed.status == "succeeded"
    assert completed.result == {"created": 1}
    assert completed.poll_after_ms == 250
    assert store.get(created.operation_uid, owner_uid="user-a") == completed

    try:
        store.get(created.operation_uid, owner_uid="user-b")
    except OperationNotFoundError:
        pass
    else:
        raise AssertionError("Operation reads must be scoped to their owner UID.")


def test_observable_operation_failure_retains_sanitized_public_error() -> None:
    store = InMemoryOperationStore[ExampleRequest, dict[str, int]]()
    created = store.create(
        action="register",
        request=ExampleRequest(symbols=["ETHUSDT"]),
        owner_uid="user-a",
        steps=[("register", "Register")],
    )
    store.start(created.operation_uid, step_key="register")

    failed = store.fail(
        created.operation_uid,
        error=OperationError(
            code="dependency_unavailable",
            message="The operation could not be completed by a required service.",
            retryable=True,
        ),
    )

    assert failed.status == "failed"
    assert failed.error is not None
    assert failed.error.retryable is True
    assert failed.steps[0].status == "failed"
