from __future__ import annotations

import os
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519
from mainsequence.server.caller_assertions import (
    ASSERTION_TYPE,
    AuthenticatedCaller,
    CallerAssertionVerifier,
)

OFFLINE_RUNTIME_DATA_SOURCE_UID = "00000000-0000-0000-0000-000000000001"
TEST_CALLER_UID = "5f0c7a52-3b1e-4d7a-9c2e-1a4b6d8e0f13"


class GatewayCallerAssertions(CallerAssertionVerifier):
    """Stand in for the platform gateway that signs every hosted request.

    `create_app()` installs SDK request identity, which refuses a request without
    a valid caller assertion. This verifier signs one for `TEST_CALLER_UID` when a
    request carries none, so tests reach their handlers as an authenticated
    caller, and verifies any assertion a test sends through the SDK unchanged.
    """

    _KEY_ID = "ms-markets-tests"

    def __init__(self) -> None:
        self._signing_key = ed25519.Ed25519PrivateKey.generate()
        public = jwt.algorithms.OKPAlgorithm.to_jwk(
            self._signing_key.public_key(), as_dict=True
        )
        keys = {
            "keys": [
                {
                    "kid": self._KEY_ID,
                    "alg": "EdDSA",
                    "use": "sig",
                    **{name: public[name] for name in ("kty", "crv", "x")},
                }
            ]
        }
        super().__init__(
            issuer="https://platform.ms-markets.test",
            jwks_url="https://platform.ms-markets.test/fastapi/caller-keys/",
            release_uid="0d7e2f6a-6c1b-4e8f-9a3d-2b5c7e9f1a04",
            environment_uid="8a1f3c5e-7b9d-4f2a-8c6e-0d2f4a6b8c15",
            fetch_jwks=lambda: keys,
        )

    def sign(self, user_uid: str = TEST_CALLER_UID, **claims: object) -> str:
        """Sign a caller assertion as the platform does; `claims` override its claims."""

        now = int(time.time())
        payload = {
            "iss": self.issuer,
            "aud": f"urn:mainsequence:fapi:{self.release_uid}",
            "sub": user_uid,
            "resource_release_uid": self.release_uid,
            "organization_environment_uid": self.environment_uid,
            "iat": now,
            "nbf": now,
            "exp": now + 120,
            "team_uids": [],
            "is_organization_admin": False,
            **claims,
        }
        return jwt.encode(
            payload,
            self._signing_key,
            algorithm="EdDSA",
            headers={"kid": self._KEY_ID, "typ": ASSERTION_TYPE},
        )

    def verify(self, assertion: str) -> AuthenticatedCaller:
        return super().verify(assertion or self.sign())


GATEWAY_CALLER_ASSERTIONS = GatewayCallerAssertions()


def pytest_configure(config: pytest.Config) -> None:
    # Runs before any test module imports `apps.v1.main`, whose `create_app()`
    # selects the caller-authentication mode and verifier when it installs
    # request identity.
    os.environ["MAINSEQUENCE_CALLER_AUTH_MODE"] = "assertion"
    CallerAssertionVerifier.from_environment = classmethod(  # type: ignore[method-assign]
        lambda cls, **_: GATEWAY_CALLER_ASSERTIONS
    )


@pytest.fixture
def caller_assertions() -> GatewayCallerAssertions:
    """Sign caller assertions the API under test accepts."""

    return GATEWAY_CALLER_ASSERTIONS


@pytest.fixture
def offline_postgresql_runtime(monkeypatch):
    """Serve a hosted PostgreSQL MetaTables runtime without resolving or calling an API.

    When a repository context leaves `data_source_uid` as `None`, as product code
    does, or no `dialect=` is passed, `metatables.compiled_sql.v1` reads the
    DataSource UID and the SQL dialect together from the Environment-selected
    API runtime through `RuntimeContext.require_data_source_uid()` and
    `RuntimeContext.require_sql_dialect()`. This fixture answers
    `get_runtime_context()` offline with a runtime that satisfies both checks,
    so statement tests compile through the same automatic path.
    """

    import metatables.runtime_context
    from metatables.runtime_contract import RuntimeContext

    runtime = RuntimeContext(
        git_source=None,
        dialect="postgresql",
        paramstyle="pyformat",
        data_source={"uid": OFFLINE_RUNTIME_DATA_SOURCE_UID},
        default_schema="public",
    )
    assert runtime.require_data_source_uid() == OFFLINE_RUNTIME_DATA_SOURCE_UID
    assert runtime.require_sql_dialect() == ("postgresql", "pyformat")

    def get_runtime_context() -> RuntimeContext:
        runtime.require_data_source_uid()
        return runtime

    monkeypatch.setattr(metatables.runtime_context, "get_runtime_context", get_runtime_context)
    return runtime
