"""How many MetaTables operations each request sent, in the log (issue 94).

A request's time is mostly those operations, one after another, so their number says
whether a slow request sent too many or each was slow. The count goes to two places:

- ``scope["state"]["platform_log_fields"]``, which the platform launcher copies into the
  request's "HTTP request completed" line, as MetaTables does with its timings;
- one line of our own for a request that sent any, with the count in its message: the
  hosted log API returns a line's message and not its other fields.

The line names the route's template, never the path's uids or the query.
"""

from __future__ import annotations

import time
from typing import Any

from mainsequence.logconf import logger as _mainsequence_logger
from msm.repositories.operation_count import OperationCount, counting_operations

logger = _mainsequence_logger.bind(sub_application="markets", component="api")


class OperationCountMiddleware:
    """Count each HTTP request's MetaTables operations and log them when it ends."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        status = 500  # what an exception no handler answers becomes

        async def send_status(message: Any) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        started = time.perf_counter()
        with counting_operations() as count:
            try:
                await self.app(scope, receive, send_status)
            finally:
                _record(scope, count, status=status, seconds=time.perf_counter() - started)


def _record(scope: Any, count: OperationCount, *, status: int, seconds: float) -> None:
    state = scope.setdefault("state", {})
    fields = state.get("platform_log_fields")
    if not isinstance(fields, dict):
        fields = state["platform_log_fields"] = {}
    fields["metatables_operations"] = count.operations
    if not count.operations:
        return
    method = scope.get("method", "")
    route = getattr(scope.get("route"), "path", "unmatched")
    duration_ms = round(seconds * 1000)
    logger.info(
        f"MetaTables operations={count.operations} {method} {route} "
        f"status={status} duration_ms={duration_ms}",
        metatables_operations=count.operations,
        http_method=method,
        route=route,
        status_code=status,
        duration_ms=duration_ms,
    )


__all__ = ["OperationCountMiddleware"]
