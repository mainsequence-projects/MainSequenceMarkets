"""MetaTables refusals and failures as the SDK raises them, for the API and client tests.

The SDK errors are built the way the MetaTables client builds them: from an HTTP
response, by ``mainsequence.client.exceptions.raise_for_response``, with the request
payload attached.
"""

from __future__ import annotations

import json
from typing import Any

import requests
from mainsequence.client.exceptions import ApiError, raise_for_response

UPSTREAM_URL = "https://metatables.example.test/api/v1/meta-table/execute-operation/"
SENT_SQL = "INSERT INTO ms_markets__asset VALUES (%(secret_value)s)"


def sdk_error(status_code: int, body: Any, *, headers: dict[str, str] | None = None) -> ApiError:
    """The error the MetaTables client raises for an answer of ``status_code`` and ``body``."""

    response = requests.Response()
    response.status_code = status_code
    response._content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    response.url = UPSTREAM_URL
    response.headers.update(headers or {})
    response.request = requests.Request("POST", UPSTREAM_URL).prepare()
    try:
        raise_for_response(response, payload={"json": {"statement": {"sql": SENT_SQL}}})
    except ApiError as error:
        return error
    raise AssertionError("raise_for_response did not raise")


STATEMENT_TOO_LONG = sdk_error(
    422,
    {
        "detail": [
            {
                "type": "string_too_long",
                "loc": ["body", "statement", "sql"],
                "msg": "String should have at most 1000000 characters",
                "input": SENT_SQL,
                "ctx": {"max_length": 1000000},
            }
        ]
    },
)
