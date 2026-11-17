"""Answer a refused or failed call to an API this deployment depends on (MainSequenceMarkets#84).

Every row a route reads or writes goes through the MetaTables API, and the SDK raises
``mainsequence.client.exceptions.ApiError`` or a subclass when that API, or another
Main Sequence API the deployment calls, answers with an error. A route that does not
handle the exception itself gets one answer here, for every router:

- ``502`` when the upstream API refused the call (its status was 4xx);
- ``503`` when it failed or could not be reached (5xx, ``429``, no answer, or the
  MetaTables API could not be located), which a caller may try again.

The body is ``{"detail", "error_type": "UpstreamApiError", "upstream_status"}``.
``detail`` carries the reason the upstream API gave and nothing else from the
exchange: not the request, whose SQL and values the SDK keeps on the exception, and
not the values a validation error echoes back.
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
from msm.api.remote import UPSTREAM_ERROR_TYPE

logger = logging.getLogger(__name__)

MAX_REASON_CHARACTERS = 1000
_URL_CREDENTIALS = re.compile(r"(?<=://)[^\s/@]+@")


def install_upstream_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _upstream_api_error)
    app.add_exception_handler(ApiResolutionError, _upstream_unreachable)


def _upstream_api_error(_request: Request, exc: ApiError) -> JSONResponse:
    upstream_status = exc.status_code if isinstance(exc.status_code, int) else None
    refused = upstream_status is not None and 400 <= upstream_status < 500 and upstream_status != 429
    reason = upstream_reason(exc)
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
    status_code: int, detail: str, upstream_status: int | None, headers: Mapping[str, str]
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "detail": detail,
            "error_type": UPSTREAM_ERROR_TYPE,
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


__all__ = ["install_upstream_error_handlers", "upstream_reason"]
