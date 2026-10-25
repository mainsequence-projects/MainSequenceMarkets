"""Core-first `include` hydration of provider sidecars (ADR 0047, decision 4)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.v1.main import app
from apps.v1.schemas.accounts import Account, AccountWithIncludes
from apps.v1.services import includes
from msm.models import AccountTable

SIDECAR_UID = "11111111-1111-1111-1111-111111111111"
OTHER_UID = "22222222-2222-2222-2222-222222222222"


def _sidecar(uid: str = SIDECAR_UID, *, target: str = AccountTable.__table__.name, join: str = "account_uid"):
    return SimpleNamespace(
        uid=uid,
        identifier="alpaca-connectors.AlpacaAccountDetails",
        namespace="alpaca-connectors",
        physical_table_name="alpaca_connectors__acct_alpaca",
        physical_schema="public",
        columns=[{"name": join}, {"name": "is_paper"}, {"name": "api_key_id"}],
        foreign_keys=[
            SimpleNamespace(
                source_columns=[join],
                target_columns=["uid"],
                target_table_physical_table_name=target,
                target_table_uid=None,
            )
        ],
    )


def _account(uid: uuid.UUID) -> Account:
    return Account(uid=uid, unique_identifier=f"acct-{uid.hex[:6]}", account_name="A")


def test_resolve_includes_requires_a_single_column_fk_to_the_core_uid() -> None:
    resolved = includes.resolve_sidecar_includes(
        [f"{SIDECAR_UID},{OTHER_UID}"],
        core_model=AccountTable,
        meta_table_lookup=lambda uids: [_sidecar(), _sidecar(OTHER_UID, join="owner_uid")],
    )
    assert [item.join_column for item in resolved] == ["account_uid", "owner_uid"]
    assert resolved[0].physical_table_name == "alpaca_connectors__acct_alpaca"
    assert resolved[0].physical_schema is None
    assert resolved[0].columns == ("account_uid", "is_paper", "api_key_id")

    with pytest.raises(LookupError, match="not a visible MetaTable"):
        includes.resolve_sidecar_includes([SIDECAR_UID], core_model=AccountTable, meta_table_lookup=lambda _uids: [])
    with pytest.raises(ValueError, match="not a sidecar of it"):
        includes.resolve_sidecar_includes(
            [SIDECAR_UID],
            core_model=AccountTable,
            meta_table_lookup=lambda _uids: [_sidecar(target="ms_markets__asset")],
        )
    with pytest.raises(ValueError, match="at most 10"):
        includes.normalize_includes([str(uuid.uuid4()) for _ in range(11)])
    assert includes.resolve_sidecar_includes(None, core_model=AccountTable, meta_table_lookup=lambda _u: pytest.fail("no lookup")) == []


def test_read_sidecar_rows_reads_each_sidecar_once_and_keys_by_core_uid(monkeypatch) -> None:
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    statements: list[str] = []
    monkeypatch.setattr(includes, "compile_markets_statement", lambda statement, **_kwargs: statements.append(str(statement.compile(compile_kwargs={"literal_binds": True}))) or statement)
    monkeypatch.setattr(
        includes,
        "execute_markets_operation",
        lambda _operation, **_kwargs: {"rows": [
            {"account_uid": first, "is_paper": True, "api_key_id": b"\x01\x02"},
            {"account_uid": str(second), "is_paper": False, "api_key_id": None},
        ]},
    )
    (sidecar,) = includes.resolve_sidecar_includes([SIDECAR_UID], core_model=AccountTable, meta_table_lookup=lambda _u: [_sidecar()])

    hydrated = includes.read_sidecar_rows(object(), core_uids=[first, second, third], includes=[sidecar])

    assert len(statements) == 1
    assert "alpaca_connectors__acct_alpaca" in statements[0]
    assert "account_uid IN" in statements[0]
    assert hydrated[str(first)] == {SIDECAR_UID: {"account_uid": str(first), "is_paper": True, "api_key_id": "0102"}}
    assert hydrated[str(second)][SIDECAR_UID]["is_paper"] is False
    assert hydrated[str(third)] == {SIDECAR_UID: None}


def test_read_sidecar_rows_wraps_backend_failures(monkeypatch) -> None:
    monkeypatch.setattr(includes, "compile_markets_statement", lambda statement, **_kwargs: statement)

    def denied(_operation, **_kwargs):
        raise PermissionError("missing data_viewer on alpaca-connectors.AlpacaAccountDetails")

    monkeypatch.setattr(includes, "execute_markets_operation", denied)
    (sidecar,) = includes.resolve_sidecar_includes([SIDECAR_UID], core_model=AccountTable, meta_table_lookup=lambda _u: [_sidecar()])

    with pytest.raises(includes.SidecarReadError, match="could not be read: PermissionError"):
        includes.read_sidecar_rows(object(), core_uids=[uuid.uuid4()], includes=[sidecar])


def test_hydrate_attaches_includes_to_every_item(monkeypatch) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(includes, "compile_markets_statement", lambda statement, **_kwargs: statement)
    monkeypatch.setattr(includes, "execute_markets_operation", lambda _o, **_k: {"rows": [{"account_uid": first, "is_paper": True, "api_key_id": None}]})

    hydrated = includes.hydrate(
        object(),
        model_cls=AccountWithIncludes,
        core_model=AccountTable,
        items=[_account(first), _account(second)],
        include=[SIDECAR_UID],
        meta_table_lookup=lambda _u: [_sidecar()],
    )
    plain = includes.hydrate(object(), model_cls=AccountWithIncludes, core_model=AccountTable, items=[_account(first)], include=None)

    assert all(isinstance(item, AccountWithIncludes) for item in hydrated)
    assert hydrated[0].includes == {SIDECAR_UID: {"account_uid": str(first), "is_paper": True, "api_key_id": None}}
    assert hydrated[1].includes == {SIDECAR_UID: None}
    assert plain[0].includes == {}
    assert plain[0].unique_identifier == f"acct-{first.hex[:6]}"


def test_by_uids_route_passes_include_and_maps_errors(monkeypatch) -> None:
    account_uid = uuid.uuid4()
    captured: dict[str, object] = {}

    def fake_lookup(*, uids, include=None):
        captured.update(uids=uids, include=include)
        return [AccountWithIncludes(uid=account_uid, unique_identifier="a", account_name="A", includes={SIDECAR_UID: {"is_paper": True}})]

    monkeypatch.setattr("apps.v1.routers.accounts.get_accounts_by_uids", fake_lookup)
    client = TestClient(app)

    response = client.get("/api/v1/account/by-uids/", params=[("uid__in", str(account_uid)), ("include", SIDECAR_UID)])

    assert response.status_code == 200
    assert captured["include"] == [SIDECAR_UID]
    assert response.json()["items"][0]["includes"] == {SIDECAR_UID: {"is_paper": True}}

    for error, status in ((LookupError("include 'x' is not a visible MetaTable"), 404), (ValueError("not a sidecar"), 400), (includes.SidecarReadError("sidecar could not be read"), 409)):
        def failing(*, uids, include=None, _error=error):
            raise _error
        monkeypatch.setattr("apps.v1.routers.accounts.get_accounts_by_uids", failing)
        assert client.get("/api/v1/account/by-uids/", params={"uid__in": str(account_uid), "include": SIDECAR_UID}).status_code == status


def test_account_lookup_service_hydrates_through_the_includes_service(monkeypatch) -> None:
    from apps.v1.services import accounts as account_service
    from apps.v1.services import lookups

    account_uid = uuid.uuid4()
    monkeypatch.setattr(account_service, "_get_runtime", lambda: SimpleNamespace(context="ctx"))
    monkeypatch.setattr(lookups, "search_model", lambda _c, *, model, in_filters, limit: {"rows": [{"uid": str(account_uid), "unique_identifier": "a", "account_name": "A"}]})
    seen: dict[str, object] = {}

    def fake_hydrate(context, *, model_cls, core_model, items, include, meta_table_lookup=None):
        seen.update(context=context, model_cls=model_cls, core_model=core_model, include=include, items=items)
        return includes.with_includes(model_cls, items, {str(account_uid): {SIDECAR_UID: {"is_paper": True}}})

    monkeypatch.setattr(includes, "hydrate", fake_hydrate)

    rows = account_service.get_accounts_by_uids(uids=[str(account_uid)], include=[SIDECAR_UID])

    assert seen["context"] == "ctx" and seen["core_model"] is AccountTable and seen["model_cls"] is AccountWithIncludes
    assert seen["include"] == [SIDECAR_UID]
    assert rows[0].includes == {SIDECAR_UID: {"is_paper": True}}
