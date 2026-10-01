# Authentication and errors

The [Security model](../security/index.md) defines application administration,
Reader/Writer ownership, live namespace inheritance, and sharing endpoints.

## Hosted requests

The API's request boundary calls the verifier from `mainsequence[server]` for
platform-signed caller assertions. The SDK owns issuer, key discovery, claim,
request-target, signature, and expiry verification. MetaTables only maps
its verified identity and exceptions into request context and HTTP responses.
Unsigned user headers are not identity evidence.

After verification, the API reads the admitted User through the SDK to obtain
current admin status and active Team UIDs. It evaluates table/namespace grants
in its runtime database. User and Team facts remain platform-owned; no local
membership registry is used. The API caches successful User facts for one hour
per caller and runtime; concurrent refreshes share one SDK lookup. Expired facts
are never used if refresh fails. Existing platform User-directory access must permit
the deployment's lookup. This adds no authentication mechanism.

## Local requests

A local server binds only a loopback listener supplied by `metatables serve
--local`. Startup establishes the developer's SDK identity and seeds the same
one-hour fact cache used by subsequent requests. Each request checks
loopback peer, exact Host, the private local process token, and browser-origin
policy. Hosted caller assertions are rejected in local mode; request headers
cannot choose an authentication mode or supply another user.

`METATABLES_LOCAL_ALLOWED_ORIGINS` lists exact loopback browser origins with ports.
The default permits no browser-origin write requests. Native requests without
browser headers use the token and listener checks. Cross-site requests remain
rejected even if another check passes. This is request admission, not a promise
of arbitrary cross-origin browser support.

## Fact freshness

User deactivation, Team membership and admin changes take effect on the next
admission after cache expiry, with a maximum one-hour cache lifetime. Reads do
not extend that lifetime. Table and namespace grants are checked live against
the catalog, so their revocation does not wait for the platform-fact cache.
An expired entry whose refresh fails returns 503; it cannot supply stale access.
Restart the API after changing its SDK account or endpoint. Worker restarts and
runtime-mode changes discard caches. No cache environment variables are needed.

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
| 503 | Catalog, SDK verification/source access, physical connection, or an uncertain operation outcome is unavailable. |

Most framework errors use a `detail` field. Some domain operations provide a
structured code and field information. Raw-query validation errors can be returned
inside an `ok: false` result envelope; a 200 response alone does not mean that
query execution succeeded. Batch finalization also carries per-table results.
Read each operation's response schema rather than assuming one universal envelope.

Never log SDK runtime responses, caller proofs, database passwords, migration
credentials, or TLS key material. Error translation exposes safe messages/codes.
An unknown physical commit outcome requires reconciliation, not a blind retry.

## Transfer errors

Data routes return 413 for request/row/response byte limits, 408 for the overall transfer deadline, and 429 with `Retry-After: 1` when per-process admission capacity is exhausted. Existing SQL/driver errors can retain their engine-specific deadline codes and status. Upload conflicts use 409 and uncertainty can use 503. A limit enforced by schema validation can return 422. See [typed client exceptions and recovery](../client/bounded-transfers.md).
