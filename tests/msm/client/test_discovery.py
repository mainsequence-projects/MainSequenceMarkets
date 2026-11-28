"""``msm.client`` finds the Markets API the way MetaTables finds its own API."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from msm.client import MarketsClient, discovery

ENVIRONMENT = "env-1"
OTHER_ENVIRONMENT = "env-2"


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in (
        discovery.MARKETS_API_URL_ENV,
        discovery.MARKETS_API_TOKEN_ENV,
        discovery.MARKETS_API_RELEASE_UID_ENV,
        discovery.MARKETS_API_RELEASE_NAME_ENV,
        discovery.MARKETS_API_REPOSITORY_NAME_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def _platform(monkeypatch, *, releases, branches, repositories):
    import mainsequence.client as client_module
    import mainsequence.code_repository_context as context_module

    access_calls: list[str] = []

    class FakeRelease:
        @staticmethod
        def filter_admin(*, name, release_kind, timeout):
            return [release for release in releases if release.name == name]

        def __init__(self, uid, release_kind):
            self.uid = uid

        def resolve_runtime_access(self, timeout):
            access_calls.append(self.uid)
            raise AssertionError("discovery names the release; it asks for no runtime access")

    monkeypatch.setattr(client_module, "ResourceRelease", FakeRelease)
    monkeypatch.setattr(
        client_module,
        "CodeRepositoryBranch",
        SimpleNamespace(filter=lambda *, uid__in, timeout: [b for b in branches if b.uid in uid__in]),
    )
    monkeypatch.setattr(
        client_module,
        "CodeRepository",
        SimpleNamespace(get=lambda *, uid: SimpleNamespace(code_repository_name=repositories[uid])),
    )
    monkeypatch.setattr(
        context_module, "resolve_organization_environment_uid", lambda operation: ENVIRONMENT
    )
    return access_calls


def _release(uid: str, branch: str, name: str = "api") -> Any:
    return SimpleNamespace(uid=uid, name=name, code_repository_branch_uid=branch)


def _branch(uid: str, repository: str, environment: str = ENVIRONMENT) -> Any:
    return SimpleNamespace(uid=uid, code_repository_uid=repository, organization_environment_uid=environment)


def test_explicit_url_and_token(monkeypatch) -> None:
    monkeypatch.setenv(discovery.MARKETS_API_URL_ENV, "http://127.0.0.1:8000/")
    monkeypatch.setenv(discovery.MARKETS_API_TOKEN_ENV, "local-token")

    endpoint = discovery.resolve_markets_api_endpoint()

    assert endpoint.url == "http://127.0.0.1:8000"
    assert endpoint.release_uid is None
    assert endpoint.headers(False) == {"Authorization": "Bearer local-token"}


def test_rejects_urls_with_credentials(monkeypatch) -> None:
    monkeypatch.setenv(discovery.MARKETS_API_URL_ENV, "https://user:pw@markets.example")

    with pytest.raises(discovery.MarketsApiResolutionError):
        discovery.resolve_markets_api_endpoint()


def test_discovers_the_markets_release_of_the_callers_environment(monkeypatch) -> None:
    calls = _platform(
        monkeypatch,
        releases=[
            _release("markets-env-1", "b1"),
            _release("markets-env-2", "b2"),
            _release("other-api", "b3"),
            _release("provider-app", "b4", name="app"),
        ],
        branches=[
            _branch("b1", "markets-repo"),
            _branch("b2", "markets-repo", OTHER_ENVIRONMENT),
            _branch("b3", "other-repo"),
            _branch("b4", "provider-repo"),
        ],
        repositories={
            "markets-repo": "MainSequenceMarkets",
            "other-repo": "SomethingElse",
            "provider-repo": "Provider",
        },
    )

    endpoint = discovery.resolve_markets_api_endpoint()

    assert endpoint == discovery.MarketsApiEndpoint(release_uid="markets-env-1")
    assert calls == []


def test_no_visible_markets_api_names_the_workflow_grant(monkeypatch) -> None:
    _platform(
        monkeypatch,
        releases=[_release("other-api", "b3")],
        branches=[_branch("b3", "other-repo")],
        repositories={"other-repo": "SomethingElse"},
    )

    with pytest.raises(discovery.MarketsApiResolutionError, match="reader on the MainSequenceMarkets"):
        discovery.resolve_markets_api_endpoint()


def test_two_markets_apis_in_one_environment_need_a_pinned_release(monkeypatch) -> None:
    _platform(
        monkeypatch,
        releases=[_release("a", "b1"), _release("b", "b2")],
        branches=[_branch("b1", "markets-repo"), _branch("b2", "markets-repo")],
        repositories={"markets-repo": "MainSequenceMarkets"},
    )

    with pytest.raises(discovery.MarketsApiResolutionError, match="MARKETS_API_RELEASE_UID"):
        discovery.resolve_markets_api_endpoint()


def test_a_pinned_release_skips_the_search(monkeypatch) -> None:
    monkeypatch.setenv(discovery.MARKETS_API_RELEASE_UID_ENV, "pinned")
    _platform(monkeypatch, releases=[], branches=[], repositories={})

    assert discovery.resolve_markets_api_endpoint().release_uid == "pinned"


def test_a_client_from_the_environment_calls_the_release(monkeypatch) -> None:
    monkeypatch.setenv(discovery.MARKETS_API_RELEASE_UID_ENV, "pinned")
    calls = _platform(monkeypatch, releases=[], branches=[], repositories={})

    client = MarketsClient.from_environment()

    assert client.release_uid == "pinned"
    assert client.base_url is None
    assert calls == []


def test_an_explicit_url_overrides_the_release(monkeypatch) -> None:
    monkeypatch.setenv(discovery.MARKETS_API_URL_ENV, "http://127.0.0.1:8000/")
    monkeypatch.setenv(discovery.MARKETS_API_RELEASE_UID_ENV, "pinned")

    client = MarketsClient.from_environment()

    assert client.base_url == "http://127.0.0.1:8000"
    assert client.release_uid is None


def test_lazy_backend_finds_the_api_on_its_first_call_only() -> None:
    from msm.client import LazyRemoteBackend

    created: list[int] = []

    class Client:
        def run_row_operation(self, resource, operation, arguments):
            return (resource, operation, dict(arguments))

    def factory():
        created.append(1)
        return Client()

    backend = LazyRemoteBackend(factory)
    assert created == []
    assert backend.call("asset", "get_by_uid", {"uid": "x"}) == ("asset", "get_by_uid", {"uid": "x"})
    backend.call("asset", "get_by_uid", {"uid": "y"})
    assert created == [1]


def test_msm_api_backend_env_selects_a_lazy_backend(monkeypatch) -> None:
    from msm.api import remote
    from msm.client import LazyRemoteBackend

    monkeypatch.setenv(remote.MSM_API_BACKEND_ENV, "remote")
    monkeypatch.setattr(remote, "_remote_backend", None)
    monkeypatch.setattr(
        "msm.client.MarketsClient.from_environment",
        classmethod(lambda cls: pytest.fail("discovery must wait for the first row call")),
    )
    try:
        assert isinstance(remote.active_remote_backend(), LazyRemoteBackend)
    finally:
        remote.use_runtime_backend()
