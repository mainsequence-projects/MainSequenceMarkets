"""Find the Markets API deployment and its access credential (ADR 0047, decision 2).

Discovery works as ``metatables.endpoint`` does for MetaTables: the Markets API
is the FastAPI release of the ``MainSequenceMarkets`` CodeRepository in the
caller's Environment, and ``ResourceRelease.resolve_runtime_access`` returns
its URL and a short-lived release token. A caller sees the release when its
workflow grants it ``reader`` on that repository's branch::

    access:
      branches:
        - repository: MainSequenceMarkets
          policy: reader

Overrides, for local development and pinned deployments:

- ``MARKETS_API_URL`` (optionally with ``MARKETS_API_TOKEN``): call this URL;
  without a token the caller's own platform session is sent.
- ``MARKETS_API_RELEASE_UID``: use this release instead of searching for it.
- ``MARKETS_API_RELEASE_NAME`` and ``MARKETS_API_REPOSITORY_NAME``: the release
  name (``api``, from ``source_path: api/main.py``) and repository name
  (``MainSequenceMarkets``) to search for.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

MARKETS_API_URL_ENV = "MARKETS_API_URL"
MARKETS_API_TOKEN_ENV = "MARKETS_API_TOKEN"
MARKETS_API_RELEASE_UID_ENV = "MARKETS_API_RELEASE_UID"
MARKETS_API_RELEASE_NAME_ENV = "MARKETS_API_RELEASE_NAME"
MARKETS_API_REPOSITORY_NAME_ENV = "MARKETS_API_REPOSITORY_NAME"

DEFAULT_RELEASE_NAME = "api"
DEFAULT_REPOSITORY_NAME = "MainSequenceMarkets"
DISCOVERY_TIMEOUT = 30.0
_RUNTIME_ACCESS_REQUEST_TIMEOUT = 20.0


class MarketsApiResolutionError(RuntimeError):
    """The Markets API deployment could not be selected or reached."""


@dataclass(frozen=True)
class MarketsApiEndpoint:
    """Where the Markets API runs and how to authenticate to it."""

    url: str
    release_uid: str | None = None
    headers: Callable[[bool], dict[str, str]] | None = None
    """Return request headers; ``True`` asks for a fresh credential after a 401."""


def resolve_markets_api_endpoint(*, timeout: float = DISCOVERY_TIMEOUT) -> MarketsApiEndpoint:
    """Select the Markets API from the overrides or by discovery in the caller's Environment."""

    explicit = os.environ.get(MARKETS_API_URL_ENV, "").strip()
    if explicit:
        url = validate_url(explicit)
        token = os.environ.get(MARKETS_API_TOKEN_ENV, "").strip()
        if token:
            return MarketsApiEndpoint(url, headers=lambda _force: {"Authorization": f"Bearer {token}"})
        return MarketsApiEndpoint(url, headers=_platform_session_headers)

    release_uid = os.environ.get(MARKETS_API_RELEASE_UID_ENV, "").strip() or None
    if release_uid is None:
        release_uid = _discover_release_uid()
    return _release_endpoint(release_uid, timeout=timeout)


def validate_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise MarketsApiResolutionError(
            "The Markets API URL must be an absolute HTTP(S) URL without credentials, "
            "query or fragment."
        )
    return value.rstrip("/")


def _platform_session_headers(force: bool) -> dict[str, str]:
    from mainsequence.client.utils import loaders

    return dict(loaders.refresh_headers(force=force))


def _discover_release_uid() -> str:
    from mainsequence.client import CodeRepository, CodeRepositoryBranch, ResourceRelease
    from mainsequence.code_repository_context import resolve_organization_environment_uid

    release_name = os.environ.get(MARKETS_API_RELEASE_NAME_ENV, "").strip() or DEFAULT_RELEASE_NAME
    repository_name = (
        os.environ.get(MARKETS_API_REPOSITORY_NAME_ENV, "").strip() or DEFAULT_REPOSITORY_NAME
    )
    environment_uid = str(resolve_organization_environment_uid("Markets API discovery"))
    candidates = [
        release
        for release in ResourceRelease.filter_admin(
            name=release_name, release_kind="fastapi", timeout=30
        )
        if getattr(release, "name", None) == release_name and getattr(release, "uid", None)
    ]
    branch_uids = sorted(
        {str(release.code_repository_branch_uid) for release in candidates if release.code_repository_branch_uid}
    )
    branches = {
        str(branch.uid): branch
        for branch in (CodeRepositoryBranch.filter(uid__in=branch_uids, timeout=30) if branch_uids else [])
    }
    repository_names: dict[str, str] = {}
    matches = []
    for release in candidates:
        branch = branches.get(str(release.code_repository_branch_uid))
        if branch is None or str(branch.organization_environment_uid) != environment_uid:
            continue
        repository_uid = str(branch.code_repository_uid)
        if repository_uid not in repository_names:
            repository = CodeRepository.get(uid=repository_uid)
            repository_names[repository_uid] = str(getattr(repository, "code_repository_name", ""))
        if repository_names[repository_uid] == repository_name:
            matches.append(release)
    if not matches:
        raise MarketsApiResolutionError(
            f"No visible Markets API (FastAPI release {release_name!r} of {repository_name!r}) in "
            f"Environment {environment_uid}. Grant this workload reader on the {repository_name} "
            f"branch in its workflow, or set {MARKETS_API_RELEASE_UID_ENV}."
        )
    if len(matches) != 1:
        raise MarketsApiResolutionError(
            f"More than one Markets API in Environment {environment_uid}; set "
            f"{MARKETS_API_RELEASE_UID_ENV} to choose one."
        )
    return str(matches[0].uid)


def _release_endpoint(release_uid: str, *, timeout: float) -> MarketsApiEndpoint:
    access = _release_access(release_uid, timeout=timeout)
    url = validate_url(str(access["rpc_url"]))
    state: dict[str, Any] = {"token": access["token"]}

    def headers(force: bool) -> dict[str, str]:
        if force:
            refreshed = _release_access(release_uid, timeout=timeout)
            if validate_url(str(refreshed["rpc_url"])) != url:
                raise MarketsApiResolutionError(
                    "The Markets API endpoint changed; create a new client."
                )
            state["token"] = refreshed["token"]
        from mainsequence.client.utils import SessionJWTAuthProvider

        return dict(SessionJWTAuthProvider(access_token=state["token"], refresh_token="").get_headers())

    return MarketsApiEndpoint(url, release_uid=release_uid, headers=headers)


def _release_access(release_uid: str, *, timeout: float) -> dict[str, Any]:
    from mainsequence.client import ResourceRelease
    from mainsequence.client.exceptions import TransportError

    release = ResourceRelease(uid=release_uid, release_kind="fastapi")
    deadline = time.monotonic() + timeout
    last_state = "no answer"
    while True:
        if time.monotonic() >= deadline:
            raise MarketsApiResolutionError(
                f"The Markets API did not become available within {timeout:g} s "
                f"(last state: {last_state})."
            )
        try:
            result = release.resolve_runtime_access(timeout=_RUNTIME_ACCESS_REQUEST_TIMEOUT)
        except TransportError as exc:
            last_state = type(exc).__name__
            time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
            continue
        admission = result.runtime_access
        if admission.state == "ready" and admission.can_request and result.routing.state == "routable":
            access = result.access
            if (
                not isinstance(access, dict)
                or access.get("mode") != "token"
                or not isinstance(access.get("rpc_url"), str)
                or not str(access.get("token") or "").strip()
            ):
                raise MarketsApiResolutionError("The Markets API returned no usable endpoint or token.")
            return access
        if admission.state != "waking":
            raise MarketsApiResolutionError(
                f"The Markets API is unavailable (state {admission.state!r}); check its deployment."
            )
        last_state = admission.state
        delay = max(0.05, (admission.retry_after_ms or 250) / 1000)
        time.sleep(min(delay, max(0.0, deadline - time.monotonic())))


__all__ = [
    "DEFAULT_RELEASE_NAME",
    "DEFAULT_REPOSITORY_NAME",
    "MARKETS_API_RELEASE_NAME_ENV",
    "MARKETS_API_RELEASE_UID_ENV",
    "MARKETS_API_REPOSITORY_NAME_ENV",
    "MARKETS_API_TOKEN_ENV",
    "MARKETS_API_URL_ENV",
    "MarketsApiEndpoint",
    "MarketsApiResolutionError",
    "resolve_markets_api_endpoint",
    "validate_url",
]
