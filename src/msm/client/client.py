"""HTTP client and remote row backend for the Markets API (ADR 0047, decision 2)."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from msm.api.remote import MarketsApiError, raise_for_error
from msm.client.discovery import MarketsApiEndpoint, resolve_markets_api_endpoint

API_PREFIX = "/api/v1"
DEFAULT_TIMEOUT = 60.0
VALUES_PAGE_SIZE = 5000
"""Largest ``limit`` one ``GET /portfolio/values/`` request accepts."""


class MarketsClient:
    """Calls one Markets API deployment as the current process's identity.

    ``session`` is any object with ``request(method, url, json=..., params=...,
    headers=...)`` returning a response with ``status_code`` and ``json()``: an
    ``httpx.Client`` with ``timeout`` by default, or FastAPI's ``TestClient`` in
    tests. The client never builds or forwards identity itself; the platform
    authenticates the release token or session it sends.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: Callable[[bool], Mapping[str, str]] | None = None,
        session: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = str(base_url).rstrip("/")
        self._headers = headers or (lambda _force: {})
        self._session = session
        self._session_lock = threading.Lock()
        self.timeout = timeout

    @classmethod
    def from_environment(cls, *, timeout: float = DEFAULT_TIMEOUT) -> MarketsClient:
        """Discover the Environment's Markets API, or use ``MARKETS_API_URL``."""

        endpoint: MarketsApiEndpoint = resolve_markets_api_endpoint()
        return cls(endpoint.url, headers=endpoint.headers, timeout=timeout)

    @property
    def backend(self) -> RemoteRowBackend:
        """The remote backend for ``msm.api.remote.use_remote_backend``."""

        return RemoteRowBackend(self)

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        params: Mapping[str, Any] | Sequence[tuple[str, Any]] | None = None,
    ) -> Any:
        """Send one request; re-raise failures as the row API's exceptions."""

        url = f"{self.base_url}{path}"
        response = self._send(method, url, json=json, params=params, force=False)
        if response.status_code == 401:
            response = self._send(method, url, json=json, params=params, force=True)
        if response.status_code >= 400:
            detail, error_type = _error_detail(response)
            raise_for_error(response.status_code, detail, error_type)
        if response.status_code == 204:
            return None
        return response.json()

    def run_row_operation(self, resource: str, operation: str, arguments: Mapping[str, Any]) -> Any:
        payload = self.request(
            "POST",
            f"{API_PREFIX}/rows/{resource}/{operation}/",
            json={"arguments": dict(arguments)},
        )
        if not isinstance(payload, Mapping) or "result" not in payload:
            raise MarketsApiError(f"Markets API returned no result for {resource}.{operation}.")
        return payload["result"]

    def describe_row_operations(self) -> list[dict[str, Any]]:
        return list(self.request("GET", f"{API_PREFIX}/rows/"))

    def portfolio_values(
        self,
        portfolio_uids: Sequence[Any],
        *,
        start_date: dt.datetime | None = None,
        end_date: dt.datetime | None = None,
        order: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        as_pandas: bool = False,
    ) -> Any:
        """Values of several portfolios, read from their catalogued tables by the Markets API.

        A ``limit`` above ``VALUES_PAGE_SIZE`` is read in pages of that size and
        returned as one frame.
        """

        params: list[tuple[str, Any]] = [("portfolio_uid__in", str(uid)) for uid in portfolio_uids]
        for name, value in (("start_date", start_date), ("end_date", end_date), ("order", order)):
            if value is not None:
                params.append((name, value.isoformat() if isinstance(value, dt.datetime) else value))
        if limit is None or limit <= VALUES_PAGE_SIZE:
            page_params = list(params)
            if limit is not None:
                page_params.append(("limit", limit))
            if offset:
                page_params.append(("offset", offset))
            frame = self.request("GET", f"{API_PREFIX}/portfolio/values/", params=page_params)
            return tabular_frame_to_pandas(frame) if as_pandas else frame

        frame: dict[str, Any] | None = None
        rows: list[Any] = []
        while len(rows) < limit:
            size = min(VALUES_PAGE_SIZE, limit - len(rows))
            page = self.request(
                "GET",
                f"{API_PREFIX}/portfolio/values/",
                params=[*params, ("limit", size), ("offset", offset + len(rows))],
            )
            frame = frame or dict(page)
            page_rows = list(page.get("rows") or [])
            rows.extend(page_rows)
            if len(page_rows) < size:
                break
        frame = {**(frame or {}), "rows": rows}
        return tabular_frame_to_pandas(frame) if as_pandas else frame

    def portfolio_weights(
        self,
        portfolio_uids: Sequence[Any],
        *,
        weights_date: dt.datetime | None = None,
        as_of: bool = True,
        as_pandas: bool = False,
    ) -> Any:
        """One weights snapshot per portfolio, read from their catalogued tables by the Markets API."""

        params: list[tuple[str, Any]] = [("portfolio_uid__in", str(uid)) for uid in portfolio_uids]
        if weights_date is not None:
            params.append(("weights_date", weights_date.isoformat()))
            params.append(("as_of", "true" if as_of else "false"))
        frame = self.request("GET", f"{API_PREFIX}/portfolio/weights/", params=params)
        return tabular_frame_to_pandas(frame) if as_pandas else frame

    def _send(self, method: str, url: str, *, json: Any, params: Any, force: bool) -> Any:
        headers = dict(self._headers(force))
        return self._client().request(method, url, json=json, params=params, headers=headers)

    def _client(self) -> Any:
        if self._session is None:
            with self._session_lock:
                if self._session is None:
                    import httpx

                    self._session = httpx.Client(timeout=self.timeout)
        return self._session


class RemoteRowBackend:
    """Runs ``msm.api`` row operations on the Markets API (``msm.api.remote.RemoteBackend``)."""

    def __init__(self, client: MarketsClient) -> None:
        self.client = client

    def call(self, resource: str, operation: str, arguments: Mapping[str, Any]) -> Any:
        return self.client.run_row_operation(resource, operation, arguments)


class LazyRemoteBackend:
    """A remote backend that finds the Markets API on its first row call.

    Selecting the remote backend at process start then costs nothing, and a process
    that never touches a Markets registry never needs to see the Markets API.
    """

    def __init__(self, factory: Callable[[], MarketsClient] | None = None) -> None:
        self._factory = factory or MarketsClient.from_environment
        self._client: MarketsClient | None = None
        self._lock = threading.Lock()

    @property
    def client(self) -> MarketsClient:
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = self._factory()
        return self._client

    def call(self, resource: str, operation: str, arguments: Mapping[str, Any]) -> Any:
        return self.client.run_row_operation(resource, operation, arguments)


def tabular_frame_to_pandas(frame: Mapping[str, Any]) -> Any:
    """Build a pandas DataFrame from a ``core.tabular_frame@v1`` response."""

    import pandas as pd

    columns = list(frame.get("columns") or [])
    return pd.DataFrame(list(frame.get("rows") or []), columns=columns or None)


def _error_detail(response: Any) -> tuple[str, str | None]:
    try:
        body = response.json()
    except Exception:
        return getattr(response, "text", "") or f"HTTP {response.status_code}", None
    if isinstance(body, Mapping):
        detail = body.get("detail")
        if not isinstance(detail, str):
            detail = str(detail)
        error_type = body.get("error_type")
        return detail, str(error_type) if error_type else None
    return str(body), None


__all__ = [
    "API_PREFIX",
    "LazyRemoteBackend",
    "MarketsClient",
    "RemoteRowBackend",
    "tabular_frame_to_pandas",
]
