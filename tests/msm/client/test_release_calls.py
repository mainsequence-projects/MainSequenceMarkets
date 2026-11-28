"""``MarketsClient`` sends each call to the Markets API release through ``ResourceRelease.call``.

The platform's runtime-access answers are faked on ``ResourceRelease``, and the HTTP client is
a recording session, so nothing leaves the process. Each answer issues a new token, so the
``Authorization`` a call carries shows whether it reused the access this process kept.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mainsequence import logconf
from mainsequence.client import (
    ReleaseReadinessTimeoutError,
    ReleaseUnavailableError,
    ResourceRelease,
    release_runtime_cache,
)
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags

from msm.api.remote import MarketsAccessError
from msm.client import MarketsClient

RELEASE_UID = "6f0c2a4e-1b7d-4c3e-9a5f-8d2e7b1c4a90"
ROW_PATH = "/api/v1/rows/asset/get_by_uid/"
CALLER_TRACE_ID = 0x4BF92F3577B34DA6A3CE929D0E0E4736
CALLER_SPAN_ID = 0x00F067AA0BA902B7


@pytest.fixture
def platform(monkeypatch):
    """The platform's answers about the release: admitted, each with a new token.

    ``state["waking"]`` answers that many asks ``waking``, with a retry hint, first.
    """

    release_runtime_cache.clear()
    asked: list[str] = []
    state = {"admitted": True, "waking": 0}

    def resolve_runtime_access(self, *, static_site_release_uid=None, timeout=None):
        asked.append(str(self.uid))
        if state["waking"]:
            state["waking"] -= 1
            return SimpleNamespace(
                runtime_access=SimpleNamespace(state="waking", can_request=False, retry_after_ms=10),
                runtime_presence=None,
                scaling=None,
                access=None,
            )
        if not state["admitted"]:
            return SimpleNamespace(
                runtime_access=SimpleNamespace(state="unavailable", can_request=False, retry_after_ms=None),
                runtime_presence=None,
                scaling=None,
                access=None,
            )
        return SimpleNamespace(
            runtime_access=SimpleNamespace(state="ready", can_request=True, retry_after_ms=None),
            runtime_presence=None,
            scaling=None,
            access={"mode": "token", "rpc_url": "https://markets.example/", "token": f"token-{len(asked)}"},
        )

    monkeypatch.setattr(ResourceRelease, "resolve_runtime_access", resolve_runtime_access)
    yield SimpleNamespace(asked=asked, state=state)
    release_runtime_cache.clear()


@pytest.fixture
def dependency_lines(monkeypatch):
    """The ``dependency.call.*`` lines the SDK writes through its logger."""

    lines: list[tuple[str, dict]] = []

    class Recorder:
        def info(self, event, **fields):
            lines.append((event, fields))

        def warning(self, event, **fields):
            lines.append((event, fields))

        def __getattr__(self, name):
            return lambda *args, **kwargs: None

    monkeypatch.setattr(logconf, "logger", Recorder())
    return lines


class Session:
    """Answers each request with the next status, 200 once they run out, and records it."""

    def __init__(self, *statuses: int) -> None:
        self.statuses = list(statuses)
        self.sent: list[SimpleNamespace] = []

    def request(self, method, url, *, json=None, params=None, headers=None, timeout=None):
        self.sent.append(SimpleNamespace(method=method, url=url, headers=dict(headers or {}), timeout=timeout))
        status = self.statuses.pop(0) if self.statuses else 200
        return SimpleNamespace(status_code=status, headers={}, json=lambda: {"result": "ok", "detail": "refused"})


def _dependency_lines(lines):
    return [fields for event, fields in lines if event.startswith("dependency.call.")]


def _row_call(client: MarketsClient):
    return client.run_row_operation("asset", "get_by_uid", {"uid": "x"})


def test_a_call_is_a_span_of_the_callers_trace(platform, dependency_lines) -> None:
    session = Session()
    client = MarketsClient(release_uid=RELEASE_UID, session=session)
    caller = SpanContext(
        CALLER_TRACE_ID, CALLER_SPAN_ID, is_remote=False, trace_flags=TraceFlags(TraceFlags.SAMPLED)
    )

    with trace.use_span(NonRecordingSpan(caller)):
        assert _row_call(client) == "ok"

    (sent,) = session.sent
    assert sent.method == "POST"
    assert sent.url == "https://markets.example" + ROW_PATH
    _, trace_id, span_id, _ = sent.headers["traceparent"].split("-")
    assert trace_id == f"{CALLER_TRACE_ID:032x}"
    assert span_id != f"{CALLER_SPAN_ID:016x}"
    assert sent.headers["Authorization"] == "Bearer token-1"
    assert sent.headers["Mainsequence-Request-Timeout-Ms"] == "60000"
    assert sent.timeout == 60.0
    (line,) = _dependency_lines(dependency_lines)
    assert line["span_id"] == span_id
    assert line["parent_span_id"] == f"{CALLER_SPAN_ID:016x}"
    assert line["dependency_type"] == "release"
    assert line["dependency_name"] == RELEASE_UID
    assert line["route"] == ROW_PATH
    assert line["status_code"] == 200


def test_calls_to_a_warm_release_ask_the_platform_once(platform) -> None:
    session = Session()
    client = MarketsClient(release_uid=RELEASE_UID, session=session)

    _row_call(client)
    _row_call(client)

    assert platform.asked == [RELEASE_UID]
    assert [sent.headers["Authorization"] for sent in session.sent] == ["Bearer token-1"] * 2


def test_a_401_to_the_kept_token_sends_the_write_once_more_with_a_new_token(
    platform, dependency_lines
) -> None:
    session = Session(200, 401, 200)
    client = MarketsClient(release_uid=RELEASE_UID, session=session)

    _row_call(client)
    assert _row_call(client) == "ok"

    assert [sent.method for sent in session.sent] == ["POST"] * 3
    assert [sent.headers["Authorization"] for sent in session.sent] == [
        "Bearer token-1",
        "Bearer token-1",
        "Bearer token-2",
    ]
    assert platform.asked == [RELEASE_UID, RELEASE_UID]
    assert [line["status_code"] for line in _dependency_lines(dependency_lines)] == [200, 401, 200]


def test_a_401_to_a_new_token_is_the_answer(platform) -> None:
    session = Session(401)
    client = MarketsClient(release_uid=RELEASE_UID, session=session)

    with pytest.raises(MarketsAccessError):
        _row_call(client)

    assert len(session.sent) == 1
    assert platform.asked == [RELEASE_UID]


def test_a_starting_release_is_called_once_it_is_ready(platform) -> None:
    platform.state["waking"] = 2
    session = Session()
    client = MarketsClient(release_uid=RELEASE_UID, session=session)

    assert _row_call(client) == "ok"

    assert platform.asked == [RELEASE_UID] * 3
    assert len(session.sent) == 1


def test_a_release_still_starting_raises_the_sdks_error_and_sends_nothing(platform, monkeypatch) -> None:
    monkeypatch.setenv("MAINSEQUENCE_RELEASE_READY_TIMEOUT_SECONDS", "0.2")
    platform.state["waking"] = 10_000
    session = Session()
    client = MarketsClient(release_uid=RELEASE_UID, session=session)

    with pytest.raises(ReleaseReadinessTimeoutError):
        _row_call(client)

    assert session.sent == []


def test_an_unavailable_release_raises_the_sdks_error_and_sends_nothing(platform) -> None:
    platform.state["admitted"] = False
    session = Session()
    client = MarketsClient(release_uid=RELEASE_UID, session=session)

    with pytest.raises(ReleaseUnavailableError):
        _row_call(client)

    assert session.sent == []


def test_an_explicit_url_carries_no_trace_context(dependency_lines) -> None:
    session = Session()
    client = MarketsClient(
        "http://127.0.0.1:8000", headers=lambda _force: {"Authorization": "Bearer local"}, session=session
    )
    caller = SpanContext(
        CALLER_TRACE_ID, CALLER_SPAN_ID, is_remote=False, trace_flags=TraceFlags(TraceFlags.SAMPLED)
    )

    with trace.use_span(NonRecordingSpan(caller)):
        _row_call(client)

    (sent,) = session.sent
    assert sent.url == "http://127.0.0.1:8000" + ROW_PATH
    assert sent.headers == {"Authorization": "Bearer local"}
    assert _dependency_lines(dependency_lines) == []


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"base_url": "http://127.0.0.1:8000", "release_uid": RELEASE_UID},
        {"release_uid": RELEASE_UID, "headers": lambda _force: {}},
    ],
)
def test_a_client_is_for_one_address_or_one_release(arguments) -> None:
    with pytest.raises(ValueError):
        MarketsClient(**arguments)
