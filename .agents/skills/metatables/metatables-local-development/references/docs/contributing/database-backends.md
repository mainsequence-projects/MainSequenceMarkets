# Database backend contract tests

This suite is strictly on demand. Run it only when explicitly requested for the
current task. Routine changes and general requests to verify or fix code do not
start containers or trigger this matrix. Prefer focused checks without containers
for everyday development.

Run the same API/client contract against SQLite, PostgreSQL, TimescaleDB, MySQL
and SQL Server:

```sh
python -m scripts.test_databases
```

Use the project's Python environment, with development dependencies and the
[published SDK prerequisite](../client/installation-and-connection.md) installed.
The runner packages that installed SDK checkout into a wheel; it does not copy
credentials or local SDK state. `--sdk-source /path/to/mainsequence-sdk` selects
an explicit checkout. A published installation uses its exact installed version.

Docker Compose must be available. The pinned services are in
`compose.database-tests.yml`. SQL Server needs an x86-64 Docker worker; Apple
Silicon development requires compatible x86 emulation.
The test container includes Microsoft ODBC Driver 18 and all Python drivers.
The runner starts and stops one database engine at a time to avoid competing
database memory allocations. Allow at least 4 GB of free Docker memory for the
SQL Server checks. Existing containers consume that same allocation.
Compose bounds each service's memory, including SQL Server's 2 GB
database memory budget within a 3 GB container. Image downloads and builds also
need several gigabytes of free disk space.

The runner creates an isolated Compose project without publishing database ports.
Databases use disposable storage; SQLite uses temporary files. Each test gets an
empty database. The runner waits for health checks, runs the identical suite for
every selected engine, retains JUnit results and container logs under
`.local/database-tests/results/`, and removes only its own Compose project.

For a targeted development check:

```sh
python -m scripts.test_databases --engines mysql mssql
```

These checks are manual and local; CI does not start databases or run this suite.
A missing server, driver, health check failure, failed test or skipped contract
test fails the local run. Test-only credentials are confined to the isolated
services. The test container checks its SDK interfaces before collecting tests.

The suite covers system schema creation and constraints, explicit Settings
bootstrap, runtime binding, interrupted initialization, drift detection, approved
application migrations, compiled SQL produced by the Python client, managed and
external ownership, protected deletion, time-index replacement and statistics,
and authorization rejection. PostgreSQL-specific extension helpers remain behind
the backend adapter; their existing regression suite runs separately.

Shared routes and operation services depend on `DatabaseBackend` and its
`catalog`, `tables`, `access` and `sql` interfaces. New driver imports and physical adapter
imports in those layers fail `python -m scripts.check_boundaries`.

The access contract runs the same Reader/Writer, Team and namespace grant,
revocation, rollback, catalog isolation, timeout, triggered-write and foreign-key
scenarios on every engine. Engine-specific cases exercise PostgreSQL privileged
routines and column-grant drift, PostgreSQL initialization with `CREATEROLE` and
no superuser, real TimescaleDB hypertables, and interrupted MySQL permission
reconciliation. The MySQL driver extra stays below PyMySQL 1.2: its RSA full-auth
handshake must work for newly created caller accounts, as these tests verify.


The relation-import suite runs discovery, dry-run, strict/partial import,
foreign-key expansion, idempotent identity reuse, view reads, Writer refresh,
revocation, Python client transport, and catalog-only unregistration. It tests
external accounts with actual SELECT-only privileges as well as privileged
accounts configured read-only. An execution listener rejects physical writes,
DDL and permission mutations sent to the external database. Runtime view tests
exercise output-only grants and reject direct/CTE access to ungranted base tables.

The default command runs all five engines sequentially. To select smaller groups:

```sh
python -m scripts.test_databases --engines sqlite postgresql timescale_db mysql
python -m scripts.test_databases --engines mssql
```
