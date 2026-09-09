"""Structured, sanitized FastAPI errors for provider HTTP adapters."""

from __future__ import annotations

from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from ._base import HttpContractModel


class ErrorResponse(HttpContractModel):
    """Compatibility model for existing endpoints whose error detail is plain text."""

    detail: str


class ApiErrorDetail(HttpContractModel):
    """Machine-readable error detail safe to return across a provider boundary."""

    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(pattern=r".*\S.*")
    retryable: bool = False


class ApiErrorResponse(HttpContractModel):
    detail: ApiErrorDetail


def api_error(
    *,
    status_code: int,
    code: str,
    message: str,
    retryable: bool = False,
) -> HTTPException:
    """Create a structured HTTP exception without exposing an underlying exception."""

    detail = ApiErrorDetail(code=code, message=message, retryable=retryable)
    return HTTPException(status_code=status_code, detail=detail.model_dump())


def bad_request(message: str) -> HTTPException:
    return api_error(status_code=400, code="bad_request", message=message)


def not_found(message: str) -> HTTPException:
    return api_error(status_code=404, code="not_found", message=message)


def conflict(message: str) -> HTTPException:
    return api_error(status_code=409, code="conflict", message=message)


def dependency_unavailable(
    message: str = "The operation could not be completed by a required service.",
) -> HTTPException:
    return api_error(
        status_code=503,
        code="dependency_unavailable",
        message=message,
        retryable=True,
    )


def api_http_error(exc: Exception) -> HTTPException:
    """Map expected public exceptions and sanitize unexpected dependency failures."""

    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, LookupError):
        return not_found(str(exc))
    if isinstance(exc, (TypeError, ValueError)):
        return bad_request(str(exc))
    return dependency_unavailable()


ErrorCode = Literal["bad_request", "not_found", "conflict", "dependency_unavailable"]


__all__ = [
    "ApiErrorDetail",
    "ApiErrorResponse",
    "ErrorCode",
    "ErrorResponse",
    "api_error",
    "api_http_error",
    "bad_request",
    "conflict",
    "dependency_unavailable",
    "not_found",
]
