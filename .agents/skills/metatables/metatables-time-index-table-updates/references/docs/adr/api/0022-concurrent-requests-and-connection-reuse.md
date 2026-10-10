# ADR 0022: Concurrent requests per pod and reused database connections

Status: Accepted.

Implementation status: implemented on development. Unit tests pass; deployment
verification, the MySQL and SQL Server container suites and the load test against the
development deployment are pending.

Owner: this repository.

Related decisions: [ADR 0007](0007-database-enforced-table-access.md) (each User
queries as their own login roles), [ADR 0012](0012-bounded-data-transfer-and-safe-retries.md)
(deadlines, cancellation and the shared SQL security guard),
[ADR 0001](0001-unified-api-storage-and-local-sqlite.md) (`configuration.yaml`),
[ADR 0008](0008-mysql-mssql-table-workflows.md) (MySQL and SQL Server) and
[ADR 0021](../agent/0021-api-serves-the-analyst-tools-over-mcp.md) (MCP tools call the
API's own routes).

## Context

The hosted API must serve tens to hundreds of clients at the same time. Main Sequence
runs it as identical pods, each running one Uvicorn process, and adds pods under load
up to a maximum. A Python process runs Python code on one core at a time, so a pod's
capacity comes from threads that wait on the database, and the API's capacity from the
number of pods.

Today:

- Nearly every route is a plain `def`, so each request runs on one of the process's 40
  worker threads, AnyIO's fixed default.
- The catalog engine uses SQLAlchemy's default pool: 5 connections plus 10 overflow,
  with a 30 s wait.
- Each SQL request opens a new connection as the caller's login role and closes it
  afterwards: a TCP and TLS handshake, a password check and a new database backend for
  every request. MySQL and SQL Server build a whole engine per request, and physical
  data-source operations build and dispose of one per call.
- A SQL request holds two connections at once: its catalog transaction keeps the shared
  SQL security guard (ADR 0012) while the login-role query runs.
- ADR 0012's admission runs at most 8 data requests per process (`run-query`, `read`,
  inserts and the other data actions) and answers 429 after a 1 s wait for a slot,
  whatever the thread count.
- Nothing relates the connections all pods may open to what the database allows.

A burst therefore opens connections as fast as requests arrive, spends latency and
database CPU on connecting, and can exhaust the database's connection limit.

## Decision

One number, **T**, sizes a pod: the requests it runs at once and the connections it may
hold.

| Part | Rule |
| --- | --- |
| Threads | Route handlers run on T threads per process. |
| Catalog | The catalog pool holds at most T connections, with no overflow, and closes each at the maximum age. |
| Data requests | ADR 0012's admission runs T data requests at once per process, not 8, and a request waits for a slot within its deadline instead of 1 s. `/runtime-context/` publishes the effective T as `transfer_limits.concurrent_requests`. |
| Login-role connections | A pod holds at most T login-role connections per database server, idle or in use. A connection is reused only by the login role that opened it, never by another role and never through `SET ROLE` (ADR 0007). |
| Data-source operations | Physical data-source operations reuse connections per (DataSource, login), through one kept engine on MySQL and SQL Server, instead of connecting per call; they count against the same cap. |
| Budget | Maximum pods × 3T ≤ the database's `max_connections`, minus a reserve for migrations, the Admin and other clients: per pod, T catalog connections, T capped connections, and about T per-call connections (see below). Each server the API connects to has its own budget. |
| Setting | `configuration.yaml` declares T as `serving.concurrency`. Local runtimes use the default. |

Rules for reused connections:

- Each use sets its own statement timeout, read-only or write mode, and search path.
  Nothing carries over from a previous use: on PostgreSQL, `DISCARD ALL` returns the
  session to its defaults before the connection is reused.
- On MySQL and SQL Server, a login-role connection closes after each use. Neither
  driver can reset a session, and SQL Server may keep a session's role memberships.
  These connections still count against the cap; the DataSource's own login is reused.
- A connection that errored, was cancelled, or stopped before its result was read is
  closed, not reused. ADR 0012 already forbids draining a read to return a connection.
- Idle connections close after a timeout, and every connection closes at a maximum age.
  The maximum age bounds how long a connection outlives a password change or a disabled
  login. Grant changes apply at once, because the database checks privileges on every
  statement.
- When the cap is full, the least recently used idle connection closes to make room. If
  none is idle, the request waits within its deadline (ADR 0012) and then fails with 503,
  `database_connections_busy` and `Retry-After: 1`. No statement ran, so a retry is safe.
- MCP tool calls keep their own threads. The route calls a tool makes count against T
  like any request. Sharing T would let tool calls hold every thread while their own
  route calls wait.
- Connection probes that bring their own host or timeout (DataSource validation and
  maintenance), relation discovery and reads, and MySQL's administrative connections
  (grant changes and `KILL QUERY`) connect per call, outside the cap. A pod's T threads
  bound them to about T, the third T in the budget. A relation read holds its reader
  while it runs the caller's login-role query; counting both against one cap could
  leave every thread waiting for a second connection.

### Suggested values

These are starting values, not measurements. A load test against the development
deployment replaces them.

| Setting | Suggested | Why |
| --- | --- | --- |
| Pod CPU | 1 vCPU | One process uses one core. |
| Pod memory | 2 GiB | About 160 MiB at idle, plus results in flight. |
| Minimum pods | 2 | A burst lands on two pods while more start, and one survives a restart. |
| T | 20 | At the current maximum of 10 pods: 3 × 20 × 10 = 600 connections. |
| Idle timeout | 60 s | Long enough to reuse a role's connection across a session of requests. |
| Maximum age | 30 min | Bounds a connection's life after a credential change. |

The workflow declares CPU, memory and minimum pods for the `metatables` resource;
`configuration.yaml` declares T. T is raised only when the budget allows it.

The workflow also declares the platform's per-replica request policy
(platform issues 921 and 922): `container_concurrency` equal to T, so the platform sends a pod
no more requests than it has threads and queues the rest while it adds pods, and
`max_scale` equal to the budget's maximum pods (10). Changing T changes both files.

## Consequences

- On PostgreSQL most requests reuse a connection; a role's first request on a pod still
  connects. On MySQL and SQL Server, caller SQL and caller table operations still connect
  per request, though their engines are kept.
- Connections are bounded by configuration, not by traffic.
- A pod runs at most T requests at once; further requests wait for a thread. Capacity
  grows by adding pods.
- Many Users share one cap per pod, so a pod serving many Users reconnects more often
  than one serving few.
- A reused connection stays logged in as its role until its idle timeout or maximum age.
- SQLite has no login roles; only the thread count applies locally.
- Changing T is a configuration change and a deployment.

Verification: unit tests (`tests/integrations/test_connection_reuse.py`) cover role
isolation, per-use settings and the session reset, closing broken connections, the cap
and eviction, waiting within the deadline, the idle timeout and maximum age, T applied
to the route threads, the catalog pool and data-request admission, and the kept engines. The hosted engines,
including the MySQL and SQL Server behavior above, are verified through the container
suite on request, and a load test against the development deployment sets the values
above.
