# Tables, queries, and migration operations

## Catalog reads and metadata

Collection filtering returns a grant-filtered page. Detail retrieval, contract
validation, schema graphs, table search and column search apply the same visibility boundary.
Schema graphs include only visible endpoints, preventing a visible table from
revealing hidden related tables. Supported metadata PATCH fields update catalog
state; label replacement is separate from currently unavailable add/remove-label
actions.

Contract validation is independent of physical execution. Existing-resource
validation requires visibility. Introspection requires appropriate access and a
capable current DataSource; it reflects columns, indexes, constraints, and physical
binding back into catalog projections.

## Table search

`GET /meta-tables/search/?q=&limit=` ranks the tables the caller can read
([ADR 0018](../adr/api/0018-table-search.md)). It accepts the list filters and is
also served under `/time-index-meta-tables/search/`, which returns time-index
tables only. The response carries `semantic` and up to `limit` (default 20,
at most 100) results, each with the normal table projection, a fused `score` and
the `matched_columns` whose name or logical name contains a query word.

Each table has one search document built only from its own metadata: identifier,
physical name, description, labels, time index and cadence, namespace and its
description, and every column's name, type, logical name, label and description.
It never names another table. The document is rewritten in every catalog
transaction that changes that metadata, so keyword ranking (BM25 over split and
stemmed words) is never stale. The API embeds documents in the background with the
local `BAAI/bge-small-en-v1.5` model and merges the meaning ranking with reciprocal
rank fusion. Until the model is available, or while a table's vectors embed an
older document, ranking uses keywords only; `semantic` is false while the model is
unavailable. Set `METATABLES_SEARCH_EMBEDDINGS=off` to keep the model from loading.

`GET /meta-tables/{uid}/search-document/` returns that document as
`{"content": "..."}` and serves the Admin's Description tab. It requires table
Reader access and does not query physical rows or change catalog state. The
inherited `/time-index-meta-tables/{uid}/search-document/` route accepts
time-index tables only. Both spellings also work without the trailing slash,
without redirecting.

`PATCH /namespaces/{uid}/` with `{"description": ...}` sets a namespace's
description; it requires Writer access to the namespace.

## Import and bounded relation reads

`GET /data-sources/{source_uid}/relations/` lists the visible tables and views in
the configured default schema, or the optional `physical_schema` query parameter.
It returns the canonical schema and each relation's name, kind, existing
`meta_table_uid`, `importable` flag and `blocked_reason`. This administrator-only
read discovers names without reflecting every column or changing the catalog.
Discovery is bounded by the shared deadline and 8 MiB response limit, but not by
the import operation's 200-relation batch limit.

`POST /meta-tables/import-from-data-source/` accepts a registered `data_source_uid`,
optional `physical_schema`, `relation_names`, `exclude_relation_names`, `namespace`,
`include_views`, `follow_foreign_keys`, `refresh_existing`, `dry_run`, and `strict`.
Preview and strict mode default to true. Discovery/import requires an active
administrator; refreshing existing rows also requires their Writer grant.
The result separates planned changes, committed changes, relation failures,
warnings, stale visibility, and runtime read-admission status.

Import discovers the schema once for planning and reflects the selection in
batches on a shared read connection, including any foreign-key expansion.
Before saving, it rechecks the selected metadata in one fresh batch. SELECT
permission checks return zero rows; external import does not read application
data. The 60-second request deadline and 200-relation limit still apply.

`POST /meta-tables/{table_uid}/read/` accepts `columns`, typed `filters`, `order_by`,
`limit`, `offset`, and `statement_timeout_ms`. It returns `rows`, `columns`,
`has_more`, `limit`, and `offset`. Reader/Writer grants authorize each request.
Only registered columns can be selected, and values are bound parameters.
Non-runtime sources use their stored account for this generated SELECT; arbitrary
SQL and managed mutations retain the runtime source restriction. No external
DDL, DML, permission initialization, role creation, or grants are performed.

`POST /meta-tables/{table_uid}/introspect/` refreshes imported definitions and
projections with Writer authorization. See the [import guide](../client/register-existing-tables.md)
for limits, lifecycle, views, Python calls and Vite navigation.

## Table update pipelines

`GET /meta-tables/{table_uid}/update-graph/` serves the admin table Updates diagram.
The response contains `root_id`, compact `nodes` identified as `table:{uid}` or
`update:{uid}`, and `edges` with `source`, `target`, and `kind`. Registered table
dependencies flow from table to update (`reads`), producers flow from update to
output table (`writes`), and update dependencies flow from upstream to consumer
(`depends_on`). Upstream and downstream traversal is separate, so a shared input
does not pull unrelated sibling producers into the graph.

Only tables the caller can view, and updates with visible output tables, participate.
Hidden nodes cut traversal and never expose their links or metadata. Missing and
hidden roots both return 404; graphs exceeding 500 nodes or 2,000 edges return 409.
This endpoint reads catalog metadata without querying physical rows or changing
execution state. The producer list uses the existing
`GET /time-index-table-updates/?output_table__uid={table_uid}` filter.

## Time-index statistics

`GET /meta-tables/{uid}/stats` serves the table detail Stats tab.
`GET /time-index-meta-tables/{uid}/get-stats/` serves the Python client.
Both routes use the same permission-filtered implementation and return:

```json
{
  "multi_index_stats": {
    "_GLOBAL_": {"min": "2026-01-01T00:00:00Z", "max": "2026-09-29T00:00:00Z"},
    "index_progress": {"SPY": "2026-09-29T00:00:00Z"},
    "index_min": {"SPY": "2026-01-01T00:00:00Z"}
  },
  "multi_index_column_stats": {"price": {"SPY": {"min": 10, "max": 20}}}
}
```

Each field is an object or `null` when no statistics have been stored; explicitly
stored empty objects remain `{}`. Additional stored statistics keys and nested
index coordinates are preserved. Reads return catalog statistics without querying
the physical table, recalculating bounds, or changing stored progress.
Missing, hidden, and relational tables return the same 404 response. A table Reader
grant is sufficient; writes are not required. The `/stats/` spelling is also accepted
without redirecting.

## Registration and finalization

Low-level `register` supports explicit ownership/provisioning intent. Collection
creation reserves Alembic-managed resources. Ordinary Python authoring uses
providers instead of handcrafting those requests.

The API distinguishes server-created physical names in `backend_managed` mode
from authored names in Alembic reservations and external registrations. It checks
scope, duplicate physical identity, logical identifiers, and compatible lifecycle
before accepting a binding.

`finalize-managed` reconciles requested provider-scoped rows with physical state.
The response reports each table separately; failures may coexist with successes.
Only successful reconciliation makes a reserved binding active.

## SQL execution

`POST /meta-tables/execute-operation/` accepts `compiled-sql.v1`, a
`data_source_uid`, the runtime dialect, SQL text, bound parameters, optional
parameter types and limits. It accepts at most 1,000,000 SQL characters. Row limits
default to 1,000 and are capped at 10,000; time limits default to 15 seconds and are
capped at 60 seconds. `operation="select"` selects read mode; the other operation
labels select write mode. They do not classify SQL.

`POST /meta-tables/run-query/` accepts `{"data_source_uid": "…", "sql": "…"}` and
optional `limits`. It uses the same restricted execution path in read mode and
returns the `ok/results/truncated/max_rows/row_count/error` success envelope. Errors
use the standard HTTP error contract. The inherited TimeIndexMetaTable routes
follow the same contract.

Requests declare no table scope. The API submits SQL unchanged through the selected
backend's restricted identity. Native table privileges, or SQLite's engine
callback, enforce all reads and writes, including CTEs and subqueries. Setup and
schema operations establish safeguards before queries are admitted. Imported views
are read-only and validated by the engine adapter; elevated routines cannot provide
an escape, and cascading foreign
keys are not supported on registered PostgreSQL/MySQL/MSSQL tables. Result pages
are fetched from the cursor without rewriting the statement.

See [ADR 0007](../adr/api/0007-database-enforced-table-access.md) for engine protocol
differences, including SQL Server batch transaction semantics and active cancellation.

## Migration connection

`POST /meta-tables/{uid}/migration-connection/` validates the provider identity,
Writer access to its catalog tables and the selected DataSource's write availability.
It returns the configured runtime connection (`uri`, dialect, TLS material, default
schema, DataSource UID and provider table UIDs). A supervised runtime also returns a
lease that the client releases after migration and finalization. Responses use
`Cache-Control: no-store`; callers must keep connection material private.

The client loads its application provider and executes Alembic in its own process.
The database login's existing privileges govern DDL. The API creates no migration
roles, imports no application Python code and accepts no uploaded revisions.
Catalog grants protect connection admission and catalog operations; they do not
sandbox a direct database connection. `ttl_seconds` remains accepted for compatibility
but does not expire the configured database login.

After execution, the client closes its database connection and calls
`finalize-managed` with actual revision IDs (or explicit null at base). Finalization
reconciles physical contracts, dropped provider tables and SQL permission projections.
The client finalizes at most 10 tables per request, the Alembic version table first,
so each request holds the catalog lock briefly and finishes within the hosted request
limit. If a run stops partway, rerunning it finalizes the tables still reserved.
The former `/application-migrations/upgrade/` endpoint and provider allowlist are
removed. MetaTables system migrations run in the hosted deployment's migration Job,
or through Settings in Local mode. See
[ADR 0013](../adr/api/0013-application-owned-migrations.md).
