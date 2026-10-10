# ADR 0017: Hosted caller identity through the SDK request identity

Date: 2026-10-04

Status: Accepted.

Implementation status: implemented for 0.1.21. Tests cover the hosted entrypoint's
launcher declaration, genuine EdDSA caller assertions verified by the SDK, rejected
callers, Local isolation, and PodDeploymentOrchestrator's own launcher run against
the deployed entrypoint. A hosted rollout has not yet been verified.

Owner: MetaTables API. The SDK owns caller verification
([SDK 9.0.6 ADR 0036: Request-scoped logged user](https://github.com/mainsequence-sdk/mainsequence-sdk/blob/v9.0.6/docs/adr/0036-request-scoped-logged-user.md));
the platform's FastAPI launcher owns the startup check.

Related decisions: [ADR 0001](0001-unified-api-storage-and-local-sqlite.md) (one API
execution path, with Local for development), [ADR 0002](0002-application-administration-and-table-ownership.md)
(admission and platform facts) and [ADR 0007](0007-database-enforced-table-access.md)
(the API authenticates the caller; the database enforces grants).

## Context

Since 2026-09-28 the platform's FastAPI launcher serves an application only when
`app.state.mainsequence_request_identity` declares the installed SDK integration,
the deployment's caller mode (`assertion` when hosted) and its public ingress
(`FASTAPI_PUBLIC_INGRESS`). The SDK's `install_request_identity(app)` sets that
declaration. MetaTables verified caller assertions itself, in its admission
dependency, and never installed the integration. Every hosted revision after
0.1.13 therefore stopped at startup with "Application request identity is not
installed" while traffic stayed on the 0.1.13 revision
([#34](https://github.com/mainsequence-projects/MetaTables/issues/34)).

## Decision

- The application factory installs the SDK request identity once, after mounting
  every route, for the hosted runtime only. Its middleware is the outermost
  application middleware, so callers are verified before local admission,
  transfer limits or any route.
- It installs it when the process carries the platform's caller-authentication
  configuration: any of `MAINSEQUENCE_CALLER_AUTH_MODE`, `APP_NAME`,
  `FASTAPI_PUBLIC_BASE_URL`, `MAINSEQUENCE_CALLER_ASSERTION_ISSUER` or
  `MAINSEQUENCE_CALLER_ASSERTION_JWKS_URL`. The SDK and the launcher select their
  mode from the same variables, and every hosted deployment carries them.
- The hosted API accepts only platform caller assertions. If the SDK would select
  another mode, creating the app fails; incomplete trust configuration also fails
  at startup. Without any of these variables nothing is installed, no caller is
  ever bound, and admission rejects every caller with 401.
- The SDK verifies each assertion once, before the route: missing or invalid proof
  is 401 and unavailable key discovery is 503. Admission takes the caller's User UID
  from `User.get_logged_user()` and the verified target Environment from the request
  state the SDK records. It no longer reads the assertion header or calls the
  verifier. The SDK verifier keeps no replay record, so assertions are not
  single-use; a second verification would only repeat key discovery and could
  disagree at the expiry boundary.
- Local and developer runtimes never install it. The SDK's local mode requires a
  Bearer token on every request and validates it against the platform, while Local
  admits requests through its loopback listener and the launcher's private token
  with the developer's SDK user resolved at startup. Local clients send no Bearer
  token, so the SDK would reject every Local request. `metatables serve --local`
  runs its own uvicorn worker, which the platform launcher never checks.
- `metatables.api.app.main:app` is created on first access. Importing the factory,
  as the Local worker and the hosted entrypoint do, builds no extra app and cannot
  fail because a shell carries a platform variable.
- MetaTables declares no anonymous route. The SDK copies the deployment's
  `FASTAPI_PUBLIC_INGRESS` into the declaration unchanged; every other route,
  including `/`, `/docs` and `/openapi.json`, requires a caller.
- The direct verifier dependency, `metatables.api.app.auth.caller_assertions`, is
  removed so that no route can verify an assertion a second time.

## Consequences

- Who may call what is unchanged. The caller is still the User in a platform-signed
  assertion for this release and Environment. Admin and Team facts, the one-hour
  fact cache, table and namespace grants and database enforcement are unchanged.
  Unsigned User headers, the runtime's own SDK account and Bearer tokens never
  identify a hosted caller.
- New hosted revisions pass the launcher's check and can roll out. The SDK
  requirement stays `mainsequence>=9.0.6,<10`, which provides the integration.
- Hosted routes without an admission dependency (`/` and the OpenAPI pages) now also
  require a verified caller; the platform ingress already authenticated those
  requests. A numeric `X-User-Id` header is rejected with 401.
- The SDK answers rejected callers itself with `{"detail": ...}`, so MetaTables'
  error handler no longer logs them. The launcher's request log records each
  request's authentication outcome.
- The SDK and the launcher look for public ingress routes among the app's top-level
  routes. FastAPI 0.142 keeps included routers unflattened, so a route mounted
  through a router cannot be declared public; startup would refuse it. MetaTables
  declares none.

## Amendment: caller facts from the assertion (2026-10-05)

Since platform ADR-0048, applications and Jobs run as their own workload User.
`User.get_by_uid` lists people and the requester's own row only, so admission's
User lookup failed for every workload caller and the request was refused with 503
([#37](https://github.com/mainsequence-projects/MetaTables/issues/37)).

- The platform signs the caller's active Team UIDs and Organization-admin flag into
  every caller assertion. SDK 9.0.9 verifies them and exposes them on
  `User.get_logged_user()` as `team_uids` and `is_organization_admin`. Hosted
  admission takes the caller's facts from there and looks up no User.
- Hosted facts are not cached; each request's assertion, which lives at most five
  minutes, states them. The one-hour fact cache now serves only the developer's
  Local and developer-mode admission, which is unchanged.
- An assertion without the facts, from a platform that predates them, admits the
  caller with no Teams and no admin access.
- This needs SDK 9.0.9 or later. ADR 0002's amendment on caller-visible
  principals raises the requirement to `mainsequence>=9.0.14,<10`.

## Verification

`tests/auth/test_request_identity.py` imports the deployed entrypoint under a
simulated hosted environment and checks its declaration, verifies genuine EdDSA
assertions signed with a test key served as the platform's key document, and checks
rejected callers, a key outage, the other runtimes and the refused modes. With
`PYTHONPATH` naming PodDeploymentOrchestrator's `src` directory, it also runs that
launcher's `require_request_identity` and `serve_fastapi` against the entrypoint.
`tests/auth/test_local_mode.py` shows Local admission is unchanged when a shell
carries hosted variables, and that the SDK's local mode would reject Local clients.
`tests/auth/test_request_identity.py` and `tests/auth/test_platform_fact_cache.py`
admit a workload caller with the Teams and admin flag its assertion carries, without
a User lookup.
