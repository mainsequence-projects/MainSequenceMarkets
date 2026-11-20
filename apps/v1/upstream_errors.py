"""Answer a refused or failed call to an API this deployment depends on (MainSequenceMarkets#84).

Every row a route reads or writes goes through the MetaTables API, and the SDK raises
``mainsequence.client.exceptions.ApiError`` or a subclass when that API, or another
Main Sequence API the deployment calls, answers with an error. A route that does not
handle the exception itself gets one answer here, for every router:

- ``500`` when MetaTables rejected a statement the Markets API compiled as invalid
  (MainSequenceMarkets#87): the fault is the Markets API's, and the same request
  fails the same way again. ``error_type`` is ``InvalidStatementError``;
- ``502`` when the upstream API refused the call for any other reason (its status was
  4xx: permissions, a missing table, a conflict);
- ``503`` when it failed or could not be reached (5xx, ``429``, no answer, or the
  MetaTables API could not be located), which a caller may try again.

The body is ``{"detail", "error_type", "upstream_status"}``, with ``error_type``
``UpstreamApiError`` for ``502`` and ``503``. ``detail`` carries the reason the
upstream API gave and nothing else from the exchange: not the request, whose SQL and
values the SDK keeps on the exception, and not the values a validation error echoes
back.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mainsequence.client.exceptions import ApiError
from metatables.endpoint import ApiResolutionError
from msm.api.remote import INVALID_STATEMENT_ERROR_TYPE, UPSTREAM_ERROR_TYPE

logger = logging.getLogger(__name__)

MAX_REASON_CHARACTERS = 1000

INVALID_STATEMENT_CODES = frozenset(
    {
        # The database rejected the statement. MetaTables answers every database error
        # running a compiled statement with this code and no SQLSTATE, so a syntax
        # error and a constraint the statement breaks are the same answer.
        "compiled_sql_database_error",
        # MetaTables' checks of the compiled statement before it runs.
        "compiled_sql_dialect_mismatch",
        "compiled_sql_statement_list_requires_write",
        "compiled_sql_statement_list_size",
        "compiled_sql_statement_list_unsupported",
        "compiled_sql_transaction_ended",
        "empty_sql",
        "invalid_query_limits",
        "invalid_sql",
        "invalid_sql_parameters",
    }
)
"""MetaTables codes for a compiled statement it rejects as invalid.

The ``code`` of a 4xx answer from ``/meta-tables/execute-operation/``,
``/meta-tables/execute-transaction/`` and ``/meta-tables/run-query/``
(MetaTables 0.1.71, ``metatables.api.app.routes.table_sql``). MetaTables' other
codes there refuse the caller or the table (``sql_scope_denied``,
``relation_read_denied``, ``compiled_sql_guard_failed``, ...) and stay ``502``.
"""

_URL_CREDENTIALS = re.compile(r"(?<=://)[^\s/@]+@")


def install_upstream_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _upstream_api_error)
    app.add_exception_handler(ApiResolutionError, _upstream_unreachable)


def _upstream_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    upstream_status = exc.status_code if isinstance(exc.status_code, int) else None
    refused = upstream_status is not None and 400 <= upstream_status < 500 and upstream_status != 429
    reason = upstream_reason(exc)
    if refused and upstream_code(exc) in INVALID_STATEMENT_CODES:
        logger.error(
            "The Markets API sent an invalid statement: %s %s answered %s: %s",
            exc.method,
            exc.url,
            upstream_status,
            reason,
        )
        detail = (
            "The Markets API sent a statement the upstream API rejects as invalid. "
            "This is a fault of the Markets API; a retry fails the same way. "
            f"The upstream API answered {upstream_status}: {reason}"
        )
        return _answer(500, detail, upstream_status, {}, INVALID_STATEMENT_ERROR_TYPE)
    logger.warning(
        "Upstream API call failed: %s %s answered %s: %s", exc.method, exc.url, upstream_status, reason
    )
    if upstream_status is None:
        detail = f"The upstream API did not answer: {reason}"
    else:
        detail = f"The upstream API answered {upstream_status}: {reason}"
    headers = {}
    retry_after = getattr(exc, "retry_after", None) or (exc.headers or {}).get("Retry-After")
    if not refused and retry_after:
        headers["Retry-After"] = str(retry_after)
    return _answer(502 if refused else 503, detail, upstream_status, headers)


def _upstream_unreachable(_request: Request, exc: ApiResolutionError) -> JSONResponse:
    reason = _safe(str(exc))
    logger.warning("The MetaTables API could not be reached: %s", reason)
    return _answer(503, f"The MetaTables API could not be reached: {reason}", None, {})


def _answer(
    status_code: int,
    detail: str,
    upstream_status: int | None,
    headers: Mapping[str, str],
    error_type: str = UPSTREAM_ERROR_TYPE,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "error_type": error_type,
            "upstream_status": upstream_status,
        },
        headers=dict(headers) or None,
    )


def upstream_reason(exc: ApiError) -> str:
    """The reason the upstream API gave, from its answer's ``detail``."""

    detail = _answer_detail(exc.response)
    if isinstance(detail, str):
        reason = detail
    elif isinstance(detail, Mapping):
        # MetaTables: {"code": ..., "detail": ...}, with the failing statement of a list.
        parts = [detail.get("code"), detail.get("detail") or detail.get("message")]
        reason = ": ".join(str(part) for part in parts if part)
        if detail.get("statement_index") is not None:
            reason += f" (statement {detail['statement_index']})"
    elif isinstance(detail, list):
        # Request validation: where and why, never the value that was sent.
        reason = "; ".join(
            f"{'.'.join(str(part) for part in item.get('loc', ()))}: {item.get('msg')}"
            for item in detail
            if isinstance(item, Mapping)
        )
    else:
        reason = str(exc.args[0]) if exc.args else ""
    return _safe(reason)


def upstream_code(exc: ApiError) -> str | None:
    """The ``code`` the upstream API answered with, if it gave one.

    MetaTables sends it as ``{"detail": {"code": ...}}``, or as the whole ``detail``
    for a few refusals, such as ``compiled_sql_dialect_mismatch``.
    """

    detail = _answer_detail(exc.response)
    if isinstance(detail, Mapping):
        code = detail.get("code")
        return code if isinstance(code, str) else None
    return detail if isinstance(detail, str) else None


def _answer_detail(response: Any) -> Any:
    try:
        body = response.json()
    except Exception:
        return None
    return body.get("detail") if isinstance(body, Mapping) else None


def _safe(reason: str) -> str:
    reason = _URL_CREDENTIALS.sub("***@", " ".join(reason.split()))
    if len(reason) > MAX_REASON_CHARACTERS:
        reason = reason[:MAX_REASON_CHARACTERS] + "..."
    return reason or "no reason given"


__all__ = [
    "INVALID_STATEMENT_CODES",
    "install_upstream_error_handlers",
    "upstream_code",
    "upstream_reason",
]
