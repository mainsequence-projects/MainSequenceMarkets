---
name: metatables-upgrade-legacy-app
description: "Upgrade consuming applications from MainSequence 8.x MetaTables or older extracted clients to the installed metatables package. Use for legacy imports, removed SQL scopes, repository compilers, application migration-provider integration and provider modules that collide with other installed packages. Excludes MetaTables client/API implementation and ordinary schema revision authoring."
---

# Upgrade a legacy MetaTables application

## Scope and references

Update the consuming application to the installed client's current contract.
Removed scope APIs are intentional; do not restore them in the client or create
application compatibility shims. Keep identity/login and Git source integration
in the MainSequence SDK.

Read `docs/client/upgrade-legacy-app.md` for the conversion table and before/after
repository compiler examples. In a copied skill, resolve the `docs/` and
`src/metatables/examples/` paths here relative to this skill's `references/` directory. In the
MetaTables source checkout, resolve them from the repository root.

Use `docs/client/installation-and-connection.md` to establish the target package
and compatible SDK versions. Refresh copied skills after a client upgrade with
`metatables copy-metatables-skills`. Inspect the installed public exports and CLI
help before mapping an unfamiliar old interface; avoid broad import rewrites.

## Find and replace legacy usage

Inspect dependency pins, table imports, shared repository compilers and their
callers, runtime setup, and existing Alembic provider integration. Useful search
terms are `mainsequence.client.metatables`, `mainsequence.meta_tables`,
`MetaTableOperationScopeTable`, `MetaTableOperationScope`, `scope_tables`, and
`application_migration_providers`.

For SQL operations:

- Import public table resources from `metatables` and the compiler from
  `metatables.compiled_sql.v1`.
- Send SQL and a DataSource. The API executes as the authenticated user, and the
  selected engine enforces that user's table permissions on actual SQL access.
  Removing the declared table list does not remove table permissions.
- Delete scope classes, `scope_tables`, and scope-only wrappers or parameters,
  including `models`, `access`, aliases or `reserved_policy` when they serve only
  scope construction. Update callers and old nested wire payloads together.
- Do not substitute per-query catalog lookups, registration/binding preflights,
  local permission checks or SQL parsing for the removed scope machinery.
  Registration/finalization remain table lifecycle operations. Preserve separate
  application business rules.
- Let the compiler obtain DataSource and dialect from the selected API runtime,
  or supply both explicitly for offline compilation. Never use a MetaTable UID as
  a DataSource UID or infer a new database from the retired table list.
- Preserve the query's physical bindings, bound parameters, result behavior,
  execution mode, offsets, row limits, statement deadlines and HTTP timeouts.
  `select` selects read execution; the other operation labels select write
  execution. These labels do not classify the SQL statement.

Read `docs/client/query-and-mutate.md` for current query behavior and
`docs/adr/api/0007-database-enforced-table-access.md` for the decision. The retained
`compiled-sql.v1` label does not make the old scoped payload compatible.

## Upgrade application migration integration

Keep the existing provider `package=` value, namespace, model registry,
version-table binding and applied revision history. Update bootstrap/import wiring
to the installed client's public migration interfaces. Do not scaffold a replacement
provider, rewrite applied history or stamp the database to bypass an upgrade issue.

### Move a provider whose module name collides

A provider installed under a generic top-level module, such as `migrations`,
shares files and imports with every other installed package that chose the same
name. Move it under a module the application owns, for example `ledger.migrations`
or `ledger_migrations`:

- Move the provider package with its `env.py`, `script.py.mako` and `versions/`
  tree.
- Update `script_location`, `version_location_prefix`, the `env.py` import,
  imports inside the provider, packaging configuration, and every provider
  reference in code, scripts and jobs.
- Keep `package=`, `migration_namespace`, the version-table binding and the
  revision files unchanged. The catalog binds provider tables to
  `package:namespace` and rejects a reservation from a different key. Alembic
  stores only revision IDs, so the module path can change.
- Do not ship a module under the old name. A forwarding module would keep the
  file collision.

Then confirm that `migrations current` reports the same revision as before the
move, and that the built wheel no longer installs the old top-level name.

Providers load in the application process from Python references such as
`ledger.migrations:migration`. The client executes Alembic with the environment
connection; the API handles authorization, reservations and finalization. The
environment operator supplies database DDL privileges. Remove retired API provider
allowlists and aliases; the API needs no application provider code installed.
MetaTables' internal catalog migrations remain a separate history.

Use the [application migrations skill](../metatables-migrations/SKILL.md),
`docs/client/define-and-migrate-tables.md`, and
`docs/adr/api/0013-application-owned-migrations.md` for that workflow. Ordinary
SQL continues through the governed API, independently of the migration connection.
If the application's deployment workflow does not yet run its providers in a
migration Job before its API and agents roll out, add one as
`docs/client/deploy-application-migrations.md` describes.

## Verify the upgrade

Run imports and offline compilation first. The guide includes an example that
needs no registration, credentials or running API. Check actual query parameters,
mode and limits; use existing tests for application business behavior. Review
provider loading and unchanged Alembic history. Remove obsolete tests that assert
scope construction rather than recreating that behavior to make them pass.

For application execution checks, follow the
[local development skill](../metatables-local-development/SKILL.md), verify the
actual local runtime, and exercise the smallest relevant workflow. Respect the
requested scope for database mutations; a client upgrade alone does not authorize
hosted migrations. Distinguish offline verification from API execution and from
hosted-engine verification in the result.
