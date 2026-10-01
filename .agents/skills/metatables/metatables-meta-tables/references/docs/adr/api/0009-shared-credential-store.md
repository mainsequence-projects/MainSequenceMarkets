# ADR 0009: Shared CredentialStore with cross-platform local key management

> Amendment (2026-10-01): [ADR 0013](0013-application-owned-migrations.md) establishes application-owned
> client Alembic execution using the configured environment connection. Its DDL
> privileges belong to the environment database role. It supersedes this ADR's
> conflicting application-migration execution and credential restrictions;
> governed API operations and MetaTables system migrations remain separate.


Date: 2026-09-30

Status: Accepted. Implemented by the API CredentialStore providers and catalog
revision `0006_local_credentials`.

Owner: MetaTables API. Related decisions:
[storage](0001-unified-api-storage-and-local-sqlite.md),
[administration](0002-application-administration-and-table-ownership.md),
[database permissions](0007-database-enforced-table-access.md), and
[backend contract](0008-mysql-mssql-table-workflows.md).

## Context

The connection test accepts an entered password directly. Previously, saving
always called SDK `Secret.create`, and connections independently called
`Secret.get_by_uid`. SDK Secrets require the hosted execution context. An admin
on an unregistered local branch could test a database successfully and then get
503 when saving it. Read-only access was unrelated to the failure.

DataSources retain one model, schema, table and UUID-shaped password/TLS reference
fields. Credential persistence needs one application service contract, selected
at runtime composition. It must not introduce another authorization layer or
engine-specific registration workflows.

## Decision

### One contract, two storage providers

The internal `CredentialStore` exposes:

| Operation | Meaning |
| --- | --- |
| `create(value, purpose) -> UUID` | Persist a new credential and return its opaque reference. |
| `resolve(uid, purpose) -> str` | Resolve it inside the API for the declared purpose. |
| `delete(uid)` | Explicitly remove an unreferenced credential. |

Registration, replacement, draft/saved validation, bootstrap and database
connections receive the selected store. There is no default SDK resolver inside
connection adapters. An unconfigured dependency fails explicitly.

**Hosted uses the existing Main Sequence SDK Secrets service.** It calls
`Secret.create`, `Secret.get_by_uid` and `Secret.destroy_by_uid`. Existing hosted
UUIDs remain unchanged. MetaTables adds no encryption envelope, local key, local
credential import, or second key lifecycle to hosted Secrets. Their admission,
protection, rotation and recovery remain owned by the managed service.

**Local uses encrypted records in the selected MetaTables catalog.** Its SQL
provider borrows the caller's session, never commits/closes it, and participates
in the same transaction as the DataSource mutation. Password replacement creates
a new record; rollback leaves the previous reference intact. Existing credentials
are not silently deleted. Explicit deletion takes the shared catalog mutation
lock and checks every DataSource password/TLS reference.

The hosted service cannot join a SQL transaction. A failed registration attempts
to delete only the newly created SDK Secrets as compensation. It never changes or
deletes pre-existing Secrets. An unavailable managed service can leave an orphan
requiring its normal administrative cleanup.

The same contract covers database passwords, TLS CA certificates, client
certificates and private keys. Preserve content and whitespace; bound UTF-8 input
to 1 MiB. Values remain write-only. Neither browser/client nor runtime-context
receives plaintext, ciphertext or key material. Database adapters receive resolved
connection settings, through their existing DatabaseBackend contract.

### Private local persistence

`credential_vault` contains a persistent catalog identity, active key identifier
and authenticated checks for provisioned keys. `credential` contains UUID,
purpose, key ID, format version, nonce, ciphertext, creator UID and creation time.
These are private system tables in the same schema as DataSource. Shared Alembic
migrations create the same models on every supported engine. Base64 encodings use
portable text columns; MySQL uses LONGTEXT for encrypted PEM material.

UUID-shaped configuration field names remain compatible, including the existing
`*_secret_uid` names. Local references resolve in the local store; hosted
references resolve through SDK Secrets. There are no reference prefixes, automatic
credential transfers or mode-switch migrations. Catalog selection and execution
binding remain separate responsibilities of the existing runtime.

Only the API account accesses local credentials. The catalog's existing protected
system-table rules exclude them from governed SQL and application migration
providers. Existing admin checks authorize registration and credential changes;
existing Reader/Writer grants authorize use of connections. A reference confers
no new permission. Remote source registrations may coexist with the local SQLite
runtime row; execution still accepts only the selected runtime source.

### Local encryption and key provisioning

Use `cryptography` AES-256-GCM with a fresh 96-bit nonce for each write. Associated
data authenticates catalog identity, credential UID, purpose, key ID and format
version. Authenticated key checks distinguish an incorrect key from a valid key.
Tampering fails without returning partial plaintext. Both `cryptography` and
`keyring` are direct package dependencies.

Keys stay outside SQL and ordinary configuration. The key provider is selected
once from `configuration.yaml`:

| Provider | Platforms |
| --- | --- |
| `native` (default) | macOS Keychain, Windows Credential Locker, Linux Secret Service or KWallet, using explicitly approved keyring backends. |
| `file` with `key_directory` | Protected key files on macOS, Windows and Linux, including injected secret volumes, headless services and CI. |

Native services must be available to the API service account. Null, plaintext and
arbitrary auto-selected keyring backends are never fallbacks. File provisioning
uses exclusive creation, private Unix ownership/permissions, or restricted Windows
ACLs; reads reject symlinks, public access and malformed keys. File names identify
catalog UUID and key ID, never credential values.

Explicit local Settings migration/initialization provisions the first key. The
admin CLI can initialize keys after migrations. Startup and normal resolve do
not generate keys. If existing catalog key metadata exists, initialization loads
and verifies that key; it cannot replace a missing or incorrect key. Missing,
locked or inaccessible material leaves runtime-context and Settings available
with a specific credential-store error.

Cross-platform interfaces are implemented. macOS Keychain provisioning and reload
were verified with a temporary API-owned key, subsequently removed. This cannot
establish Windows/Linux native service behavior. The protected-file integration
is exercised with real local files and a fresh Python process; OS-specific
coverage must additionally run on its corresponding host.

### Bootstrap, restart and lifecycle

Local SQLite opens using the existing API-owned file binding, before credential
lookup. Hosted bootstrap resolves the selected connection's UUID through SDK
Secrets before opening the catalog. Its credential never depends on opening the
database that needs that password. Saved selection JSON holds only public
settings and UUID references.

A fresh local catalog must receive explicit system migrations before saving
sources/credentials. Local saves never substitute JSON for encrypted SQL storage.
Previously saved local candidate metadata can be materialized by explicit setup,
retaining DataSource UIDs. Hosted pre-catalog registration continues to use SDK
Secrets and its existing metadata registry; it becomes the runtime row during
explicit setup. Startup never silently applies migrations.

`metatables credentials` provides admin-only local operations:

- `initialize`: provision/verify the local root key after catalog migration.
- `import-sdk`: explicitly import existing local SDK references, preserving UUIDs,
  verifying decryption and affected enabled connections, then commit. Failed
  imports roll back; retry skips already imported references. It never deletes
  platform Secrets or runs automatically on lookup.
- `rotate-key KEY_ID`: provision a new local key and re-encrypt resumable batches.
  Record UIDs remain stable. Per-record key IDs support mixed batches on restart.
- `remove-unused UUID`: explicitly delete a local credential after reference checks.

Retain old keys until current records and retained backups no longer need them.
Back up the encrypted catalog and key material separately. Restoring the same
catalog identity and keys permits recovery; a database backup without keys does
not reveal credentials. Provider changes require supplying the original keys.
Hosted backup and rotation remain managed Secret operations.

### Application feedback

Existing `/runtime-context/` exposes only provider, status and an actionable
credential-store error. Settings and the source form show that state through
Command Center SDK components. A successful transient connection test says the
connection succeeded; it does not claim credentials have been saved.

Credential failures distinguish catalog initialization, provider/key availability,
incorrect keys, authentication failure, missing references and hosted Secret
access. Provider exception bodies are suppressed. Existing endpoints, runtime
selection, authentication, admin checks and table grants retain their authority.

## Verification requirements

- Real local SQL registration, rollback, password replacement, read-only sources,
  and restart succeed without any SDK Secret call.
- A fresh Python process resolves credentials with the same catalog and keys.
- Wrong/missing keys, ciphertext/nonce/metadata tampering and purpose misuse fail;
  missing keys are never replaced.
- Source references protect deletion; key rotation preserves UUIDs and is resumable.
- Hosted create/resolve/delete delegate to SDK Secrets without calling local crypto
  or key provisioning. Existing hosted bootstrap remains usable before catalog open.
- Password and TLS material never enter registration responses, public selection
  JSON, diagnostics or logs. Draft connection tests persist no credentials.
- New system tables remain inaccessible to caller SQL identities and application
  migration providers. Shared migrations and large encrypted values must pass
  the existing engine matrix on PostgreSQL, TimescaleDB, MySQL and MSSQL.
- Native keyring integration and Windows ACL enforcement require their respective
  OS integration runs; source or mocked tests alone are not proof of those services.

## References

- [keyring native backends](https://keyring.readthedocs.io/en/stable/).
- [cryptography AESGCM](https://cryptography.io/en/stable/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM).
