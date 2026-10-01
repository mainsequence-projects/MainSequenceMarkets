# 0043. SDK 9 And MetaTables Client Hard Cut For The 2.0 Package Contract

## Status

Accepted and implemented for `ms-markets` 2.0.0. Supersedes the dependency and
CLI parts of [ADR 0039](0039-sdk-8-hard-cut-and-1-0-package-contract.md) and the
CLI references in [ADR 0022](0022-alembic-metatable-migration-alignment.md) and
[ADR 0024](0024-namespace-scoped-alembic-version-locations.md); the provider
design those ADRs record is unchanged.

## Context

Main Sequence SDK 9 no longer contains MetaTables. Table resources, the
time-index table updaters, the compiled SQL protocol, the `dtype` codec, and the
application Alembic migration interfaces moved to the separate
`mainsequence-metatable` distribution, imported as `metatables`, with its own
`metatables` CLI. Identity and login, Git source context, CodeRepository, jobs,
and agents remain in the SDK.

The extracted client also removed the SQL operation scope intentionally. A
compiled operation previously declared every MetaTable it touched, with an
access mode and reservation policy per table, and the API could derive the
DataSource from that list. Now an operation sends SQL with one DataSource; the
API executes as the authenticated user and the database enforces that user's
table permissions on the tables the SQL actually touches.

SDK 9 also replaced request-header context binding with request identity
injected by the platform into `request.state.user`.

## Decision

- `ms-markets` 2.x requires `mainsequence>=9.0.2,<10` and
  `mainsequence-metatable>=0.1.6,<0.2`, without exact patch pins. These floors
  are the releases in which the SDK-owned agent skills refresh offline, the
  client takes the DataSource and dialect from the API runtime, the client
  wheel ships only the `metatables` packages, and hosted discovery selects the
  `metatables` deployment of the caller's Organization Environment. The lock
  and exported requirements select the validated releases. SDK 8 and earlier
  are unsupported; there are no fallback imports, aliases, or shims.
- MetaTables imports use the `metatables` public exports, `metatables.updaters`,
  `metatables.migrations`, `metatables.dtype_codec`, and
  `metatables.compiled_sql.v1`. Other SDK imports are unchanged.
- The shared repository compiler follows the client's legacy-upgrade contract:
  `compile_markets_statement(statement, *, context, operation, dialect=None)`.
  The `models=` and `access=` parameters, `scope_table(...)` methods,
  `MarketsMetaTableHandle.meta_table_uid_for_model(...)`, and the
  `reserved_policy` field of the repository context and table handle are
  deleted. `data_source_uid`, limits, offsets, statement deadlines, HTTP
  timeouts, the namespace, and the `select` (read) versus other labels (write)
  execution semantics are preserved. Product code leaves `data_source_uid` as
  `None`: the client takes the DataSource and dialect together from the runtime
  of the Environment-selected MetaTables API and raises
  `metatables.DataSourceResolutionError` when that runtime has no usable
  DataSource. An explicit DataSource must match the runtime unless a dialect is
  also supplied for offline compilation. ms-markets does not add SQL parsing,
  per-query catalog lookups, or local permission checks.
- Read-service executor callbacks receive only the statement, because the
  table list they also received existed only to build the deleted scope.
- The migration provider stays `migrations:migration` with the same package,
  namespace, model registry, version-table binding, revision IDs, and applied
  history. Admin commands use
  `metatables migrations ... --provider migrations:migration`.
- Authenticated FastAPI routes read the platform-injected `request.state.user`.
- The breaking change ships as `ms-markets` 2.0.0. Dependent packages declare
  `ms-markets>=2,<3`.

## Consequences

- Installers reject SDK 8 environments for `ms-markets` 2.x. SDK 8 projects stay
  on `ms-markets` 1.x.
- Callers of `compile_markets_statement(...)` remove `models=` and `access=`;
  callers that built repository contexts with `reserved_policy=` remove it;
  code that read `operation.scope.data_source_uid` reads
  `operation.data_source_uid`; executor callbacks take one argument.
- `mainsequence-metatable` requires SQLAlchemy 2.1, whose PostgreSQL compiler
  renders typed bind casts such as `%(direction_0)s::SMALLINT` in compiled SQL.
- Hosted applications configure neither an API URL nor a DataSource: the
  caller's Organization Environment selects the MetaTables deployment, and its
  runtime supplies the DataSource and dialect.
- No database schema migration is introduced. Upgrading the client does not
  authorize applying migrations to a hosted database.
- Version-matched MetaTables agent skills live under `.agents/skills/metatables/`
  and are refreshed with `metatables copy-metatables-skills --path .` after a
  client upgrade.
