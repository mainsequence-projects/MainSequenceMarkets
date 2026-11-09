from __future__ import annotations

import datetime as dt
import uuid

import pytest
from mainsequence.client.exceptions import ConflictError
from pydantic import BaseModel, ValidationError

from msm.api.http import (
    ACCOUNT_SYNC_ACTION,
    AccountSyncOperation,
    AccountSyncRequest,
    AccountSyncResult,
    InMemoryOperationStore,
    OperationError,
    OperationNotFoundError,
    api_http_error,
    build_resource_discovery_spec,
    resolve_resource_discovery,
    resource_column,
    resource_text_filter,
)


class ExampleRequest(BaseModel):
    symbols: list[str]


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


def test_structured_errors_map_sdk_conflicts_to_sanitized_409() -> None:
    error = api_http_error(ConflictError("SECRET duplicate key value violates unique constraint"))

    assert error.status_code == 409
    assert error.detail == {
        "code": "conflict",
        "message": "The request conflicts with the current state of the resource.",
        "retryable": False,
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


ACCOUNT_UID = str(uuid.UUID("00000000-0000-0000-0000-000000000301"))
HOLDINGS_SET_UID = str(uuid.UUID("00000000-0000-0000-0000-000000000304"))


def _account_sync_store() -> tuple[InMemoryOperationStore, str]:
    store = InMemoryOperationStore[AccountSyncRequest, AccountSyncResult]()
    created = store.create(
        action=ACCOUNT_SYNC_ACTION,
        request=AccountSyncRequest(account_uid=ACCOUNT_UID),
        owner_uid="user-a",
        steps=[("capture", "Capture holdings"), ("publish", "Publish holdings set")],
    )
    store.start(created.operation_uid, step_key="capture")
    return store, created.operation_uid


def test_succeeded_account_sync_validates_with_its_result() -> None:
    store, operation_uid = _account_sync_store()
    store.advance(operation_uid, step_key="publish")
    completed = store.succeed(
        operation_uid,
        result=AccountSyncResult(
            account_uid=ACCOUNT_UID,
            holdings_set_uid=HOLDINGS_SET_UID,
            time_index=dt.datetime(2026, 11, 9, 10, 30, tzinfo=dt.timezone(dt.timedelta(hours=-5))),
            holdings_rows=3,
            extra={"unresolved_symbols": ["XYZ"]},
        ),
    )

    operation = AccountSyncOperation.model_validate(completed.model_dump(mode="json"))

    assert operation.action == "account_sync"
    assert operation.result is not None
    assert operation.result.holdings_set_uid == HOLDINGS_SET_UID
    assert operation.result.time_index == dt.datetime(2026, 11, 9, 15, 30, tzinfo=dt.UTC)
    assert operation.result.extra == {"unresolved_symbols": ["XYZ"]}


def test_account_sync_result_requires_every_documented_field() -> None:
    published_none = AccountSyncResult(
        account_uid=ACCOUNT_UID,
        holdings_set_uid=None,
        time_index=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
        holdings_rows=0,
    )
    assert published_none.extra == {}

    with pytest.raises(ValidationError, match="holdings_set_uid"):
        AccountSyncResult(
            account_uid=ACCOUNT_UID,
            time_index=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
            holdings_rows=0,
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        AccountSyncResult(
            account_uid=ACCOUNT_UID,
            holdings_set_uid=None,
            time_index=dt.datetime(2026, 11, 9),
            holdings_rows=0,
        )
    with pytest.raises(ValidationError, match="holdings_rows"):
        AccountSyncResult(
            account_uid=ACCOUNT_UID,
            holdings_set_uid=None,
            time_index=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
            holdings_rows=-1,
        )


def test_account_sync_operation_enforces_terminal_payloads() -> None:
    store, operation_uid = _account_sync_store()
    failed = store.fail(
        operation_uid,
        error=OperationError(code="venue_unavailable", message="The venue did not answer."),
    )
    assert AccountSyncOperation.model_validate(failed.model_dump(mode="json")).status == "failed"

    without_error = {**failed.model_dump(mode="json"), "error": None}
    with pytest.raises(ValidationError, match="must contain an error"):
        AccountSyncOperation.model_validate(without_error)

    succeeded_without_result = {
        **failed.model_dump(mode="json"),
        "status": "succeeded",
        "error": None,
    }
    with pytest.raises(ValidationError, match="AccountSyncResult"):
        AccountSyncOperation.model_validate(succeeded_without_result)

    other_action = {**failed.model_dump(mode="json"), "action": "register"}
    with pytest.raises(ValidationError, match="action"):
        AccountSyncOperation.model_validate(other_action)


def test_account_sync_result_must_describe_the_requested_account() -> None:
    store, operation_uid = _account_sync_store()
    completed = store.succeed(
        operation_uid,
        result=AccountSyncResult(
            account_uid=str(uuid.uuid4()),
            holdings_set_uid=None,
            time_index=dt.datetime(2026, 11, 9, tzinfo=dt.UTC),
            holdings_rows=0,
        ),
    )

    with pytest.raises(ValidationError, match="requested account"):
        AccountSyncOperation.model_validate(completed.model_dump(mode="json"))
