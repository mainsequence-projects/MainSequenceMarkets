# Authentication and errors

The [Security model](../security/index.md) defines application administration,
Reader/Writer ownership, live namespace inheritance, and sharing endpoints.

## Hosted requests

The hosted API installs the `mainsequence` SDK's request identity once, when it is
created; the platform's FastAPI launcher requires it before serving a deployment
([ADR 0017](../adr/api/0017-hosted-request-identity.md)). The SDK verifies the
platform-signed caller assertion before any route runs and owns issuer, key
discovery, claim, request-target, signature, and expiry verification. It answers a
missing or invalid assertion with 401 and unavailable key discovery with 503.
Admission then reads the caller from `User.get_logged_user()` and never verifies the
assertion again. Unsigned user headers, Bearer tokens and the runtime's own SDK
account are not identity evidence.

The API installs the integration when the process carries the platform's
caller-assertion configuration, as every hosted deployment does, and accepts no
other SDK mode. Once it is installed, every route not declared in the deployment's
`FASTAPI_PUBLIC_INGRESS` requires a caller, including `/` and the OpenAPI pages;
MetaTables declares no anonymous route. A hosted API started without that
configuration installs nothing, and admission rejects every caller.

The assertion also carries the caller's active Team UIDs and admin flag, which
the SDK exposes on `User.get_logged_user()`. Admission uses them as signed and
performs no User lookup, so workload Users, such as applications and Jobs that run
as their own User, are admitted like people. Each request's assertion states
current facts, so hosted facts are not cached. The API evaluates table/namespace
grants in its runtime database. User and Team facts remain platform-owned; no local
membership registry is used. This adds no authentication mechanism.

## Local requests

A local server binds only a loopback listener supplied by `metatables serve
--local`. Startup establishes the developer's SDK identity and seeds the same
one-hour fact cache used by subsequent requests. Each request checks
loopback peer, exact Host, the private local process token, and browser-origin
policy. Hosted caller assertions are rejected in local mode; request headers
cannot choose an authentication mode or supply another user. Local does not install
the SDK request identity, whose local mode would require a platform Bearer token on
every request.

`METATABLES_LOCAL_ALLOWED_ORIGINS` lists exact loopback browser origins with ports.
The default permits no browser-origin write requests. Native requests without
browser headers use the token and listener checks. Cross-site requests remain
rejected even if another check passes. This is request admission, not a promise
of arbitrary cross-origin browser support.

## Fact freshness

Hosted facts are as fresh as each request's caller assertion, which lives at most
five minutes. For the Local developer, User deactivation, Team membership and admin
changes take effect on the next admission after cache expiry, with a maximum
one-hour cache lifetime. Reads do
not extend that lifetime. Table and namespace grants are checked live against
the catalog, so their revocation does not wait for the platform-fact cache.
An expired entry whose refresh fails returns 503; it cannot supply stale access.
Restart the API after changing its SDK account or endpoint. Worker restarts
discard caches. No cache environment variables are needed.

Environment display metadata is cached separately for one hour, including
not-found and unavailable results. `/runtime-context/` still reads current runtime,
DataSource and bootstrap state and returns `Cache-Control: no-store`.

## Common responses

| Status | Meaning |
| --- | --- |
| 400 | Invalid operation or physical SQL validation/execution rejection. |
| 401 | Missing or invalid caller proof/token. |
| 403 | Request boundary, source access mode, or operation scope denied. |
| 404 | Resource missing or not visible to the current actor. |
| 409 | Lifecycle, capability, protection, reference, or physical-state conflict. |
| 422 | Request/schema validation failure. |
| 503 | Catalog, SDK verification/source access, physical connection, or an uncertain operation outcome is unavailable; or every database connection the API may hold stayed busy (`database_connections_busy`, `Retry-After: 1`). |

Most framework errors use a `detail` field. Some domain operations provide a
structured code and field information. Raw-query validation errors can be returned
inside an `ok: false` result envelope; a 200 response alone does not mean that
query execution succeeded. Batch finalization also carries per-table results.
Read each operation's response schema rather than assuming one universal envelope.

Never log SDK runtime responses, caller proofs, database passwords, migration
credentials, or TLS key material. Error translation exposes safe messages/codes.
An unknown physical commit outcome requires reconciliation, not a blind retry.

## Transfer errors

Data routes return 413 for request/row/response byte limits, 408 for the overall transfer deadline, and 429 `transfer_capacity_exceeded` with `Retry-After: 1` when no data-request slot freed up within the request deadline (each API process runs `serving.concurrency` data requests at once). A 503 `database_connections_busy` with `Retry-After: 1` means every database connection stayed busy until the deadline. In both cases no statement ran, so any request, including SQL and writes, is safe to retry. Existing SQL/driver errors can retain their engine-specific deadline codes and status. Upload conflicts use 409 and uncertainty can use 503. A limit enforced by schema validation can return 422. See [typed client exceptions and recovery](../client/bounded-transfers.md).
