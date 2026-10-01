# ADR 0004: Execute approved application migrations inside the API

> Amendment (2026-10-01): [ADR 0013](0013-application-owned-migrations.md) establishes application-owned
> client Alembic execution using the configured environment connection. Its DDL
> privileges belong to the environment database role. It supersedes this ADR's
> conflicting application-migration execution and credential restrictions;
> governed API operations and MetaTables system migrations remain separate.


Date: 2026-09-29

Status: Superseded by [ADR 0013](0013-application-owned-migrations.md) on 2026-10-01.

The original decision below is retained as history; it is no longer the implementation contract.

Owner: MetaTables API.

## Context

[ADR 0002](0002-application-administration-and-table-ownership.md) disables direct
application migration credentials. The tutorial debugger starts a reader on an
empty catalog. Setup must create and migrate its tables on the selected runtime
without opening a client database connection.

## Decision

Code-owned deployment configuration maps aliases to reviewed, installed Alembic
providers. `POST /application-migrations/upgrade/` accepts only an alias, resolves
the active runtime DataSource, and executes the provider head inside the API.
Callers cannot upload Python/revisions, choose a database or target revision,
request a downgrade, or obtain a database credential.

The API reuses authoring contract builders, reservation and physical finalization.
Existing tables require Writer access; creation follows existing namespace and
creator grant rules. Admin status does not bypass existing table grants. Provider
identity and parent bindings must match. Unversioned physical tables are not
silently adopted or stamped.

Alembic commands are serialized in process. Catalog mutation locks serialize
reservations and journal transitions; a database transaction checks grants again
before DDL. The operation journal records physical migration work. An uncertain
outcome stops subsequent setup until reconciliation. Finalization can be repeated
after a committed migration without recreating tables.

Revision code is trusted deployment code: approving a provider requires reviewing
its full revision stream and effects. This is not a sandbox for caller-supplied
code. Direct connections and general client-side Alembic execution remain disabled.
Local SQLite and hosted PostgreSQL use the same API operation. System migrations
remain explicit Settings operations.

## Example integration

`examples/scripts/setup_metatables.py` only reserves, upgrades and finalizes the
tutorial provider. Every data-dependent tutorial command calls it first. VS Code
launches then seed instruments and run producers through `--prepare-data` before
the requested example. Offline preview and endpoint-only connect skip preparation.
API endpoint discovery is pinned across setup and the example.

## Verification

`test_example_setup_migrates_via_api_and_reuses_the_selected_runtime` covers default
SQLite, a selected SQLite file, and PostgreSQL with actual HTTP and database DDL.
It verifies empty sample tables after setup, preserved UIDs/data after restart,
seeding/producers/reading, and rejection of unapproved providers, DataSource
overrides, and Reader callers. Launch-order tests use both checked-in debug
configurations and stop the example on migration failure.
